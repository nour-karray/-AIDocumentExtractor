from __future__ import annotations

import os
import re
import tempfile
import time
import unicodedata
from pathlib import Path
from typing import Dict, List, Optional

import cv2
import pytesseract

from src.extraction.medical_analysis_extractor import (
    extract_combined_ocr_text,
    extract_fields_from_medical,
    extract_fields_from_medical_text,
    extract_result_rows_from_medical_ocr_data,
)
from src.extraction.steg_invoice_extractor import configure_tesseract, normalize_digits
from src.models.schemas import (
    DocumentMetadata,
    LabInfo,
    LabTest,
    MedicalDocumentResult,
    PatientInfo,
    ProcessingWarning,
    ReferenceRange,
)
from src.services.document_preprocessing import preprocess_document
from src.services.gemini_llm import analyze_medical_document_gemini


def _extract_pdf_text(file_path: Path) -> tuple[str, list[ProcessingWarning]]:
    try:
        from pypdf import PdfReader
    except ImportError:
        return "", [
            ProcessingWarning(
                code="PDF_TEXT_READ_UNAVAILABLE",
                message="Le module 'pypdf' est indisponible ; le texte embarque du PDF sera ignore.",
                context=str(file_path),
            )
        ]

    try:
        reader = PdfReader(str(file_path))
        raw_text = "\n".join([(p.extract_text() or "") for p in reader.pages]).strip()
        return raw_text, []
    except Exception as exc:
        return "", [
            ProcessingWarning(code="PDF_TEXT_READ_FAILED", message=str(exc), context=str(file_path))
        ]


def _render_pdf_first_page(file_path: Path, png_path: Path) -> list[ProcessingWarning]:
    pymupdf_warnings: list[ProcessingWarning] = []
    try:
        import fitz

        with fitz.open(str(file_path)) as doc:
            if len(doc) == 0:
                return [ProcessingWarning(code="PDF_NO_PAGE", message="Aucune page convertie")]
            page = doc.load_page(0)
            matrix = fitz.Matrix(2.4, 2.4)
            pix = page.get_pixmap(matrix=matrix, alpha=False)
            pix.save(str(png_path))
            return []
    except ImportError:
        pass
    except Exception as exc:
        pymupdf_warnings.append(
            ProcessingWarning(code="PYMUPDF_RENDER_FAILED", message=str(exc), context=str(file_path))
        )

    try:
        from pdf2image import convert_from_path
    except ImportError:
        return pymupdf_warnings + [
            ProcessingWarning(
                code="PDF_RENDER_UNAVAILABLE",
                message="Les modules de rendu PDF sont indisponibles ; impossible de rasteriser ce PDF.",
                context=str(file_path),
            )
        ]

    try:
        pages = convert_from_path(str(file_path), dpi=200, first_page=1, last_page=1)
    except Exception as exc:
        return pymupdf_warnings + [
            ProcessingWarning(code="PDF_RENDER_FAILED", message=str(exc), context=str(file_path))
        ]

    if not pages:
        return pymupdf_warnings + [ProcessingWarning(code="PDF_NO_PAGE", message="Aucune page convertie")]

    pages[0].save(png_path)
    return []


def _to_float(value: Optional[str]) -> Optional[float]:
    if not value:
        return None
    txt = str(value).strip().replace(" ", "").replace(",", ".")
    try:
        return float(txt)
    except ValueError:
        return None


def _parse_reference_range(raw: Optional[str]) -> Optional[ReferenceRange]:
    if not raw:
        return None
    txt = raw.replace(",", ".")
    nums: List[float] = []
    for token in txt.replace("a", " ").replace("à", " ").replace("-", " ").split():
        try:
            nums.append(float(token))
        except ValueError:
            pass
    if len(nums) >= 2:
        return ReferenceRange(min=min(nums), max=max(nums), raw_text=raw)
    return ReferenceRange(raw_text=raw)


