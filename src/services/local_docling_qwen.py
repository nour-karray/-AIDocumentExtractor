from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.services.document_preprocessing import PreprocessingError, preprocess_document


class LocalPipelineError(RuntimeError):
    pass


DOCUMENT_TYPE_BY_MODE = {
    "medical": "medical_lab_report",
    "steg": "steg_invoice",
    "supplier": "supplier_invoice",
    "receipt": "receipt",
}

SCHEMA_NAMES = {
    "medical_lab_report": "schema.medical_lab_report.v1",
    "steg_invoice": "schema.steg_invoice.v1",
    "receipt": "schema.receipt.v1",
    "supplier_invoice": "schema.supplier_invoice.v1",
    "unknown": "schema.unknown.v1",
}

REQUIRED_FIELDS = {
    "medical_lab_report": ("patient_info.patient_name", "tests"),
    "steg_invoice": ("reference", "numero_compteur", "date_facture", "montant_a_payer"),
    "receipt": ("store_name", "total"),
    "supplier_invoice": ("invoice_number", "summary.total_amount"),
}

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp"}
_PADDLE_OCR: Any | None = None


@dataclass(frozen=True)
class ExtractionContent:
    text: str
    source: str
    docling_markdown: str
    docling_quality: dict[str, Any]
    fallback_used: bool
    preprocessing: dict[str, Any] | None = None
    fallback_quality: dict[str, Any] | None = None
    docling_error: str | None = None
    fallback_error: str | None = None


def _json_from_text(text: str) -> dict[str, Any]:
    text = (text or "").strip()
    if not text:
        raise LocalPipelineError("Qwen n'a retourne aucun texte.")
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass

    match = re.search(r"\{.*\}", text, flags=re.S)
    if not match:
        raise LocalPipelineError("Qwen n'a pas retourne un JSON exploitable.")
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError as exc:
        raise LocalPipelineError(f"JSON Qwen invalide: {exc}") from exc
    if not isinstance(data, dict):
        raise LocalPipelineError("Le JSON Qwen doit etre un objet.")
    return data


def _docling_to_markdown(file_path: Path) -> str:
    try:
        from docling.document_converter import DocumentConverter
    except ImportError as exc:
        raise LocalPipelineError(
            "Docling n'est pas installe. Lance: python -m pip install docling"
        ) from exc

    try:
        converter = DocumentConverter()
        result = converter.convert(str(file_path))
        document = result.document
        if hasattr(document, "export_to_markdown"):
            markdown = document.export_to_markdown()
        elif hasattr(document, "export_to_text"):
            markdown = document.export_to_text()
        else:
            markdown = str(document)
    except Exception as exc:
        raise LocalPipelineError(f"Docling n'a pas pu convertir le document: {exc}") from exc

    markdown = (markdown or "").strip()
    if not markdown:
        raise LocalPipelineError("Docling a produit un Markdown vide.")
    return markdown


def _markdown_quality(markdown: str) -> dict[str, Any]:
    text = markdown or ""
    stripped = text.strip()
    lines = [line.strip() for line in stripped.splitlines() if line.strip()]
    words = re.findall(r"\w+", stripped, flags=re.UNICODE)
    digits = re.findall(r"\d", stripped)
    table_lines = [line for line in lines if line.count("|") >= 2]
    replacement_chars = stripped.count("\ufffd")
    noisy_chars = len(re.findall(r"[^\w\s.,;:!?%/\\|+()\\[\\]{}<>=\\-_'\"@#&$]", stripped, flags=re.UNICODE))
    char_count = len(stripped)
    noise_ratio = (replacement_chars + noisy_chars) / max(char_count, 1)

    score = 0.0
    if char_count >= 250:
        score += 25.0
    elif char_count >= 80:
        score += 12.0
    if len(words) >= 45:
        score += 25.0
    elif len(words) >= 15:
        score += 12.0
    if len(lines) >= 6:
        score += 15.0
    elif len(lines) >= 3:
        score += 7.0
    if table_lines:
        score += 20.0
    if len(digits) >= 8:
        score += 10.0
    if noise_ratio <= 0.04:
        score += 5.0
    else:
        score -= min(20.0, noise_ratio * 100.0)

    score = round(max(0.0, min(100.0, score)), 1)
    usable = score >= 55.0 and char_count >= 120 and len(words) >= 25
    reasons: list[str] = []
    if char_count < 120:
        reasons.append("Texte trop court")
    if len(words) < 25:
        reasons.append("Peu de mots exploitables")
    if noise_ratio > 0.08:
        reasons.append("Texte bruite")
    if not table_lines:
        reasons.append("Aucun tableau Markdown detecte")
    return {
        "score": score,
        "usable": usable,
        "characters": char_count,
        "words": len(words),
        "lines": len(lines),
        "tableLines": len(table_lines),
        "digitCount": len(digits),
        "noiseRatio": round(noise_ratio, 4),
        "reasons": reasons,
    }