def _normalize_name(raw_name: str) -> str:
    n = raw_name.lower()
    mapping: Dict[str, List[str]] = {
        "tsh": ["tsh", "thyreostimuline"],
        "vitamin_d": ["vitamine d", "hydroxy", "25-oh"],
        "glucose": ["glycem", "glucose"],
        "cholesterol_total": ["cholesterol total"],
        "hdl_cholesterol": ["hdl"],
        "ldl_cholesterol": ["ldl"],
        "triglycerides": ["triglycer"],
        "creatinine": ["creatinin"],
        "urea": ["uree", "urée"],
        "hemoglobin": ["hemoglob", "hémoglob"],
        "hematocrit": ["hematocrit", "hématocrit"],
        "leukocytes": ["leucocyt", "leukocyt"],
        "platelets": ["plaquette", "platelet"],
        "crp": ["crp", "c reactive"],
    }
    for canonical, keys in mapping.items():
        if any(k in n for k in keys):
            return canonical
    return "unknown"


def _map_category(raw_name: str) -> str:
    n = raw_name.lower()
    if any(k in n for k in ["hemoglob", "hémoglob", "leucocyt", "plaquette", "hematocrit"]):
        return "hematology"
    if any(k in n for k in ["tsh", "thyre", "vitamine d"]):
        return "hormonology"
    if any(k in n for k in ["crp", "anticorps", "hiv", "hbs", "serolog"]):
        return "serology"
    if any(k in n for k in ["glycem", "glucose", "creatinin", "uree", "cholesterol", "hdl", "ldl"]):
        return "biochemistry"
    return "other"


def _compute_status(value: Optional[float], rr: Optional[ReferenceRange]) -> str:
    if value is None or rr is None or rr.min is None or rr.max is None:
        return "unknown"
    if value < rr.min:
        return "low"
    if value > rr.max:
        return "high"
    return "normal"


def _rows_to_tests(rows: List[Dict[str, Optional[str]]]) -> List[LabTest]:
    tests: List[LabTest] = []
    for row in rows:
        raw_name = (row.get("parametre") or "unknown").strip()
        val = _to_float(row.get("valeur"))
        vraw = row.get("valeur")
        vtxt = None if val is not None else (str(vraw).strip() if vraw else None)
        rr = _parse_reference_range(row.get("valeurs_normales"))
        tests.append(
            LabTest(
                raw_test_name=raw_name,
                normalized_name=_normalize_name(raw_name),
                category=_map_category(raw_name),
                value_text=vtxt,
                value=val,
                unit=row.get("unite"),
                reference_range=rr,
                status=_compute_status(val, rr),
                raw_line=row.get("ligne_complete") or raw_name,
                confidence=0.7 if val is not None else 0.4,
            )
        )
    return tests


def _strip_accents(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value or "")
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def _parse_date_token(raw: str | None) -> Optional[str]:
    if not raw:
        return None
    text = normalize_digits(raw)
    match = re.search(r"(\d{1,2})\s*[./-]\s*(\d{1,2})\s*[./-]\s*(\d{2,4})", text)
    if not match:
        return None
    day, month, year = match.groups()
    year_i = int(year)
    if year_i < 100:
        year_i += 2000
    day_i = int(day)
    month_i = int(month)
    if not (1 <= day_i <= 31 and 1 <= month_i <= 12 and 1990 <= year_i <= 2100):
        return None
    return f"{year_i:04d}-{month_i:02d}-{day_i:02d}"


def _date_after_label(text: str, labels: tuple[str, ...]) -> Optional[str]:
    normalized = normalize_digits(text or "")
    for label in labels:
        pattern = rf"{label}\s*[:=]?\s*(\d{{1,2}}\s*[./-]\s*\d{{1,2}}\s*[./-]\s*\d{{2,4}})"
        match = re.search(pattern, normalized, flags=re.IGNORECASE)
        if match:
            parsed = _parse_date_token(match.group(1))
            if parsed:
                return parsed
    return None


def _extract_medical_metadata_from_text(text: str) -> dict[str, Optional[str]]:
    normalized = normalize_digits(text or "")
    compact = re.sub(r"\s+", " ", normalized)

    def find(pattern: str) -> Optional[str]:
        match = re.search(pattern, compact, flags=re.IGNORECASE)
        if not match:
            return None
        value = re.sub(r"\s+", " ", match.group(1)).strip(" .,:;|")
        return value[:80] or None

    return {
        "exam_number": find(r"(?:Examen|Exam|N[°o]\s*examen)\s*N[°o]?\s*[:=]?\s*([A-Z0-9][A-Z0-9/\- ]{3,40})"),
        "dossier_number": find(r"(?:Dossier|Dossier\s*N[°o]?|N[°o]\s*dossier)\s*[:=]?\s*([A-Z0-9][A-Z0-9/\- ]{3,40})"),
        "received_date": _date_after_label(normalized, (r"Re[cç]u\s*le", r"Date\s*re[cç]u", r"Reception")),
        "edited_date": _date_after_label(normalized, (r"Edit[eé]\s*le", r"Date\s*edit", r"Edition")),
        "request_date": _date_after_label(normalized, (r"Demand[eé]\s*le", r"Demande\s*le")),
    }


def _extract_requested_doctor(text: str) -> Optional[str]:
    normalized = normalize_digits(text or "")
    patterns = [
        r"Demand[eé]\s*(?:par)?\s*Dr\.?\s*[:?]?\s*([A-Z][A-Z\s.'-]{3,60})",
        r"Demand[eé]\s*par\s*[:?]?\s*Dr\.?\s*([A-Z][A-Z\s.'-]{3,60})",
        r"\bDr\.?\s+([A-Z][A-Z\s.'-]{3,60})\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, normalized, flags=re.IGNORECASE)
        if not match:
            continue
        value = re.sub(r"\s+", " ", match.group(1)).strip(" .,:;|)")
        if 3 <= len(value) <= 60:
            return value.title()
    return None


_FAST_MEDICAL_TESTS: list[tuple[str, tuple[str, ...]]] = [
    ("Glycemie a jeun", ("glycem", "glucose")),
    ("Cholesterol total", ("cholesterol total",)),
    ("Cholesterol HDL", ("cholesterol hdl", " hdl")),
    ("Cholesterol LDL", ("cholesterol ldl", " ldl")),
    ("Triglycerides", ("triglycer",)),
    ("Uree", ("uree", "orer", "oree")),
    ("Creatinine", ("creatinin",)),
    ("ASAT / GOT", ("asat", "sgot", "got")),
    ("ALAT / GPT", ("alat", "sgpt", "gpt")),
    ("Vitamine D", ("vitamine d", "hydroxy")),
    ("TSH", ("tsh", "thyreostimuline")),
    ("Hemoglobine", ("hemoglob",)),
    ("Globules rouges", ("globules rouges",)),
    ("Leucocytes", ("leucocytes", "globules blancs")),
    ("Plaquettes", ("plaquettes",)),
]


_MEDICAL_OCR_KEYWORDS = (
    "id patient",
    "dossier",
    "nom",
    "demand",
    "hemoglob",
    "hematocrit",
    "globules rouges",
    "leucocytes",
    "lymphocytes",
    "plaquettes",
    "vitamine",
    "tsh",
    "thyreo",
    "resultat",
)


def _medical_ocr_score(text: str) -> float:
    if not text or not text.strip():
        return 0.0
    searchable = _strip_accents(text).lower()
    keyword_score = sum(16.0 for key in _MEDICAL_OCR_KEYWORDS if key in searchable)
    digit_score = min(60.0, len(re.findall(r"\d", text)) * 0.45)
    char_score = min(30.0, len(text) / 70.0)
    return keyword_score + digit_score + char_score


def _resize_gray_for_ocr(image, *, max_width: int = 900):
    height, width = image.shape[:2]
    if width > max_width:
        scale = max_width / float(width)
        image = cv2.resize(
            image,
            (max_width, max(1, int(height * scale))),
            interpolation=cv2.INTER_AREA,
        )
    return cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)