def _paddleocr_lines_for_image(image_path: Path) -> list[str]:
    ocr = _get_paddleocr()
    try:
        if hasattr(ocr, "ocr"):
            result = ocr.ocr(str(image_path), cls=True)
        else:
            result = ocr.predict(input=str(image_path))
    except Exception as exc:
        raise LocalPipelineError(f"PaddleOCR n'a pas pu lire l'image: {exc}") from exc

    lines: list[str] = []

    def visit(value: Any) -> None:
        if isinstance(value, str):
            text = value.strip()
            if text:
                lines.append(text)
            return
        if isinstance(value, dict):
            for key in ("text", "rec_text", "transcription"):
                text = value.get(key)
                if isinstance(text, str) and text.strip():
                    lines.append(text.strip())
            for item in value.values():
                visit(item)
            return
        if isinstance(value, (list, tuple)):
            if len(value) >= 2 and isinstance(value[1], (list, tuple)) and value[1]:
                text = value[1][0]
                if isinstance(text, str) and text.strip():
                    lines.append(text.strip())
            for item in value:
                visit(item)

    visit(result)
    deduped = list(dict.fromkeys(line for line in lines if len(line) > 1))
    return deduped


def _get_paddleocr() -> Any:
    global _PADDLE_OCR
    if _PADDLE_OCR is not None:
        return _PADDLE_OCR
    try:
        from paddleocr import PaddleOCR
    except ImportError as exc:
        raise LocalPipelineError(
            "PaddleOCR n'est pas installe. Lance: python -m pip install paddleocr"
        ) from exc

    try:
        try:
            _PADDLE_OCR = PaddleOCR(use_angle_cls=True, lang="fr")
        except TypeError:
            _PADDLE_OCR = PaddleOCR(lang="fr")
    except Exception as exc:
        raise LocalPipelineError(f"PaddleOCR n'a pas pu demarrer: {exc}") from exc
    return _PADDLE_OCR