def _best_medical_ocr_text(
    *,
    original_path: Path,
    preprocessed_path: Path,
    timeout_seconds: float,
) -> tuple[str, str, object | None, list[ProcessingWarning]]:
    warnings: list[ProcessingWarning] = []
    candidates: list[tuple[str, object]] = []
    seen_paths: set[str] = set()
    for label, path in (("original", original_path), ("preprocessed", preprocessed_path)):
        key = str(path.resolve()) if path.exists() else str(path)
        if key in seen_paths:
            continue
        seen_paths.add(key)
        image = cv2.imread(str(path))
        if image is None or image.size == 0:
            continue
        gray = _resize_gray_for_ocr(image, max_width=900)
        candidates.append((f"{label}:gray900", gray))
        try:
            clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
            candidates.append((f"{label}:clahe900", clahe.apply(gray)))
        except Exception:
            pass

    if not candidates:
        raise ValueError("image illisible")

    deadline = time.monotonic() + max(float(timeout_seconds) * 4.0, 24.0)
    best_text = ""
    best_label = ""
    best_gray = None
    best_score = -1.0
    attempts = 0
    for label, gray in candidates:
        for psm in (4, 11, 6):
            remaining = deadline - time.monotonic()
            if remaining <= 1.0:
                break
            attempts += 1
            try:
                text = pytesseract.image_to_string(
                    gray,
                    lang="fra+eng",
                    config=f"--oem 3 --psm {psm}",
                    timeout=max(2.0, min(12.0, remaining)),
                )
            except RuntimeError as exc:
                warnings.append(
                    ProcessingWarning(
                        code="MEDICAL_OCR_VARIANT_TIMEOUT",
                        message=f"Variante OCR ignoree ({label}, psm {psm}): {exc}",
                    )
                )
                continue
            score = _medical_ocr_score(text)
            if score > best_score:
                best_text = text or ""
                best_label = f"{label}:psm{psm}"
                best_gray = gray
                best_score = score
            if score >= 170.0:
                break
        if best_score >= 170.0:
            break

    if not best_text.strip():
        raise RuntimeError("Tesseract n'a retourne aucun texte medical exploitable")
    warnings.append(
        ProcessingWarning(
            code="MEDICAL_OCR_VARIANT_SELECTED",
            message=f"Variante OCR retenue: {best_label} (score {best_score:.1f}, {attempts} tentative(s)).",
        )
    )
    return normalize_digits(best_text or ""), best_label, best_gray, warnings


def _fallback_rows_from_medical_text(text: str) -> List[Dict[str, Optional[str]]]:
    lines = [re.sub(r"\s+", " ", normalize_digits(line)).strip() for line in (text or "").splitlines()]
    rows: list[dict[str, Optional[str]]] = []
    seen: set[str] = set()
    unit_pattern = (
        r"(g\s*/?\s*[l1]|mmol\s*/?\s*[l1t]|mg\s*/?\s*[l1]|mg\s*/?\s*d[l1]|"
        r"u?mol\s*/?\s*[l1]|µmol\s*/?\s*[l1]|ui\s*/?\s*[l1]|u[i1]?\s*/?\s*ml|"
        r"mui\s*/?\s*[l1]|ng\s*/?\s*ml|%)"
    )
    value_pattern = re.compile(
        rf"(\d{{1,4}}(?:[,.]\d{{1,3}})?)\s*({unit_pattern})",
        flags=re.IGNORECASE,
    )

    for index, line in enumerate(lines):
        if not line or len(line) < 4:
            continue
        searchable = _strip_accents(line).lower()
        joined = line
        if index + 1 < len(lines) and not re.search(r"\d", line):
            joined = f"{line} {lines[index + 1]}"
            searchable = _strip_accents(joined).lower()

        test_name = None
        for label, keys in _FAST_MEDICAL_TESTS:
            if any(key in searchable for key in keys):
                test_name = label
                break
        if not test_name or test_name in seen:
            continue

        match = value_pattern.search(joined)
        if not match:
            continue
        value = match.group(1).replace(",", ".")
        unit = re.sub(r"\s+", "", match.group(2)).replace("1", "l").replace("t", "l")
        ref_match = re.search(r"\(([^)]*\d[^)]*)\)", joined[match.end() :])
        rows.append(
            {
                "parametre": test_name,
                "valeur": value,
                "unite": unit,
                "valeurs_normales": ref_match.group(1).strip() if ref_match else None,
                "ligne_complete": joined[:220],
            }
        )
        seen.add(test_name)
    return rows


_KNOWN_MEDICAL_LINE_TESTS: list[tuple[str, tuple[str, ...], str]] = [
    ("Globules rouges", ("globules rouges",), "Millions/mm3"),
    ("Hemoglobine", ("hemoglob",), "g%"),
    ("Hematocrite", ("hematocrit",), "%"),
    ("VGM", ("vgm",), "fL"),
    ("TCMH", ("tcmh", "tom"), "pg"),
    ("CCMH", ("ccmh", "comme"), "%"),
    ("Leucocytes", ("leucocytes", "leucogytes"), "/mm3"),
    ("PN. Neutrophiles", ("neutrophiles",), "%"),
    ("PN. Eosinophiles", ("eosinophiles",), "%"),
    ("PN. Basophiles", ("basophiles", "basophile"), "%"),
    ("Lymphocytes", ("lymphocytes",), "%"),
    ("Monocytes", ("monocytes",), "%"),
    ("Plaquettes", ("plaquettes", "plaque"), "/mm3"),
    ("Vitamine D", ("vitamine d", "hydroxy", "vitamined"), "µg/l"),
    ("TSH", ("tsh", "thyreostimuline", "thyreo"), "uIU/mL"),
]


def _first_plausible_number(text: str) -> Optional[str]:
    normalized = normalize_digits(text)
    for raw in re.findall(r"\d{1,6}(?:[,.]\d{1,3})?", normalized):
        compact = raw.replace(" ", "")
        try:
            value = float(compact.replace(",", "."))
        except ValueError:
            continue
        if 0 <= value <= 500000:
            return compact
    return None


def _known_rows_from_medical_text(text: str) -> List[Dict[str, Optional[str]]]:
    lines = [re.sub(r"\s+", " ", normalize_digits(line)).strip() for line in (text or "").splitlines()]
    rows: list[dict[str, Optional[str]]] = []
    seen: set[str] = set()
    for index, line in enumerate(lines):
        if not line:
            continue
        searchable = _strip_accents(line).lower()
        window = line
        if index + 1 < len(lines):
            window = f"{line} {lines[index + 1]}"
        if index + 2 < len(lines):
            window = f"{window} {lines[index + 2]}"
        searchable_window = _strip_accents(window).lower()
        for label, keys, unit in _KNOWN_MEDICAL_LINE_TESTS:
            if label in seen:
                continue
            if not any(key in searchable or key in searchable_window for key in keys):
                continue
            value = _first_plausible_number(window)
            if not value:
                continue
            rows.append(
                {
                    "parametre": label,
                    "valeur": value,
                    "unite": unit,
                    "valeurs_normales": None,
                    "ligne_complete": window[:220],
                }
            )
            seen.add(label)
    return rows


def _merge_rows(primary: List[Dict[str, Optional[str]]], extra: List[Dict[str, Optional[str]]]) -> List[Dict[str, Optional[str]]]:
    merged: list[dict[str, Optional[str]]] = []
    seen: set[str] = set()
    for row in [*primary, *extra]:
        name = (row.get("parametre") or "").strip()
        key = _strip_accents(name).lower()
        if not key or key in seen:
            continue
        seen.add(key)
        merged.append(row)
    return merged