def _paddleocr_to_text(file_path: Path) -> str:
    try:
        timeout_seconds = max(float(os.getenv("LOCAL_PIPELINE_PADDLEOCR_TIMEOUT_SECONDS", "12")), 3.0)
    except ValueError:
        timeout_seconds = 12.0
    if timeout_seconds <= 0:
        return _paddleocr_to_text_raw(file_path)

    project_root = Path(__file__).resolve().parents[2]
    code = (
        "import sys\n"
        "from pathlib import Path\n"
        "from src.services.local_docling_qwen import _paddleocr_to_text_raw\n"
        "print(_paddleocr_to_text_raw(Path(sys.argv[1])), end='')\n"
    )
    env = os.environ.copy()
    env["PYTHONPATH"] = str(project_root) + os.pathsep + env.get("PYTHONPATH", "")
    try:
        completed = subprocess.run(
            [sys.executable, "-c", code, str(file_path)],
            cwd=str(project_root),
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        raise LocalPipelineError(
            f"PaddleOCR a depasse {int(timeout_seconds)} secondes; fallback OCR local rapide utilise."
        ) from exc
    if completed.returncode != 0:
        message = (completed.stderr or completed.stdout or "").strip()
        raise LocalPipelineError(f"PaddleOCR a echoue: {message[:400]}")
    text = completed.stdout.strip()
    if not text:
        raise LocalPipelineError("PaddleOCR n'a retourne aucun texte.")
    return text


def _paddleocr_to_text_raw(file_path: Path) -> str:
    suffix = file_path.suffix.lower()
    image_paths: list[Path] = []
    temp_dir: tempfile.TemporaryDirectory[str] | None = None
    try:
        if suffix == ".pdf":
            try:
                import fitz
            except ImportError as exc:
                raise LocalPipelineError("PyMuPDF est requis pour rendre un PDF avant PaddleOCR.") from exc
            temp_dir = tempfile.TemporaryDirectory()
            doc = fitz.open(str(file_path))
            try:
                for page_index in range(min(len(doc), 3)):
                    page = doc.load_page(page_index)
                    pixmap = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
                    image_path = Path(temp_dir.name) / f"page_{page_index + 1}.png"
                    pixmap.save(str(image_path))
                    image_paths.append(image_path)
            finally:
                doc.close()
        else:
            image_paths.append(file_path)

        lines: list[str] = []
        for image_path in image_paths:
            lines.extend(_paddleocr_lines_for_image(image_path))
        text = "\n".join(lines).strip()
        if not text:
            raise LocalPipelineError("PaddleOCR n'a retourne aucun texte.")
        return text
    finally:
        if temp_dir is not None:
            temp_dir.cleanup()


def _fast_tesseract_to_text(file_path: Path, mode: str) -> str:
    try:
        import cv2
        import numpy as np
        import pytesseract

        from src.extraction.steg_invoice_extractor import configure_tesseract
    except Exception as exc:
        raise LocalPipelineError(f"OCR local rapide indisponible: {exc}") from exc

    configure_tesseract()
    suffix = file_path.suffix.lower()
    temp_dir: tempfile.TemporaryDirectory[str] | None = None
    image_paths: list[Path] = []
    try:
        if suffix == ".pdf":
            try:
                import fitz
            except ImportError as exc:
                raise LocalPipelineError("PyMuPDF est requis pour rendre un PDF avant OCR local.") from exc
            temp_dir = tempfile.TemporaryDirectory()
            doc = fitz.open(str(file_path))
            try:
                for page_index in range(min(len(doc), 2)):
                    page = doc.load_page(page_index)
                    pixmap = page.get_pixmap(matrix=fitz.Matrix(1.7, 1.7), alpha=False)
                    image_path = Path(temp_dir.name) / f"page_{page_index + 1}.png"
                    pixmap.save(str(image_path))
                    image_paths.append(image_path)
            finally:
                doc.close()
        else:
            image_paths.append(file_path)

        try:
            max_side = max(int(os.getenv("LOCAL_PIPELINE_FAST_OCR_MAX_SIDE", "1600")), 900)
        except ValueError:
            max_side = 1600
        try:
            tesseract_timeout = max(float(os.getenv("LOCAL_PIPELINE_FAST_OCR_TIMEOUT_SECONDS", "15")), 3.0)
        except ValueError:
            tesseract_timeout = 15.0
        lang = os.getenv("LOCAL_PIPELINE_FAST_OCR_LANG", "eng").strip() or "eng"
        psm_values = (6, 11) if mode in {"medical", "auto"} else (6,)
        chunks: list[str] = []
        for image_path in image_paths:
            image = cv2.imread(str(image_path))
            if image is None:
                continue
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
            height, width = gray.shape[:2]
            longest = max(height, width, 1)
            if longest > max_side:
                scale = max_side / float(longest)
                gray = cv2.resize(
                    gray,
                    (max(1, int(width * scale)), max(1, int(height * scale))),
                    interpolation=cv2.INTER_AREA,
                )
            variants = [gray]
            try:
                clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
                variants.append(clahe.apply(gray))
            except Exception:
                pass
            best = ""
            for variant in variants:
                for psm in psm_values:
                    try:
                        text = pytesseract.image_to_string(
                            variant,
                            lang=lang,
                            config=f"--oem 3 --psm {psm}",
                            timeout=tesseract_timeout,
                        ).strip()
                    except RuntimeError:
                        continue
                    if len(text) > len(best):
                        best = text
            if best:
                chunks.append(best)
        merged = "\n".join(chunks).strip()
        if not merged:
            raise LocalPipelineError("OCR local rapide n'a retourne aucun texte.")
        return merged
    finally:
        if temp_dir is not None:
            temp_dir.cleanup()


def _ocr_text_with_fallback(file_path: Path, mode: str) -> tuple[str, str, str | None]:
    try:
        return _paddleocr_to_text(file_path), "paddleocr_text", None
    except LocalPipelineError as exc:
        text = _fast_tesseract_to_text(file_path, mode)
        return text, "tesseract_fast_text", str(exc)


def _content_for_extraction(
    file_path: Path,
    *,
    mode: str,
    preprocessing: dict[str, Any] | None = None,
) -> ExtractionContent:
    if file_path.suffix.lower() in IMAGE_SUFFIXES:
        ocr_text, source, ocr_warning = _ocr_text_with_fallback(file_path, mode)
        fallback_markdown = "# OCR fallback image\n\n" + ocr_text
        fallback_quality = _markdown_quality(fallback_markdown)
        return ExtractionContent(
            text=fallback_markdown,
            source=source,
            docling_markdown="",
            docling_quality=_markdown_quality(""),
            fallback_used=True,
            preprocessing=preprocessing,
            fallback_quality=fallback_quality,
            docling_error=(
                "Image/scan: OCR fallback direct pour eviter un traitement Docling trop long."
                + (f" PaddleOCR: {ocr_warning}" if ocr_warning else "")
            ),
        )

    docling_error: str | None = None
    try:
        markdown = _docling_to_markdown(file_path)
    except LocalPipelineError as exc:
        markdown = ""
        docling_error = str(exc)

    docling_quality = _markdown_quality(markdown)
    if docling_quality["usable"]:
        return ExtractionContent(
            text=markdown,
            source="docling_markdown",
            docling_markdown=markdown,
            docling_quality=docling_quality,
            fallback_used=False,
            preprocessing=preprocessing,
            docling_error=docling_error,
        )

    try:
        ocr_text, source, ocr_warning = _ocr_text_with_fallback(file_path, mode)
        fallback_markdown = "# PaddleOCR fallback\n\n" + ocr_text
        fallback_quality = _markdown_quality(fallback_markdown)
        return ExtractionContent(
            text=fallback_markdown,
            source=source,
            docling_markdown=markdown,
            docling_quality=docling_quality,
            fallback_used=True,
            preprocessing=preprocessing,
            fallback_quality=fallback_quality,
            docling_error=docling_error,
            fallback_error=ocr_warning,
        )
    except LocalPipelineError as exc:
        fallback_error = str(exc)
        if docling_error:
            fallback_error = f"{docling_error} | {fallback_error}"
        if not docling_quality["usable"]:
            raise LocalPipelineError(
                "Docling a produit un contenu insuffisant et le fallback PaddleOCR est indisponible. "
                f"{fallback_error}"
            ) from exc
        raise LocalPipelineError(fallback_error) from exc


def _ollama_generate(host: str, model: str, prompt: str) -> dict[str, Any]:
    host = (host or os.getenv("OLLAMA_HOST") or "http://127.0.0.1:11434").rstrip("/")
    model = (model or os.getenv("OLLAMA_MODEL") or "qwen2.5:7b-instruct").strip()
    try:
        timeout_seconds = max(float(os.getenv("OLLAMA_GENERATE_TIMEOUT_SECONDS", "90")), 10.0)
    except ValueError:
        timeout_seconds = 90.0
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "format": "json",
        "options": {
            "temperature": 0,
            "num_ctx": max(int(os.getenv("OLLAMA_NUM_CTX", "4096")), 2048),
            "num_predict": max(int(os.getenv("OLLAMA_NUM_PREDICT", "512")), 128),
        },
    }
    request = urllib.request.Request(
        f"{host}/api/generate",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            raw = response.read().decode("utf-8", errors="replace")
    except urllib.error.URLError as exc:
        raise LocalPipelineError(
            f"Ollama ne repond pas sur {host}. Lance Ollama puis: ollama pull {model}"
        ) from exc

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise LocalPipelineError(f"Reponse Ollama invalide: {exc}") from exc
    text = str(data.get("response") or "")
    return _json_from_text(text)


def _schema_text_for(target: str) -> str:
    common = """
Return ONLY valid JSON. No markdown fence.
Use one of these document_type values:
medical_lab_report, steg_invoice, supplier_invoice, receipt, unknown.
Do not invent values. Use empty strings for missing scalar fields and [] for missing arrays.
"""

    medical = """
For medical_lab_report:
{
  "document_type": "medical_lab_report",
  "lab_info": {"lab_name": "", "doctor_name": ""},
  "patient_info": {"patient_name": "", "patient_id": "", "date_of_birth": "", "sex": ""},
  "document_metadata": {"exam_number": "", "dossier_number": "", "received_date": "", "edited_date": "", "request_date": "", "sample_date": "", "report_date": "", "page_number": "", "organization": ""},
  "tests": [{"raw_test_name": "", "value": "", "unit": "", "reference_range": "", "status": "normal|low|high|unknown"}]
}
"""

    steg = """
For steg_invoice:
{
  "document_type": "steg_invoice",
  "reference": "", "numero_compteur": "", "date_facture": "", "montant_a_payer": "", "date_limite_paiement": "",
  "periode_du": "", "periode_au": "", "coupon_reference_raw": "", "coupon_montant": "",
  "confidence_note": "high|medium|low"
}
"""

    receipt = """
For receipt:
{
  "document_type": "receipt",
  "store_name": "", "date": "", "time": "", "ticket_number": "",
  "currency": "", "items": [{"description": "", "quantity": "", "unit_price": "", "line_total": ""}],
  "total": "", "payment_method": ""
}
"""

    supplier = """
For supplier_invoice:
{
  "document_type": "supplier_invoice",
  "invoice_number": "", "invoice_date": "", "due_date": "", "currency": "",
  "seller": {"name": "", "address": "", "tax_id": "", "iban": "", "email": "", "phone": ""},
  "client": {"name": "", "address": "", "tax_id": "", "email": "", "phone": ""},
  "items": [{"description": "", "quantity": "", "unit": "", "unit_price": "", "net_amount": "", "tax_rate": "", "tax_amount": "", "gross_amount": ""}],
  "summary": {"subtotal": "", "tax_total": "", "discount": "", "shipping": "", "total_amount": "", "amount_due": ""}
}
"""
    if target == "medical_lab_report":
        return common + medical
    if target == "steg_invoice":
        return common + steg
    if target == "receipt":
        return common + receipt
    if target == "supplier_invoice":
        return common + supplier
    return common + medical + steg + receipt + supplier


def _target_document_type(mode: str) -> str:
    return DOCUMENT_TYPE_BY_MODE.get(mode, "auto")


def _prompt_for(content: str, mode: str, *, content_source: str) -> str:
    target = _target_document_type(mode)
    schema = _schema_text_for(target)
    try:
        content_limit = max(int(os.getenv("LOCAL_PIPELINE_CONTENT_CHARS", "16000")), 4000)
    except ValueError:
        content_limit = 16000
    return f"""You extract business fields from documents.
Target mode: {target}
If target mode is auto, infer the document_type from the content.
Do not invent values. Use empty strings for missing fields.
Content source: {content_source}

{schema}

DOCUMENT CONTENT:
{content[:content_limit]}
"""


def _clean_str(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _document_type(data: dict[str, Any], mode: str) -> str:
    forced = DOCUMENT_TYPE_BY_MODE.get(mode)
    raw = _clean_str(data.get("document_type")).lower()
    if forced:
        return forced
    if raw in {"medical_lab_report", "steg_invoice", "supplier_invoice", "receipt"}:
        return raw
    keys = " ".join(data.keys()).lower()
    if "montant_a_payer" in keys or "reference" in keys:
        return "steg_invoice"
    if "patient" in keys or "tests" in keys or "analyses" in keys:
        return "medical_lab_report"
    if "invoice" in keys or "seller" in keys:
        return "supplier_invoice"
    if "store" in keys or "ticket" in keys:
        return "receipt"
    return "unknown"


def _pipeline_meta(
    host: str,
    model: str,
    content: ExtractionContent,
    *,
    doc_type: str,
    validation: dict[str, Any],
) -> dict[str, Any]:
    return {
        "docling": True,
        "preprocessing": content.preprocessing,
        "paddleocr_fallback": content.fallback_used,
        "content_source": content.source,
        "markdown_quality": content.docling_quality,
        "fallback_quality": content.fallback_quality,
        "docling_error": content.docling_error,
        "fallback_error": content.fallback_error,
        "document_type_detection": {
            "mode": doc_type if doc_type != "unknown" else "unknown",
            "schema": SCHEMA_NAMES.get(doc_type, SCHEMA_NAMES["unknown"]),
        },
        "validation": validation,
        "ollama_host": host,
        "ollama_model": model,
    }


def _warnings_from(data: dict[str, Any]) -> list[Any]:
    warnings = data.get("warnings")
    return warnings if isinstance(warnings, list) else []


def _nested_value(payload: dict[str, Any], path: str) -> Any:
    current: Any = payload
    for part in path.split("."):
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


def _is_filled(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, list):
        return len(value) > 0
    if isinstance(value, dict):
        return any(_is_filled(item) for item in value.values())
    return True


def _validate_business_payload(doc_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    errors: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []
    for field in REQUIRED_FIELDS.get(doc_type, ()):
        if not _is_filled(_nested_value(payload, field)):
            errors.append({"code": "REQUIRED_FIELD_MISSING", "field": field})

    if doc_type in {"steg_invoice", "receipt", "supplier_invoice"}:
        text = json.dumps(payload, ensure_ascii=False)
        if re.search(r"\d+[,.]\d{3,}", text) is None and re.search(r"\d+[,.]\d{2}", text) is None:
            warnings.append({"code": "AMOUNT_FORMAT_UNCLEAR", "field": "amounts"})

    if doc_type == "medical_lab_report":
        tests = payload.get("tests")
        if not isinstance(tests, list) or not tests:
            errors.append({"code": "NO_MEDICAL_TESTS", "field": "tests"})

    return {
        "valid": not errors,
        "errors": errors,
        "warnings": warnings,
    }


def _attach_pipeline(
    payload: dict[str, Any],
    *,
    host: str,
    model: str,
    content: ExtractionContent,
    doc_type: str,
) -> dict[str, Any]:
    validation = _validate_business_payload(doc_type, payload)
    payload["local_pipeline"] = _pipeline_meta(
        host,
        model,
        content,
        doc_type=doc_type,
        validation=validation,
    )
    warnings = payload.get("warnings")
    if not isinstance(warnings, list):
        warnings = []
    for item in validation["warnings"]:
        warnings.append(item)
    if content.fallback_error:
        warnings.append({"code": "PADDLEOCR_FALLBACK_UNAVAILABLE", "message": content.fallback_error})
    if validation["errors"]:
        warnings.append({"code": "BUSINESS_VALIDATION_ERRORS", "message": "Certains champs obligatoires sont absents."})
    payload["warnings"] = warnings
    return payload


def _medical_payload(data: dict[str, Any], content: ExtractionContent, *, host: str, model: str) -> dict[str, Any]:
    lab = _as_dict(data.get("lab_info"))
    patient = _as_dict(data.get("patient_info"))
    meta = _as_dict(data.get("document_metadata"))
    raw_tests = _as_list(data.get("tests") or data.get("analyses"))
    tests: list[dict[str, Any]] = []
    for row in raw_tests:
        if not isinstance(row, dict):
            continue
        ref = row.get("reference_range")
        rr = ref if isinstance(ref, dict) else {"raw_text": _clean_str(ref)}
        value_raw = row.get("value")
        value: float | None = None
        value_text = _clean_str(value_raw)
        try:
            value = float(value_text.replace(",", ".")) if value_text else None
            value_text = ""
        except ValueError:
            value = None
        tests.append(
            {
                "raw_test_name": _clean_str(row.get("raw_test_name") or row.get("test_name") or row.get("name")),
                "normalized_name": _clean_str(row.get("normalized_name") or "unknown") or "unknown",
                "category": _clean_str(row.get("category") or "other") or "other",
                "value_text": value_text or None,
                "value": value,
                "secondary_value": None,
                "previous_value": None,
                "unit": _clean_str(row.get("unit")) or None,
                "reference_range": rr,
                "status": _clean_str(row.get("status") or "unknown") or "unknown",
                "raw_line": _clean_str(row.get("raw_line")),
                "confidence": 0.85,
                "notes": _clean_str(row.get("notes")) or None,
            }
        )
    payload = {
        "document_type": "medical_lab_report",
        "lab_info": {
            "lab_name": _clean_str(lab.get("lab_name")) or None,
            "doctor_name": _clean_str(lab.get("doctor_name")) or None,
        },
        "patient_info": {
            "patient_name": _clean_str(patient.get("patient_name")) or None,
            "patient_id": _clean_str(patient.get("patient_id")) or None,
            "date_of_birth": _clean_str(patient.get("date_of_birth")) or None,
            "sex": _clean_str(patient.get("sex")) or None,
        },
        "document_metadata": {
            "exam_number": _clean_str(meta.get("exam_number")) or None,
            "dossier_number": _clean_str(meta.get("dossier_number")) or None,
            "received_date": _clean_str(meta.get("received_date")) or _clean_str(meta.get("sample_date")) or None,
            "edited_date": _clean_str(meta.get("edited_date")) or _clean_str(meta.get("report_date")) or None,
            "request_date": _clean_str(meta.get("request_date")) or None,
            "sample_date": _clean_str(meta.get("sample_date")) or None,
            "report_date": _clean_str(meta.get("report_date")) or None,
            "page_number": _clean_str(meta.get("page_number")) or None,
            "organization": _clean_str(meta.get("organization")) or None,
            "source_file": None,
            "document_type": "medical_lab_report",
        },
        "tests": tests,
        "warnings": _warnings_from(data),
        "raw_text": content.text[:80000],
        "extraction_source": "hybrid_docling_paddleocr_qwen",
    }
    return _attach_pipeline(payload, host=host, model=model, content=content, doc_type="medical_lab_report")


def _steg_payload(data: dict[str, Any], content: ExtractionContent, *, host: str, model: str) -> dict[str, Any]:
    payload = {
        "reference": _clean_str(data.get("reference")) or None,
        "numero_compteur": _clean_str(data.get("numero_compteur")) or None,
        "date_facture": _clean_str(data.get("date_facture")) or None,
        "montant_a_payer": _clean_str(data.get("montant_a_payer")) or None,
        "date_limite_paiement": _clean_str(data.get("date_limite_paiement")) or None,
        "periode_du": _clean_str(data.get("periode_du")) or None,
        "periode_au": _clean_str(data.get("periode_au")) or None,
        "coupon_reference_raw": _clean_str(data.get("coupon_reference_raw")) or None,
        "coupon_montant": _clean_str(data.get("coupon_montant")) or None,
        "confidence_note": _clean_str(data.get("confidence_note") or "medium"),
        "raw_text": content.text[:80000],
        "extraction_source": "hybrid_docling_paddleocr_qwen",
        "warnings": _warnings_from(data),
    }
    return _attach_pipeline(payload, host=host, model=model, content=content, doc_type="steg_invoice")


def _receipt_payload(data: dict[str, Any], content: ExtractionContent, *, host: str, model: str) -> dict[str, Any]:
    payload = {
        "store_name": _clean_str(data.get("store_name")),
        "date": _clean_str(data.get("date")),
        "time": _clean_str(data.get("time")),
        "ticket_number": _clean_str(data.get("ticket_number")),
        "currency": _clean_str(data.get("currency")),
        "items": [row for row in _as_list(data.get("items")) if isinstance(row, dict)],
        "total": _clean_str(data.get("total")),
        "payment_method": _clean_str(data.get("payment_method")),
        "raw_text": content.text[:80000],
        "warnings": _warnings_from(data),
        "extraction_source": "hybrid_docling_paddleocr_qwen",
    }
    return _attach_pipeline(payload, host=host, model=model, content=content, doc_type="receipt")


def _supplier_payload(data: dict[str, Any], content: ExtractionContent, *, host: str, model: str) -> dict[str, Any]:
    payload = {
        "document_type": "supplier_invoice",
        "invoice_number": _clean_str(data.get("invoice_number")),
        "invoice_date": _clean_str(data.get("invoice_date")),
        "due_date": _clean_str(data.get("due_date")),
        "currency": _clean_str(data.get("currency")),
        "seller": _as_dict(data.get("seller")),
        "client": _as_dict(data.get("client")),
        "items": [row for row in _as_list(data.get("items")) if isinstance(row, dict)],
        "summary": _as_dict(data.get("summary")),
        "confidence": _clean_str(data.get("confidence") or "medium"),
        "missing_fields": _as_list(data.get("missing_fields")),
        "raw_notes": _clean_str(data.get("raw_notes")),
        "raw_text": content.text[:80000],
        "warnings": _warnings_from(data),
        "extraction_source": "hybrid_docling_paddleocr_qwen",
    }
    return _attach_pipeline(payload, host=host, model=model, content=content, doc_type="supplier_invoice")


def extract_with_docling_qwen(
    file_path: Path,
    *,
    mode: str = "auto",
    ollama_host: str = "http://127.0.0.1:11434",
    model: str = "qwen2.5:7b-instruct",
) -> tuple[str, dict[str, Any]]:
    ollama_host = (ollama_host or os.getenv("OLLAMA_HOST") or "http://127.0.0.1:11434").rstrip("/")
    model = (model or os.getenv("OLLAMA_MODEL") or "qwen2.5:7b-instruct").strip()
    with tempfile.TemporaryDirectory() as prep_dir:
        try:
            preprocessed = preprocess_document(file_path, Path(prep_dir))
        except PreprocessingError as exc:
            raise LocalPipelineError(f"Pretraitement impossible: {exc}") from exc
        content = _content_for_extraction(
            preprocessed.path,
            mode=mode,
            preprocessing=preprocessed.metadata,
        )
        raw = _ollama_generate(ollama_host, model, _prompt_for(content.text, mode, content_source=content.source))
        doc_type = _document_type(raw, mode)
        if doc_type == "medical_lab_report":
            return "medical_local", _medical_payload(raw, content, host=ollama_host, model=model)
        if doc_type == "steg_invoice":
            return "steg_local", _steg_payload(raw, content, host=ollama_host, model=model)
        if doc_type == "receipt":
            return "receipt_local", _receipt_payload(raw, content, host=ollama_host, model=model)
        if doc_type == "supplier_invoice":
            return "supplier_invoice_local", _supplier_payload(raw, content, host=ollama_host, model=model)
        payload = {
            "document_type": "unknown",
            "fields": raw,
            "warnings": [{"code": "UNKNOWN_DOCUMENT_TYPE", "message": "Type de document non reconnu par Qwen."}],
            "raw_text": content.text[:80000],
            "extraction_source": "hybrid_docling_paddleocr_qwen",
        }
        payload = _attach_pipeline(payload, host=ollama_host, model=model, content=content, doc_type="unknown")
        return "document_local", payload