def _extract_patient_fields_from_text(text: str) -> dict[str, Optional[str]]:
    normalized = normalize_digits(text or "")
    flat = re.sub(r"\s+", " ", normalized)

    def find(pattern: str) -> Optional[str]:
        match = re.search(pattern, flat, flags=re.IGNORECASE)
        if not match:
            return None
        value = re.sub(r"\s+", " ", match.group(1)).strip(" .,:;|")
        return value[:100] or None

    patient_name = None
    for line in normalized.splitlines():
        if not re.search(r"\bNom\s*:", line, flags=re.IGNORECASE):
            continue
        after = re.split(r"\bNom\s*:", line, maxsplit=1, flags=re.IGNORECASE)[-1]
        after = re.sub(r"^\s*(?:Mme|Mlle|Mr|M|Madame|Monsieur)\.?\s+", "", after, flags=re.IGNORECASE)
        after = re.split(r"\b(?:N[^\s]{0,6}\s*le|CNAM|Demand[ée])\b", after, maxsplit=1, flags=re.IGNORECASE)[0]
        value = re.sub(r"[^A-Za-zÀ-ÿ\s'\-]", " ", after)
        value = re.sub(r"\s+", " ", value).strip(" .,:;|-")
        if len(value) >= 4:
            patient_name = value.title()
            break

    patient_name = patient_name or find(
        r"\bNom\s*:\s*(?:Mme|Mlle|Mr|M|Madame|Monsieur)?\.?\s*([A-Z][A-Z\s'\-]{4,80}?)(?=\s+N[ée]\(?e|\s+CNAM|\s+Demand|$)"
    )
    dossier = find(r"\bDossier\s*N[^\s:]{0,4}\s*:\s*([0-9][0-9/\-]{4,30})")
    return {
        "patient_id": find(r"\bID\s*patient\s*:\s*([A-Z0-9][A-Z0-9/\-]{2,30})"),
        "patient_name": patient_name.title() if patient_name else None,
        "dossier_number": dossier,
        "date_of_birth": _date_after_label(normalized, (r"N[ée]\(?e\)?\s*le", r"Date\s*de\s*naissance")),
        "doctor_name": _extract_requested_doctor(normalized),
    }


def _baseline_from_extracted(extracted, source_file: str) -> MedicalDocumentResult:
    return MedicalDocumentResult(
        document_type="medical_lab_report",
        lab_info=LabInfo(lab_name=extracted.laboratoire),
        patient_info=PatientInfo(patient_name=extracted.patient_nom),
        document_metadata=DocumentMetadata(
            dossier_number=extracted.reference_dossier,
            sample_date=extracted.date_prelevement,
            report_date=extracted.date_resultat,
            source_file=source_file,
        ),
        tests=_rows_to_tests(extracted.resultats_analyses),
        warnings=[],
        extraction_source="ocr",
    )


def process_medical_file_fast(
    file_path: Path,
    *,
    timeout_seconds: float = 8.0,
) -> MedicalDocumentResult:
    configure_tesseract()
    prep_dir: tempfile.TemporaryDirectory[str] | None = None
    ocr_path = file_path
    preprocessing_meta: dict[str, object] | None = None
    preprocessing_warning: ProcessingWarning | None = None
    try:
        prep_dir = tempfile.TemporaryDirectory()
        try:
            preprocessed = preprocess_document(file_path, Path(prep_dir.name))
            ocr_path = preprocessed.path
            preprocessing_meta = preprocessed.metadata
        except Exception as exc:
            preprocessing_warning = ProcessingWarning(
                code="DOCUMENT_PREPROCESSING_FAILED",
                message=f"Pretraitement image ignore: {type(exc).__name__}: {exc}",
                context=str(file_path),
            )

        text, selected_variant, original_gray, variant_warnings = _best_medical_ocr_text(
            original_path=file_path,
            preprocessed_path=ocr_path,
            timeout_seconds=timeout_seconds,
        )
    except Exception as exc:
        if prep_dir is not None:
            prep_dir.cleanup()
        return MedicalDocumentResult(
            document_metadata=DocumentMetadata(source_file=str(file_path)),
            warnings=[
                ProcessingWarning(
                    code="FAST_MEDICAL_OCR_FAILED",
                    message=f"OCR medical rapide indisponible: {type(exc).__name__}: {exc}",
                    context=str(file_path),
                )
            ],
            extraction_source="ocr_fast",
        )

    extracted = extract_fields_from_medical_text(text, file_path.name)
    result = _baseline_from_extracted(extracted, str(file_path))
    metadata = _extract_medical_metadata_from_text(text)
    patient_fields = _extract_patient_fields_from_text(text)
    if patient_fields.get("patient_id"):
        result.patient_info.patient_id = patient_fields["patient_id"]
    if patient_fields.get("patient_name"):
        result.patient_info.patient_name = patient_fields["patient_name"]
    if patient_fields.get("date_of_birth"):
        result.patient_info.date_of_birth = patient_fields["date_of_birth"]
    if metadata.get("exam_number"):
        result.document_metadata.exam_number = metadata["exam_number"]
    if metadata.get("dossier_number"):
        result.document_metadata.dossier_number = metadata["dossier_number"]
    if patient_fields.get("dossier_number"):
        result.document_metadata.dossier_number = patient_fields["dossier_number"]
    if metadata.get("received_date"):
        result.document_metadata.received_date = metadata["received_date"]
        if not result.document_metadata.sample_date:
            result.document_metadata.sample_date = metadata["received_date"]
    if metadata.get("edited_date"):
        result.document_metadata.edited_date = metadata["edited_date"]
        if not result.document_metadata.report_date:
            result.document_metadata.report_date = metadata["edited_date"]
    if metadata.get("request_date"):
        result.document_metadata.request_date = metadata["request_date"]
    doctor_name = patient_fields.get("doctor_name") or _extract_requested_doctor(text)
    if doctor_name:
        result.lab_info.doctor_name = doctor_name
    text_rows = _merge_rows(
        _fallback_rows_from_medical_text(text),
        _known_rows_from_medical_text(text),
    )
    image_rows: list[dict[str, Optional[str]]] = []
    if original_gray is not None:
        image_rows = extract_result_rows_from_medical_ocr_data(original_gray)
    text_tests = _rows_to_tests(text_rows)
    if not result.tests or len(result.tests) < 4:
        result.tests = _rows_to_tests(_merge_rows(text_rows, image_rows))
    elif text_tests:
        seen_tests = {
            _strip_accents(test.raw_test_name).lower()
            for test in result.tests
            if test.raw_test_name
        }
        for test in text_tests:
            key = _strip_accents(test.raw_test_name).lower()
            if key and key not in seen_tests:
                result.tests.append(test)
                seen_tests.add(key)
    result.raw_text = text[:80_000]
    result.extraction_source = "ocr_fast"
    result.warnings.extend(variant_warnings)
    if preprocessing_meta:
        result.warnings.append(
            ProcessingWarning(
                code="DOCUMENT_PREPROCESSING_APPLIED",
                message="Image redressee et amelioree avant OCR medical rapide.",
                context=str(preprocessing_meta),
            )
        )
    if preprocessing_warning:
        result.warnings.append(preprocessing_warning)
    result.warnings.append(
        ProcessingWarning(
            code="FAST_MEDICAL_OCR",
            message=f"Extraction rapide utilisee pour eviter le blocage du pipeline local sur image medicale ({selected_variant}).",
            context=str(file_path),
        )
    )
    if prep_dir is not None:
        prep_dir.cleanup()
    return result


def _merge_gemini_with_baseline(
    gem: MedicalDocumentResult, base: MedicalDocumentResult, ocr_text: str
) -> MedicalDocumentResult:
    if not gem.lab_info.lab_name and base.lab_info.lab_name:
        gem.lab_info.lab_name = base.lab_info.lab_name
    if not gem.patient_info.patient_name and base.patient_info.patient_name:
        gem.patient_info.patient_name = base.patient_info.patient_name
    if not gem.document_metadata.dossier_number and base.document_metadata.dossier_number:
        gem.document_metadata.dossier_number = base.document_metadata.dossier_number
    if not gem.document_metadata.sample_date and base.document_metadata.sample_date:
        gem.document_metadata.sample_date = base.document_metadata.sample_date
    if not gem.document_metadata.report_date and base.document_metadata.report_date:
        gem.document_metadata.report_date = base.document_metadata.report_date
    gem.raw_text = ocr_text[:80_000] if ocr_text else gem.raw_text
    gem.warnings.extend([w for w in base.warnings if w not in gem.warnings])
    return gem


def process_medical_file(
    file_path: Path,
    *,
    use_gemini: bool = False,
    gemini_api_key: Optional[str] = None,
    gemini_model: Optional[str] = None,
) -> MedicalDocumentResult:
    warnings: List[ProcessingWarning] = []
    suffix = file_path.suffix.lower()
    api_key = gemini_api_key or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    model = gemini_model or os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

    def _try_gemini(ocr_text: str, image_for_model: Optional[Path]) -> tuple[Optional[MedicalDocumentResult], List[ProcessingWarning]]:
        if not use_gemini or not api_key:
            return None, []
        try:
            gem = analyze_medical_document_gemini(
                api_key=api_key,
                model_name=model,
                ocr_text=ocr_text,
                image_path=image_for_model,
                source_file=str(file_path),
            )
            return gem, []
        except Exception as exc:
            return None, [
                ProcessingWarning(code="GEMINI_FAILED", message=str(exc), context=str(file_path))
            ]

    if suffix in {".jpg", ".jpeg", ".png", ".tif", ".tiff"}:
        ocr_text = extract_combined_ocr_text(file_path) if use_gemini and api_key else ""
        extracted = extract_fields_from_medical(file_path)
        baseline = _baseline_from_extracted(extracted, str(file_path))
        baseline.raw_text = ocr_text[:80_000] if ocr_text else None

        gem, gem_err = _try_gemini(ocr_text, file_path)
        baseline.warnings.extend(warnings)
        baseline.warnings.extend(gem_err)
        if gem and len(gem.tests) > 0:
            return _merge_gemini_with_baseline(gem, baseline, ocr_text)
        if gem and len(gem.tests) == 0 and len(baseline.tests) > 0:
            baseline.warnings.append(
                ProcessingWarning(
                    code="GEMINI_EMPTY_TESTS",
                    message="Gemini n'a retourne aucun test ; affichage OCR.",
                )
            )
            return baseline
        if gem:
            return _merge_gemini_with_baseline(gem, baseline, ocr_text)
        return baseline

    if suffix == ".pdf":
        raw_text, pdf_text_warnings = _extract_pdf_text(file_path)
        warnings.extend(pdf_text_warnings)

        fd, tmp_png = tempfile.mkstemp(suffix=".png")
        os.close(fd)
        png_path = Path(tmp_png)
        try:
            render_warnings = _render_pdf_first_page(file_path, png_path)
            if render_warnings:
                if raw_text:
                    extracted = extract_fields_from_medical_text(raw_text, file_path.name)
                    baseline = _baseline_from_extracted(extracted, str(file_path))
                    baseline.raw_text = raw_text[:80_000]
                    baseline.warnings.extend(warnings)
                    baseline.warnings.extend(render_warnings)
                    gem, gem_err = _try_gemini(raw_text, None)
                    baseline.warnings.extend(gem_err)
                    if gem and len(gem.tests) > 0:
                        return _merge_gemini_with_baseline(gem, baseline, raw_text)
                    if gem:
                        return _merge_gemini_with_baseline(gem, baseline, raw_text)
                    return baseline
                return MedicalDocumentResult(
                    document_metadata=DocumentMetadata(source_file=str(file_path)),
                    raw_text=raw_text or None,
                    warnings=warnings + render_warnings,
                    extraction_source="ocr",
                )

            ocr_text = extract_combined_ocr_text(png_path)
            if raw_text:
                ocr_text = f"--- TEXTE PDF (copie) ---\n{raw_text[:40_000]}\n\n{ocr_text}"

            extracted = extract_fields_from_medical(png_path)
            baseline = _baseline_from_extracted(extracted, str(file_path))
            baseline.raw_text = ocr_text[:80_000]

            gem, gem_err = _try_gemini(ocr_text, png_path)
            baseline.warnings.extend(warnings)
            baseline.warnings.extend(gem_err)
            if gem and len(gem.tests) > 0:
                return _merge_gemini_with_baseline(gem, baseline, ocr_text)
            if gem and len(gem.tests) == 0 and len(baseline.tests) > 0:
                baseline.warnings.append(
                    ProcessingWarning(
                        code="GEMINI_EMPTY_TESTS",
                        message="Gemini n'a retourne aucun test ; affichage OCR.",
                    )
                )
                return baseline
            if gem:
                return _merge_gemini_with_baseline(gem, baseline, ocr_text)
            return baseline
        finally:
            png_path.unlink(missing_ok=True)

    return MedicalDocumentResult(
        document_metadata=DocumentMetadata(source_file=str(file_path)),
        warnings=[ProcessingWarning(code="UNSUPPORTED_FILE_TYPE", message=f"Type non supporte: {suffix}")],
        extraction_source="ocr",
    )
