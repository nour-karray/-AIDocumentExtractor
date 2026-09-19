from __future__ import annotations

import base64
import importlib.util
import json
import multiprocessing
import os
import re
import shutil
import sys
import tempfile
import urllib.error
import urllib.request
from datetime import date, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pipelines.extract_medical_report_gemini import extract_medical_report
from pipelines.extract_receipt_gemini import extract_receipt
from pipelines.extract_supplier_invoice_gemini import extract_supplier_invoice
from src.config import AppConfig, load_config
from src.extraction.steg_invoice_extractor import (
    configure_tesseract,
    derive_reference_from_footer_compact,
)
from src.services.document_preprocessing import preprocess_document
from src.services.document_router import detect_document_type, process_any_document
from src.services.extraction_history import (
    delete_history_entry,
    list_history_entries,
    save_extraction,
)
from src.services.extraction_report_pdf import build_extraction_report_pdf
from src.services.local_docling_qwen import (
    LocalPipelineError,
    _content_for_extraction,
    extract_with_docling_qwen,
)
from src.services.medical_pipeline import process_medical_file_fast

MODE_OPTIONS = [
    {"value": "auto", "label": "Auto (detection)"},
    {"value": "medical", "label": "Analyse medicale"},
    {"value": "steg", "label": "Facture STEG"},
    {"value": "supplier", "label": "Facture fournisseur (generique)"},
    {"value": "receipt", "label": "Ticket de caisse"},
]

METHOD_OPTIONS = [
    {"value": "local", "label": "Pipeline IA local (Docling + PaddleOCR + Qwen2.5)"},
    {"value": "ocr", "label": "OCR local classique"},
    {"value": "gemini", "label": "Gemini API"},
]

DEFAULT_EXTRACTION_TIMEOUT_SECONDS = 120.0
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".tif", ".tiff"}
_STEG_HEADER_FIELD_CACHE: dict[str, dict[str, str]] = {}

THEME_OPTIONS = [
    {"value": "dark", "label": "Noir"},
    {"value": "light", "label": "Blanc"},
]

KIND_LABELS_FR = {
    "steg_ocr": "Facture STEG (OCR local)",
    "steg_gemini": "Facture STEG (Gemini)",
    "steg_local": "Facture STEG (Docling + Qwen local)",
    "medical_ocr": "Analyse medicale (OCR structure)",
    "medical_gemini": "Analyse medicale (Gemini)",
    "medical_local": "Analyse medicale (Docling + Qwen local)",
    "receipt": "Ticket de caisse",
    "receipt_test": "Ticket de caisse (import historique)",
    "receipt_local": "Ticket de caisse (Docling + Qwen local)",
    "supplier_invoice": "Facture fournisseur",
    "supplier_invoice_local": "Facture fournisseur (Docling + Qwen local)",
    "document_local": "Document (Docling + Qwen local)",
    "extraction_error": "Traitement a verifier",
}


def get_config() -> AppConfig:
    return load_config(ROOT)


def kind_label(kind: str) -> str:
    return KIND_LABELS_FR.get(kind, kind)


def method_label(kind: str) -> str:
    if kind == "extraction_error":
        return "Extraction"
    if kind.endswith("_local") or kind == "document_local":
        return "Pipeline IA local"
    if kind == "receipt_test":
        return "Dataset test annote"
    if kind.endswith("_gemini") or kind in {"receipt", "supplier_invoice"}:
        return "Gemini API"
    if kind.endswith("_ocr"):
        return "OCR local"
    return "Mixte"


def method_label_from_value(value: str | None) -> str:
    if value == "local":
        return "Pipeline IA local"
    if value == "ocr":
        return "OCR local classique"
    if value == "gemini":
        return "Gemini API"
    return "Extraction"


def result_method_label(kind: str, payload: dict[str, Any] | None = None) -> str:
    if kind == "extraction_error" and isinstance(payload, dict):
        return method_label_from_value(str(payload.get("method") or ""))
    return method_label(kind)


def family_label(kind: str) -> str:
    if kind == "extraction_error":
        return "Erreur"
    if kind.startswith("steg_"):
        return "Facture STEG"
    if kind.startswith("medical_"):
        return "Analyse medicale"
    if kind in {"receipt", "receipt_local", "receipt_test"}:
        return "Ticket de caisse"
    if kind in {"supplier_invoice", "supplier_invoice_local"}:
        return "Facture fournisseur"
    return "Autre"


def status_from_payload(payload: dict[str, Any]) -> str:
    return "error" if isinstance(payload, dict) and payload.get("error") else "ok"


def warnings_count(payload: dict[str, Any]) -> int:
    warnings = payload.get("warnings")
    if isinstance(warnings, list):
        return len(warnings)
    return 0


EMPTY_SCORE_STRINGS = {"", "n/a", "na", "none", "null", "non detecte", "non détecté", "inconnu", "inconnue"}
TECHNICAL_SCORE_KEYS = {
    "_meta",
    "raw_text",
    "warnings",
    "extraction_quality",
    "extraction_source",
    "source_file",
    "file_name",
    "document_type",
    "confidence_note",
    "local_pipeline",
}


def _is_meaningful_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, bool):
        return True
    if isinstance(value, (int, float)):
        return True
    if isinstance(value, str):
        return value.strip().casefold() not in EMPTY_SCORE_STRINGS
    if isinstance(value, list):
        return any(_is_meaningful_value(item) for item in value)
    if isinstance(value, dict):
        return any(
            _is_meaningful_value(item)
            for key, item in value.items()
            if str(key) not in TECHNICAL_SCORE_KEYS
        )
    return True


def _nested_value(payload: dict[str, Any], path: str) -> Any:
    current: Any = payload
    for part in path.split("."):
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


def _has_any(payload: dict[str, Any], *paths: str) -> bool:
    return any(_is_meaningful_value(_nested_value(payload, path)) for path in paths)


def _weighted_fields_score(payload: dict[str, Any], fields: list[tuple[float, tuple[str, ...]]]) -> float:
    return sum(weight for weight, paths in fields if _has_any(payload, *paths))


def _rows_score(rows: Any, *, weight: float, max_rows: int, name_keys: tuple[str, ...], value_keys: tuple[str, ...]) -> float:
    if not isinstance(rows, list) or not rows:
        return 0.0
    row_units = 0.0
    for row in rows[:max_rows]:
        if not isinstance(row, dict):
            continue
        has_name = any(_is_meaningful_value(row.get(key)) for key in name_keys)
        has_value = any(_is_meaningful_value(row.get(key)) for key in value_keys)
        if has_name and has_value:
            row_units += 1.0
        elif has_name or has_value:
            row_units += 0.45
    return min(1.0, row_units / max(max_rows, 1)) * weight


def _receipt_completion_score(payload: dict[str, Any]) -> float:
    score = _weighted_fields_score(
        payload,
        [
            (24.0, ("store_name",)),
            (18.0, ("date",)),
            (24.0, ("total",)),
            (16.0, ("address",)),
        ],
    )
    ticket_number = payload.get("ticket_number")
    if not _is_meaningful_value(ticket_number):
        ticket_number = _ticket_number_from_text(str(payload.get("raw_text") or ""))
    if _is_meaningful_value(ticket_number):
        score += 18.0
    return score


def _generic_completion_score(payload: dict[str, Any]) -> float | None:
    total = 0
    filled = 0

    def visit(value: Any, parent_key: str = "") -> None:
        nonlocal total, filled
        if parent_key in TECHNICAL_SCORE_KEYS:
            return
        if isinstance(value, dict):
            for key, item in value.items():
                visit(item, str(key))
            return
        if isinstance(value, list):
            if not value:
                total += 1
                return
            for item in value:
                visit(item, parent_key)
            return
        total += 1
        if _is_meaningful_value(value):
            filled += 1

    visit(payload)
    if total == 0:
        return None
    return (filled / total) * 100.0


def _completion_score(payload: dict[str, Any], kind: str) -> float | None:
    if status_from_payload(payload) == "error":
        return 0.0

    score: float | None = None
    if kind in {"medical_ocr", "medical_local"}:
        score = _weighted_fields_score(
            payload,
            [
                (8.0, ("lab_info.lab_name",)),
                (7.0, ("lab_info.doctor_name",)),
                (15.0, ("patient_info.patient_name",)),
                (8.0, ("patient_info.patient_id",)),
                (10.0, ("document_metadata.exam_number", "document_metadata.dossier_number")),
                (12.0, ("document_metadata.sample_date", "document_metadata.report_date")),
            ],
        )
        score += _rows_score(
            payload.get("tests"),
            weight=40.0,
            max_rows=6,
            name_keys=("raw_test_name", "normalized_name"),
            value_keys=("value", "value_text", "secondary_value"),
        )
    elif kind == "medical_gemini":
        score = _weighted_fields_score(
            payload,
            [
                (20.0, ("patient_name",)),
                (15.0, ("doctor_name",)),
                (15.0, ("date",)),
            ],
        )
        score += _rows_score(
            payload.get("analyses"),
            weight=50.0,
            max_rows=6,
            name_keys=("test_name",),
            value_keys=("value", "unit"),
        )
    elif kind in {"steg_ocr", "steg_gemini", "steg_local"}:
        score = _weighted_fields_score(
            payload,
            [
                (25.0, ("reference",)),
                (25.0, ("montant_a_payer",)),
                (15.0, ("date_limite_paiement",)),
                (7.5, ("periode_du",)),
                (7.5, ("periode_au",)),
                (10.0, ("coupon_reference_raw",)),
                (10.0, ("coupon_montant",)),
            ],
        )
        confidence = str(payload.get("confidence_note") or "").strip().casefold()
        if confidence == "medium":
            score = min(score, 80.0)
        elif confidence == "low":
            score = min(score, 55.0)
    elif kind in {"receipt", "receipt_local", "receipt_test"}:
        score = _receipt_completion_score(payload)
    elif kind in {"supplier_invoice", "supplier_invoice_local"}:
        score = _weighted_fields_score(
            payload,
            [
                (8.0, ("invoice_number",)),
                (7.0, ("invoice_date",)),
                (5.0, ("due_date",)),
                (10.0, ("seller.name", "seller.tax_id")),
                (10.0, ("client.name", "client.tax_id")),
                (20.0, ("summary.total_amount", "summary.amount_due")),
                (5.0, ("currency",)),
            ],
        )
        score += _rows_score(
            payload.get("items"),
            weight=35.0,
            max_rows=5,
            name_keys=("description",),
            value_keys=("net_amount", "gross_amount", "unit_price", "quantity"),
        )
    else:
        score = _generic_completion_score(payload)

    if score is None:
        return None
    score = max(0.0, min(100.0, score - min(warnings_count(payload) * 8.0, 32.0)))
    return score


def quality_score(payload: dict[str, Any], kind: str = "") -> float | None:
    if status_from_payload(payload) == "error":
        return 0.0
    if kind.endswith("_test"):
        return None
    score = _completion_score(payload, kind)
    if score is None:
        raw = payload.get("extraction_quality")
        if isinstance(raw, (int, float)) and not isinstance(raw, bool):
            value = float(raw)
            if 0.0 <= value <= 1.0:
                score = value * 100.0
            elif 0.0 <= value <= 100.0:
                score = value
    return round(score, 1) if score is not None else None


def normalize_text(raw: str) -> str:
    return " ".join((raw or "").strip().casefold().split())


def entry_saved_date(entry: dict[str, Any]) -> date | None:
    raw = str(entry.get("saved_at") or "").strip()
    if raw:
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00")).date()
        except ValueError:
            pass
    rel = str(entry.get("relative") or "")
    name = Path(rel).name
    if len(name) >= 8 and name[:8].isdigit():
        try:
            return datetime.strptime(name[:8], "%Y%m%d").date()
        except ValueError:
            return None
    return None


def encode_entry_key(relative: str) -> str:
    raw = relative.encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_entry_key(key: str) -> str:
    padding = "=" * (-len(key) % 4)
    return base64.urlsafe_b64decode((key + padding).encode("ascii")).decode("utf-8")


def summarize_payload(kind: str, payload: dict[str, Any]) -> dict[str, str]:
    if isinstance(payload, dict) and payload.get("error"):
        return {
            "headline": "Traitement a verifier",
            "subline": str(payload.get("error") or "Details indisponibles"),
        }
    if kind == "medical_gemini":
        return {
            "headline": str(payload.get("patient_name") or "Patient a verifier"),
            "subline": str(payload.get("date") or "Date a verifier"),
        }
    if kind in {"medical_ocr", "medical_local"}:
        patient = payload.get("patient_info") if isinstance(payload.get("patient_info"), dict) else {}
        meta = payload.get("document_metadata") if isinstance(payload.get("document_metadata"), dict) else {}
        return {
            "headline": str(patient.get("patient_name") or "Patient a verifier"),
            "subline": str(meta.get("report_date") or meta.get("sample_date") or "Date a verifier"),
        }
    if kind in {"steg_ocr", "steg_gemini", "steg_local"}:
        return {
            "headline": str(payload.get("reference") or "Reference a verifier"),
            "subline": str(payload.get("montant_a_payer") or "Montant a verifier"),
        }
    if kind in {"supplier_invoice", "supplier_invoice_local"}:
        seller = payload.get("seller") if isinstance(payload.get("seller"), dict) else {}
        return {
            "headline": str(payload.get("invoice_number") or "Numero a verifier"),
            "subline": str(seller.get("name") or "Fournisseur a verifier"),
        }
    if kind in {"receipt", "receipt_local", "receipt_test"}:
        return {
            "headline": str(payload.get("store_name") or "Magasin a verifier"),
            "subline": str(payload.get("total") or "Total a verifier"),
        }
    return {"headline": kind_label(kind), "subline": ""}


def history_summary(entry: dict[str, Any], cfg: AppConfig) -> dict[str, Any]:
    payload = entry.get("payload") if isinstance(entry.get("payload"), dict) else {}
    relative = str(entry.get("relative") or "")
    kind = str(entry.get("kind") or "")
    payload = _normalize_document_payload_fields(kind, payload)
    saved_at = str(entry.get("saved_at") or "")
    source_filename = str(entry.get("source_filename") or "")
    summary = summarize_payload(kind, payload)
    return {
        "entryKey": encode_entry_key(relative),
        "relative": relative,
        "kind": kind,
        "kindLabel": kind_label(kind),
        "family": family_label(kind),
        "method": result_method_label(kind, payload),
        "savedAt": saved_at,
        "savedDate": entry_saved_date(entry).isoformat() if entry_saved_date(entry) else None,
        "sourceFilename": source_filename,
        "status": str(entry.get("status") or status_from_payload(payload)),
        "warningsCount": warnings_count(payload),
        "qualityScore": quality_score(payload, kind),
        "sizeBytes": int(entry.get("size_bytes") or 0),
        "summary": summary,
        "reportUrl": f"/api/history/{encode_entry_key(relative)}/report.pdf",
        "detailUrl": f"/api/history/{encode_entry_key(relative)}",
        "sourceUrl": f"/api/history/{encode_entry_key(relative)}/source",
        "hasSourceArchive": resolve_archived_source_path(entry, cfg, payload) is not None
        or bool(entry.get("has_source_blob")),
    }


def entry_matches_search(entry: dict[str, Any], search: str) -> bool:
    if not search:
        return True
    source = normalize_text(str(entry.get("source_filename") or ""))
    return search in source


def _entry_type_query_value(entry: dict[str, Any], selected_kind: str) -> str:
    kind = selected_kind or str(entry.get("kind") or "")
    payload = entry.get("payload") if isinstance(entry.get("payload"), dict) else {}
    detected_kind = str(entry.get("detected_kind") or payload.get("document_type") or "")
    labels = [
        kind,
        kind_label(kind),
        family_label(kind),
        detected_kind,
    ]
    return normalize_text(" ".join(label for label in labels if label))


def _history_entry_is_displayable(entry: dict[str, Any]) -> bool:
    payload = entry.get("payload") if isinstance(entry.get("payload"), dict) else {}
    kind = str(entry.get("kind") or "")
    score = quality_score(payload, kind)
    return score is None or score > 0


def filter_history_entries(
    entries: list[dict[str, Any]],
    *,
    kind: str = "",
    search: str = "",
    type_query: str = "",
    date_from: date | None = None,
    date_to: date | None = None,
) -> list[dict[str, Any]]:
    filtered = [entry for entry in entries if _history_entry_is_displayable(entry)]
    if kind:
        filtered = [entry for entry in filtered if entry.get("kind") == kind]
    search_norm = normalize_text(search)
    if search_norm:
        filtered = [entry for entry in filtered if entry_matches_search(entry, search_norm)]
    type_norm = normalize_text(type_query)
    if type_norm:
        filtered = [
            entry
            for entry in filtered
            if type_norm in _entry_type_query_value(entry, kind or str(entry.get("kind") or ""))
        ]
    if date_from or date_to:
        lo = date_from or date.min
        hi = date_to or date.max
        filtered = [
            entry
            for entry in filtered
            if (ed := entry_saved_date(entry)) is not None and lo <= ed <= hi
        ]
    return filtered


def find_history_entry(cfg: AppConfig, entry_key: str) -> dict[str, Any] | None:
    try:
        relative = decode_entry_key(entry_key)
    except Exception:
        return None
    for entry in list_history_entries(cfg):
        if str(entry.get("relative") or "") == relative:
            return entry
    return None


def load_history_payload(entry: dict[str, Any]) -> dict[str, Any]:
    payload = entry.get("payload")
    if isinstance(payload, dict) and payload:
        return dict(payload)
    path = entry.get("path")
    if isinstance(path, Path) and path.is_file():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def resolve_archived_source_path(
    entry: dict[str, Any],
    cfg: AppConfig,
    payload: dict[str, Any] | None = None,
) -> Path | None:
    payload = payload or load_history_payload(entry)
    meta = payload.get("_meta") if isinstance(payload.get("_meta"), dict) else {}
    source_relative = meta.get("source_file_relative")
    if source_relative:
        candidate = cfg.extraction_history_dir / Path(str(source_relative))
        if candidate.is_file():
            return candidate

    relative = str(entry.get("relative") or "")
    if not relative or relative.startswith("db://"):
        return None
    json_path = cfg.extraction_history_dir / Path(relative)
    if not json_path.is_file():
        return None
    stem = json_path.stem
    for ext in (".jpg", ".jpeg", ".png", ".tif", ".tiff", ".webp", ".bmp", ".pdf"):
        candidate = json_path.with_name(f"{stem}{ext}")
        if candidate.is_file():
            return candidate
    return None


def build_history_detail(cfg: AppConfig, entry: dict[str, Any]) -> dict[str, Any]:
    payload = load_history_payload(entry)
    kind = str(entry.get("kind") or (payload.get("_meta") or {}).get("kind") or "")
    payload = _normalize_document_payload_fields_from_source(cfg, entry, kind, payload)
    summary = history_summary(entry, cfg)
    summary["payload"] = payload
    summary["sourceAvailable"] = resolve_archived_source_path(entry, cfg, payload) is not None
    return summary


def build_report_for_entry(cfg: AppConfig, entry: dict[str, Any]) -> bytes:
    payload = load_history_payload(entry)
    kind = str(entry.get("kind") or (payload.get("_meta") or {}).get("kind") or "")
    payload = _normalize_document_payload_fields_from_source(cfg, entry, kind, payload)
    return build_extraction_report_pdf(payload, kind)


def delete_entry_by_key(cfg: AppConfig, entry_key: str) -> tuple[bool, str]:
    entry = find_history_entry(cfg, entry_key)
    if entry is None:
        return False, "Entree introuvable."
    return delete_history_entry(cfg, entry)


def _safe_error(message: str) -> str:
    return " ".join(message.strip().split())


def _try_process_document(
    tmp_path: Path,
    mode: str,
    *,
    use_gemini: bool = False,
    gemini_api_key: str | None = None,
    gemini_model: str | None = None,
) -> tuple[dict[str, Any] | None, str | None]:
    try:
        routed = process_any_document(
            tmp_path,
            mode=mode,
            use_gemini=use_gemini,
            gemini_api_key=gemini_api_key,
            gemini_model=gemini_model,
        )
        return routed, None
    except Exception as exc:
        return None, f"{type(exc).__name__}: {exc}"


def _successful_result(
    *,
    kind: str,
    payload: dict[str, Any],
    history_relative: str | None,
    detected_kind: str,
    source_origin: str,
    filename: str,
) -> dict[str, Any]:
    entry_key = encode_entry_key(history_relative) if history_relative else None
    return {
        "filename": filename,
        "sourceOrigin": source_origin,
        "detectedType": detected_kind,
        "status": "ok",
        "kind": kind,
        "kindLabel": kind_label(kind),
        "method": result_method_label(kind, payload),
        "payload": payload,
        "warnings": payload.get("warnings") if isinstance(payload.get("warnings"), list) else [],
        "summary": summarize_payload(kind, payload),
        "historyEntryKey": entry_key,
        "reportUrl": f"/api/history/{entry_key}/report.pdf" if entry_key else None,
        "sourceUrl": f"/api/history/{entry_key}/source" if entry_key else None,
        "detailUrl": f"/api/history/{entry_key}" if entry_key else None,
    }


def _error_result(
    *,
    filename: str,
    source_origin: str,
    detected_kind: str,
    error: str,
    kind: str | None = "extraction_error",
    payload: dict[str, Any] | None = None,
    history_relative: str | None = None,
) -> dict[str, Any]:
    entry_key = encode_entry_key(history_relative) if history_relative else None
    return {
        "filename": filename,
        "sourceOrigin": source_origin,
        "detectedType": detected_kind,
        "status": "error",
        "kind": kind,
        "kindLabel": kind_label(kind or ""),
        "method": result_method_label(kind or "", payload),
        "payload": payload,
        "warnings": payload.get("warnings") if isinstance(payload, dict) and isinstance(payload.get("warnings"), list) else [],
        "summary": {"headline": "Traitement a verifier", "subline": _safe_error(error)},
        "error": _safe_error(error),
        "historyEntryKey": entry_key,
        "reportUrl": f"/api/history/{entry_key}/report.pdf" if entry_key else None,
        "sourceUrl": f"/api/history/{entry_key}/source" if entry_key else None,
        "detailUrl": f"/api/history/{entry_key}" if entry_key else None,
    }


def _persisted_error_result(
    cfg: AppConfig,
    *,
    filename: str,
    file_bytes: bytes,
    source_origin: str,
    detected_kind: str,
    error: str,
    mode: str,
    extraction_method: str,
) -> dict[str, Any]:
    safe_error = _safe_error(error)
    kind = "extraction_error"
    payload: dict[str, Any] = {
        "document_type": detected_kind or "unknown",
        "error": safe_error,
        "mode": mode,
        "method": extraction_method,
        "warnings": [{"code": "EXTRACTION_FAILED", "message": safe_error}],
        "extraction_source": extraction_method,
    }
    history_relative: str | None = None
    try:
        history_path = save_extraction(
            cfg,
            kind,
            filename,
            payload,
            source_bytes=file_bytes,
            status="error",
            error_message=safe_error,
            detected_kind=detected_kind,
        )
        history_relative = str(history_path.relative_to(cfg.extraction_history_dir))
    except Exception as exc:
        payload["warnings"].append(
            {"code": "DATABASE_SAVE_FAILED", "message": f"{type(exc).__name__}: {exc}"}
        )
    return _error_result(
        filename=filename,
        source_origin=source_origin,
        detected_kind=detected_kind,
        error=safe_error,
        kind=kind,
        payload=payload,
        history_relative=history_relative,
    )


def _fast_medical_ocr_result(
    cfg: AppConfig,
    *,
    filename: str,
    file_bytes: bytes,
    tmp_path: Path,
    source_origin: str,
    extra_warning: str | None = None,
    kind: str = "medical_ocr",
    extraction_source: str = "ocr_fast",
) -> dict[str, Any]:
    detected_kind = "medical_lab_report"
    result = process_medical_file_fast(tmp_path)
    payload = result.model_dump(exclude_none=True)
    payload["extraction_source"] = extraction_source
    if kind == "medical_local":
        payload["local_pipeline"] = {
            "architecture": "Pretraitement -> OCR medical rapide -> JSON structure",
            "content_source": "medical_fast_ocr",
            "qwen_used": False,
            "reason": "Retour rapide pour les images medicales afin d'eviter une attente longue devant l'utilisateur.",
        }
    warnings = payload.get("warnings")
    if not isinstance(warnings, list):
        warnings = []
    if extra_warning:
        warnings.append({"code": "AUTO_FAST_OCR_FALLBACK", "message": extra_warning})
    payload["warnings"] = warnings

    history_relative: str | None = None
    try:
        history_path = save_extraction(
            cfg,
            kind,
            filename,
            payload,
            source_bytes=file_bytes,
            status="ok",
            detected_kind=detected_kind,
        )
        history_relative = str(history_path.relative_to(cfg.extraction_history_dir))
    except Exception:
        history_relative = None

    return _successful_result(
        kind=kind,
        payload=payload,
        history_relative=history_relative,
        detected_kind=detected_kind,
        source_origin=source_origin,
        filename=filename,
    )


def _amount_candidates_from_text(text: str) -> list[str]:
    candidates = re.findall(r"\b\d{1,4}\s*[,.]\s*\d{3}\b", text or "")
    return [re.sub(r"\s+", "", item) for item in candidates]


def _amount_to_float(raw: str) -> float:
    text = raw.replace(" ", "").replace(".", "").replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return -1.0


def _best_steg_amount(text: str) -> str | None:
    normalized = normalize_text(text)
    keyword_match = re.search(
        r"(?:montant\s*(?:a|&|à)?\s*payer|payer)[^\d]{0,80}(\d{1,4}\s*[,.]\s*\d{3})",
        normalized,
        flags=re.IGNORECASE,
    )
    if keyword_match:
        return re.sub(r"\s+", "", keyword_match.group(1))
    before_keyword_match = re.search(
        r"(\d{1,4}\s*,\s*\d{3})[^\n\r]{0,80}(?:montant\s*(?:a|&|à)?\s*payer|payer)",
        normalized,
        flags=re.IGNORECASE,
    )
    if before_keyword_match:
        return re.sub(r"\s+", "", before_keyword_match.group(1))
    candidates = _amount_candidates_from_text(text)
    if not candidates:
        return None
    comma_candidates = [item for item in candidates if "," in item]
    if comma_candidates:
        candidates = comma_candidates
    plausible = [item for item in candidates if _amount_to_float(item) >= 10]
    return max(plausible or candidates, key=_amount_to_float)


def _steg_reference_from_text(text: str) -> tuple[str | None, str | None]:
    normalized = normalize_text(text)
    coupon_raw: str | None = None
    coupon_match = re.search(r"\b0{3,}\d{9,16}\b", normalized)
    if coupon_match:
        coupon_raw = coupon_match.group(0)

    keyword_match = re.search(
        r"(?:reference|référence|r[eé]f[eé]rence)[^\d]{0,40}(\d{9})",
        normalized,
        flags=re.IGNORECASE,
    )
    if keyword_match:
        return keyword_match.group(1), coupon_raw

    keyword_spaced_match = re.search(
        r"(?:reference|r[eé]f[eé]rence)[^\d]{0,60}(\d{5})\D{0,4}(\d{3})\D{0,4}(\d)",
        normalized,
        flags=re.IGNORECASE,
    )
    if keyword_spaced_match:
        return "".join(keyword_spaced_match.groups()), coupon_raw

    if coupon_raw:
        compact = re.sub(r"\D", "", coupon_raw).lstrip("0")
        if len(compact) >= 9:
            return compact[-9:], coupon_raw

    spaced_values = [
        "".join(match.groups())
        for match in re.finditer(r"\b(\d{5})\s+(\d{3})\s+(\d)\b", normalized)
    ]
    if spaced_values:
        return spaced_values[0], coupon_raw

    nine_digit_values = re.findall(r"\b\d{9}\b", normalized)
    return (nine_digit_values[0] if nine_digit_values else None), coupon_raw


def _normalize_ocr_year(raw_year: str) -> int:
    year = int(raw_year)
    if year > 2099 and raw_year.startswith("9"):
        candidate = int("2" + raw_year[1:])
        if 2000 <= candidate <= 2099:
            return candidate
    return year


def _normalize_short_year(raw_year: str) -> int:
    year = int(raw_year)
    return 2000 + year if year <= 79 else 1900 + year


def _iso_like_dates(text: str) -> list[str]:
    dates: list[str] = []
    for match in re.finditer(r"\b([29]0\d{2})[./-](\d{1,2})[./-](\d{1,2})\b", text or ""):
        year, month, day = match.groups()
        try:
            parsed = date(_normalize_ocr_year(year), int(month), int(day))
        except ValueError:
            continue
        value = parsed.isoformat()
        if value not in dates:
            dates.append(value)
    for match in re.finditer(r"\b(\d{1,2})[./-](\d{1,2})[./-]([29]0\d{2})\b", text or ""):
        day, month, year = match.groups()
        try:
            parsed = date(_normalize_ocr_year(year), int(month), int(day))
        except ValueError:
            continue
        value = parsed.isoformat()
        if value not in dates:
            dates.append(value)
    for match in re.finditer(r"\b(\d{1,2})[./-](\d{1,2})[./-](\d{2})\b", text or ""):
        day, month, year = match.groups()
        try:
            parsed = date(_normalize_short_year(year), int(month), int(day))
        except ValueError:
            continue
        value = parsed.isoformat()
        if value not in dates:
            dates.append(value)
    return dates


def _first_iso_like_date(text: str) -> str | None:
    dates = _iso_like_dates(text)
    return dates[0] if dates else None


def _steg_invoice_date_from_text(text: str, excluded: set[str]) -> str | None:
    for value in _iso_like_dates(text):
        if value not in excluded:
            return value
    return None


def _steg_meter_number_from_text(text: str) -> str | None:
    normalized = normalize_text(text)
    match = re.search(
        r"(?:n\s*[°ºo.]?\s*compteur|num[eé]ro\s+compteur|compteur)",
        normalized,
        flags=re.IGNORECASE,
    )
    if not match:
        return None
    window = normalized[match.end(): match.end() + 180]

    for token in re.findall(r"\d{4,14}", window):
        if token.startswith("20"):
            continue
        if 4 <= len(token) <= 8:
            return token
    for token in re.findall(r"\d{9,14}", window):
        if not token.startswith("20"):
            return token
    return None


def _steg_header_fields_from_image(image_path: Path) -> dict[str, str]:
    if image_path.suffix.lower() not in IMAGE_SUFFIXES:
        return {}
    try:
        cache_key = f"{image_path.resolve()}:{image_path.stat().st_mtime_ns}:{image_path.stat().st_size}"
    except OSError:
        cache_key = str(image_path)
    cached = _STEG_HEADER_FIELD_CACHE.get(cache_key)
    if cached is not None:
        return dict(cached)

    try:
        import cv2
    except Exception:
        return {}

    image = cv2.imread(str(image_path))
    if image is None or image.size == 0:
        return {}
    if image.shape[1] > image.shape[0] * 1.08:
        image = cv2.rotate(image, cv2.ROTATE_90_CLOCKWISE)

    text_chars = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789/.-,: "
    header_text = _quick_steg_ocr(
        _quick_steg_crop(image, 0.38, 0.15, 0.88, 0.32),
        whitelist=text_chars,
        psm=6,
        timeout=3.0,
    )
    fields: dict[str, str] = {}
    meter_number = _steg_meter_number_from_text(header_text)
    if meter_number:
        fields["numero_compteur"] = meter_number
    header_dates = _iso_like_dates(header_text)
    if header_dates:
        fields["date_facture"] = header_dates[0]
    _STEG_HEADER_FIELD_CACHE[cache_key] = dict(fields)
    return fields


def _quick_steg_crop(image: Any, x1: float, y1: float, x2: float, y2: float) -> Any:
    h, w = image.shape[:2]
    xa = max(0, min(w, int(w * x1)))
    xb = max(0, min(w, int(w * x2)))
    ya = max(0, min(h, int(h * y1)))
    yb = max(0, min(h, int(h * y2)))
    return image[ya:yb, xa:xb]


def _quick_steg_ocr(
    image: Any,
    *,
    whitelist: str | None = None,
    psm: int = 6,
    timeout: float = 3.0,
) -> str:
    try:
        import cv2
        import pytesseract
    except Exception:
        return ""

    if image is None or image.size == 0:
        return ""
    try:
        configure_tesseract()
    except Exception:
        return ""

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if len(image.shape) == 3 else image
    h, w = gray.shape[:2]
    scale = 1.0
    if min(h, w) < 420:
        scale = min(3.0, 420.0 / float(max(min(h, w), 1)))
    elif max(h, w) > 1400:
        scale = 1400.0 / float(max(h, w))
    if abs(scale - 1.0) > 0.02:
        gray = cv2.resize(
            gray,
            (max(1, int(w * scale)), max(1, int(h * scale))),
            interpolation=cv2.INTER_CUBIC if scale > 1 else cv2.INTER_AREA,
        )
    try:
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        gray = clahe.apply(gray)
    except Exception:
        pass
    variants = [gray]
    try:
        blur = cv2.GaussianBlur(gray, (3, 3), 0)
        _, otsu = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        adaptive = cv2.adaptiveThreshold(
            blur,
            255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY,
            35,
            11,
        )
        variants.extend([otsu, adaptive])
    except Exception:
        pass

    best = ""
    best_score = -1.0
    psm_values = tuple(dict.fromkeys((psm, 11)))
    for variant in variants:
        for psm_value in psm_values:
            config = f"--oem 3 --psm {psm_value}"
            if whitelist:
                config += f" -c tessedit_char_whitelist={whitelist}"
            try:
                text = pytesseract.image_to_string(
                    variant,
                    lang="eng",
                    config=config,
                    timeout=timeout,
                ) or ""
            except Exception:
                continue
            digit_count = len(re.findall(r"\d", text))
            alpha_count = len(re.findall(r"[A-Za-z]", text))
            score = digit_count * 3.0 + alpha_count * 0.8 + len(text.strip()) * 0.05
            if score > best_score:
                best_score = score
                best = text
    return best


def _quick_steg_crop_candidates(
    image: Any,
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    *,
    whitelist: str,
    psm_values: tuple[int, ...] = (6, 11),
    timeout: float = 3.0,
) -> list[str]:
    try:
        import cv2
        import pytesseract
    except Exception:
        return []
    try:
        configure_tesseract()
    except Exception:
        return []
    roi = _quick_steg_crop(image, x1, y1, x2, y2)
    if roi is None or roi.size == 0:
        return []
    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY) if len(roi.shape) == 3 else roi
    gray = cv2.resize(gray, None, fx=2.4, fy=2.4, interpolation=cv2.INTER_CUBIC)
    variants = [gray]
    try:
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        variants.append(clahe.apply(gray))
    except Exception:
        pass
    try:
        blur = cv2.GaussianBlur(gray, (3, 3), 0)
        _, otsu = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        variants.append(otsu)
    except Exception:
        pass
    texts: list[str] = []
    for variant in variants:
        for psm in psm_values:
            config = f"--oem 3 --psm {psm} -c tessedit_char_whitelist={whitelist}"
            try:
                text = pytesseract.image_to_string(
                    variant,
                    lang="eng",
                    config=config,
                    timeout=timeout,
                ) or ""
            except Exception:
                continue
            if text.strip():
                texts.append(text)
    return texts


def _best_steg_reference_from_zone(image: Any) -> tuple[str | None, str]:
    from collections import Counter

    texts = _quick_steg_crop_candidates(
        image,
        0.13,
        0.09,
        0.43,
        0.18,
        whitelist="0123456789 ",
        psm_values=(6, 11),
    )
    best_raw = "\n".join(texts)
    candidates: list[tuple[int, str]] = []
    for text in texts:
        for match in re.finditer(r"\b(\d{5})\s+(\d{3})\s+(\d)\b", text):
            candidates.append((1000 - abs(len(re.sub(r"\D", "", text)) - 9), "".join(match.groups())))
        digits_only = re.sub(r"\D", "", text)
        if len(digits_only) == 9:
            candidates.append((900, digits_only))
        for token in re.findall(r"\d{9}", digits_only):
            candidates.append((700, token))
    if not candidates:
        return None, best_raw
    counts = Counter(token for _score, token in candidates)
    return max(candidates, key=lambda item: (counts[item[1]], item[0]))[1], best_raw


def _best_steg_due_date_from_zone(image: Any) -> tuple[str | None, str]:
    texts = _quick_steg_crop_candidates(
        image,
        0.68,
        0.75,
        0.84,
        0.84,
        whitelist="0123456789. ",
        psm_values=(6, 11),
    )
    raw = "\n".join(texts)
    for text in texts:
        dates = _iso_like_dates(text)
        if dates:
            return dates[0], raw
    return None, raw


def _compact_steg_amount(raw: str) -> str | None:
    direct_matches = [
        f"{left},{right}"
        for left, right in re.findall(r"(?<!\d)(\d{2,4})\s*[,.]\s*(\d{3})(?!\d)", raw or "")
    ]
    if direct_matches:
        plausible = [item for item in direct_matches if _amount_to_float(item) >= 10]
        return max(plausible or direct_matches, key=_amount_to_float)

    text = normalize_text(raw).replace("o", "0").replace("O", "0").replace(".", ",")
    text = re.sub(r"\b([1-9])\s+(\d{2},\d{3})(?!\d)", r"\1\2", text)
    text = re.sub(r"(\d{1,4})\s+(\d{3})(?!\d)", r"\1,\2", text)
    matches = re.findall(r"(?<!\d)(\d{1,4},\d{3})(?!\d)", text)
    if matches:
        plausible = [item for item in matches if _amount_to_float(item) >= 10]
        return max(plausible or matches, key=_amount_to_float)
    compact = re.sub(r"\D", "", text)
    for match in re.finditer(r"(\d{3,4})000", compact):
        value = f"{match.group(1)},000"
        if _amount_to_float(value) >= 10:
            return value
    return None


def _quick_steg_fields_from_image(image_path: Path) -> dict[str, Any]:
    try:
        import cv2
    except Exception:
        return {}

    image = cv2.imread(str(image_path))
    if image is None or image.size == 0:
        return {}
    if image.shape[1] > image.shape[0] * 1.08:
        image = cv2.rotate(image, cv2.ROTATE_90_CLOCKWISE)

    digit_chars = "0123456789,. "
    text_chars = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789/.-,: "
    zone_reference, reference_zone_text = _best_steg_reference_from_zone(image)
    zone_due_date, due_zone_text = _best_steg_due_date_from_zone(image)
    amount_text = _quick_steg_ocr(
        _quick_steg_crop(image, 0.00, 0.66, 0.54, 0.86),
        whitelist=digit_chars,
        psm=6,
    )

    fields: dict[str, Any] = {}
    if zone_reference:
        fields["reference"] = zone_reference
    if zone_due_date:
        fields["date_limite_paiement"] = zone_due_date

    amount = _compact_steg_amount(amount_text)
    if amount:
        fields["montant_a_payer"] = amount
        fields["coupon_montant"] = amount

    if (
        fields.get("reference")
        and fields.get("montant_a_payer")
        and fields.get("date_limite_paiement")
    ):
        fields["_quick_ocr_debug"] = {
            "amount_text": amount_text[:300],
            "reference_zone_text": reference_zone_text[:300],
            "due_zone_text": due_zone_text[:300],
        }
        return fields

    coupon_text = _quick_steg_ocr(
        _quick_steg_crop(image, 0.50, 0.78, 1.00, 1.00),
        whitelist=digit_chars,
        psm=6,
    )
    if "montant_a_payer" not in fields:
        amount = _compact_steg_amount(coupon_text)
        if amount:
            fields["montant_a_payer"] = amount
            fields["coupon_montant"] = amount

    date_text = _quick_steg_ocr(
        _quick_steg_crop(image, 0.64, 0.72, 1.00, 0.90),
        whitelist=digit_chars,
        psm=6,
    )
    due_date_text = _quick_steg_ocr(
        _quick_steg_crop(image, 0.68, 0.75, 0.84, 0.84),
        whitelist="0123456789. ",
        psm=6,
    )
    next_date_text = _quick_steg_ocr(
        _quick_steg_crop(image, 0.82, 0.75, 1.00, 0.84),
        whitelist="0123456789. ",
        psm=6,
    )
    invoice_date_text = _quick_steg_ocr(
        _quick_steg_crop(image, 0.54, 0.16, 1.00, 0.31),
        whitelist=digit_chars,
        psm=6,
    )
    reference_text = _quick_steg_ocr(
        _quick_steg_crop(image, 0.13, 0.09, 0.43, 0.18),
        whitelist=digit_chars,
        psm=6,
    )
    coupon_ref_text = _quick_steg_ocr(
        _quick_steg_crop(image, 0.52, 0.86, 0.92, 1.00),
        whitelist=digit_chars,
        psm=7,
    )
    header_text = _quick_steg_ocr(
        _quick_steg_crop(image, 0.00, 0.10, 0.82, 0.46),
        whitelist=text_chars,
        psm=6,
    )

    ref_from_reference_text, _ = _steg_reference_from_text(reference_text)
    if ref_from_reference_text and "reference" not in fields:
        fields["reference"] = ref_from_reference_text

    if "reference" not in fields:
        long_digit_tokens = re.findall(r"\d{12,20}", normalize_text(coupon_text + "\n" + coupon_ref_text))
        for token in long_digit_tokens:
            ref = derive_reference_from_footer_compact(token)
            if ref:
                fields["coupon_reference_raw"] = token
                fields["reference"] = ref
                break

    if "reference" not in fields:
        ref_from_header, _coupon = _steg_reference_from_text(header_text)
        if ref_from_header:
            fields["reference"] = ref_from_header

    due_dates = _iso_like_dates(due_date_text)
    dates = _iso_like_dates(
        date_text
        + "\n"
        + due_date_text
        + "\n"
        + next_date_text
        + "\n"
        + invoice_date_text
        + "\n"
        + header_text
        + "\n"
        + coupon_text
    )
    if "date_limite_paiement" not in fields and due_dates:
        fields["date_limite_paiement"] = due_dates[0]
    elif "date_limite_paiement" not in fields and dates:
        fields["date_limite_paiement"] = max(dates)
    if dates:
        invoice_dates = [item for item in dates if item != fields.get("date_limite_paiement")]
        if invoice_dates:
            fields["date_facture"] = min(invoice_dates)

    meter_match = re.search(r"\b[A-Z]\d{7,16}[A-Z0-9/]*\b", header_text)
    if meter_match:
        fields["numero_compteur"] = meter_match.group(0).strip(" .,:;")

    fields["_quick_ocr_debug"] = {
        "amount_text": amount_text[:300],
        "coupon_text": coupon_text[:300],
        "date_text": date_text[:300],
        "due_date_text": due_date_text[:300],
        "next_date_text": next_date_text[:300],
        "invoice_date_text": invoice_date_text[:300],
        "reference_text": reference_text[:300],
        "reference_zone_text": reference_zone_text[:300],
        "due_zone_text": due_zone_text[:300],
        "coupon_ref_text": coupon_ref_text[:300],
        "header_text": header_text[:300],
    }
    return fields


def _fast_steg_local_result(
    cfg: AppConfig,
    *,
    filename: str,
    file_bytes: bytes,
    tmp_path: Path,
    source_origin: str,
    kind: str = "steg_local",
    extraction_source: str = "hybrid_local_fast_steg_ocr",
) -> dict[str, Any]:
    detected_kind = "steg_invoice"
    content = None
    content_error: str | None = None
    preprocessing_meta: dict[str, Any] | None = None
    preprocessing_error: str | None = None
    quick_fields: dict[str, Any] = {}
    quick_ocr_error: str | None = None
    text = ""
    try:
        quick_fields = _quick_steg_fields_from_image(tmp_path)
    except Exception as exc:
        quick_ocr_error = f"{type(exc).__name__}: {exc}"

    quick_complete = bool(
        quick_fields.get("reference")
        and quick_fields.get("montant_a_payer")
        and quick_fields.get("date_limite_paiement")
    )
    if quick_complete:
        debug = quick_fields.get("_quick_ocr_debug")
        text = json.dumps(debug, ensure_ascii=False) if isinstance(debug, dict) else ""
    else:
        with tempfile.TemporaryDirectory() as prep_dir:
            content_path = tmp_path
            try:
                preprocessed = preprocess_document(tmp_path, Path(prep_dir))
                content_path = preprocessed.path
                preprocessing_meta = preprocessed.metadata
            except Exception as exc:
                preprocessing_error = f"{type(exc).__name__}: {exc}"

            try:
                content = _content_for_extraction(
                    content_path,
                    mode="steg",
                    preprocessing=preprocessing_meta,
                )
                text = content.text or ""
            except Exception as exc:
                content_error = f"{type(exc).__name__}: {exc}"

    reference_from_text, coupon_reference_from_text = _steg_reference_from_text(text)
    amount_from_text = _best_steg_amount(text)
    reference = str(quick_fields.get("reference") or "") or reference_from_text
    amount = str(quick_fields.get("montant_a_payer") or "") or amount_from_text
    coupon_reference = (
        str(quick_fields.get("coupon_reference_raw") or "")
        if quick_fields.get("coupon_reference_raw")
        else coupon_reference_from_text
    )
    coupon_amount = str(quick_fields.get("coupon_montant") or "") or amount
    if not amount and coupon_amount:
        amount = coupon_amount
    dates_from_text = _iso_like_dates(text)
    date_limite_paiement = (
        str(quick_fields.get("date_limite_paiement") or "")
        if quick_fields.get("date_limite_paiement")
        else (max(dates_from_text) if dates_from_text else None)
    )
    date_facture = str(quick_fields.get("date_facture") or "") or _steg_invoice_date_from_text(
        text,
        {date_limite_paiement} if date_limite_paiement else set(),
    ) or (min(dates_from_text) if dates_from_text else date_limite_paiement)
    numero_compteur = str(quick_fields.get("numero_compteur") or "") or _steg_meter_number_from_text(text)
    periode_du = None
    periode_au = None
    reference = reference or None
    amount = amount or None
    coupon_reference = coupon_reference or None
    coupon_amount = coupon_amount or None
    date_limite_paiement = date_limite_paiement or None
    date_facture = date_facture or None
    numero_compteur = numero_compteur or None
    confidence_note = "medium" if reference and amount else "low"

    warnings = [
        {
            "code": "FAST_STEG_OCR",
            "message": "Facture STEG image: OCR texte rapide utilise pour remplir les champs sans attendre Qwen/Ollama.",
        }
    ]
    if content_error:
        warnings.append(
            {
                "code": "STEG_TEXT_FALLBACK_FAILED",
                "message": f"OCR texte alternatif indisponible: {content_error}",
            }
        )
    if preprocessing_error:
        warnings.append(
            {
                "code": "DOCUMENT_PREPROCESSING_FAILED",
                "message": f"Pretraitement image ignore: {preprocessing_error}",
            }
        )
    if quick_ocr_error:
        warnings.append(
            {
                "code": "STEG_QUICK_ZONE_OCR_FAILED",
                "message": f"Lecture rapide des zones STEG indisponible: {quick_ocr_error}",
            }
        )

    payload = {
        "document_type": "steg_invoice",
        "reference": reference,
        "numero_compteur": numero_compteur,
        "date_facture": date_facture,
        "montant_a_payer": amount,
        "date_limite_paiement": date_limite_paiement,
        "periode_du": periode_du,
        "periode_au": periode_au,
        "coupon_reference_raw": coupon_reference,
        "coupon_montant": coupon_amount,
        "confidence_note": confidence_note,
        "raw_text": text[:80000],
        "extraction_source": extraction_source,
        "warnings": warnings,
        "local_pipeline": {
            "architecture": "Pretraitement -> OCR STEG specialise -> JSON structure",
            "content_source": content.source if content is not None else "steg_specialized_ocr",
            "qwen_used": False,
            "reason": "Retour rapide pour eviter les timeouts sur image STEG.",
            "preprocessing": preprocessing_meta,
            "fallback_used": content.fallback_used if content is not None else not quick_complete,
            "fallback_quality": content.fallback_quality if content is not None else None,
            "docling_error": content.docling_error if content is not None else content_error,
            "quick_zone_ocr_used": bool(quick_fields),
            "quick_zone_ocr_debug": quick_fields.get("_quick_ocr_debug"),
        },
    }

    history_relative: str | None = None
    try:
        history_path = save_extraction(
            cfg,
            kind,
            filename,
            payload,
            source_bytes=file_bytes,
            status="ok",
            detected_kind=detected_kind,
        )
        history_relative = str(history_path.relative_to(cfg.extraction_history_dir))
    except Exception:
        history_relative = None

    return _successful_result(
        kind=kind,
        payload=payload,
        history_relative=history_relative,
        detected_kind=detected_kind,
        source_origin=source_origin,
        filename=filename,
    )


LOCAL_KIND_DETECTED = {
    "medical_local": "medical_lab_report",
    "steg_local": "steg_invoice",
    "receipt_local": "receipt",
    "supplier_invoice_local": "supplier_invoice",
    "document_local": "unknown",
}


def _sroie_box_to_text(path: Path) -> str:
    lines: list[str] = []
    for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        raw_line = raw_line.strip()
        if not raw_line:
            continue
        parts = raw_line.split(",", 8)
        lines.append(parts[8].strip() if len(parts) >= 9 else raw_line)
    return "\n".join(lines)


def _extract_receipt_number(text: str) -> str:
    patterns = [
        r"\bInvoice\s*(?:No|Number|#)?\.?\s*:?\s*([A-Z0-9][A-Z0-9\-\/]{2,})",
        r"\bInv(?:oice)?\s*(?:No|#)?\.?\s*:?\s*([A-Z0-9][A-Z0-9\-\/]{2,})",
        r"\bBill\s*(?:No|#)?\.?\s*:?\s*([A-Z0-9][A-Z0-9\-\/]{2,})",
        r"\bReceipt\s*(?:No|#)?\.?\s*:?\s*([A-Z0-9][A-Z0-9\-\/]{2,})",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return match.group(1).strip(" .:-")
    return ""


MODE_DETECTED_KIND = {
    "medical": "medical_lab_report",
    "steg": "steg_invoice",
    "supplier": "supplier_invoice",
    "receipt": "receipt",
}


def _detect_kind_safely(tmp_path: Path, *, filename: str, origin: str, mode: str) -> str:
    if mode in MODE_DETECTED_KIND:
        return MODE_DETECTED_KIND[mode]
    try:
        detected = detect_document_type(
            tmp_path,
            filename_hint=filename,
            path_hint=origin,
        )
    except Exception:
        detected = ""
    return detected or "medical_lab_report"


def _quick_ocr_text_for_fallback(path: Path) -> str:
    if path.suffix.lower() == ".pdf":
        try:
            from src.services.supplier_invoice_ocr import extract_pdf_embedded_text

            embedded = extract_pdf_embedded_text(path, max_pages=2)
            if embedded.strip():
                return embedded
        except Exception:
            return ""

    try:
        import cv2
        import pytesseract
    except Exception:
        return ""

    try:
        configure_tesseract()
    except Exception:
        return ""

    image = cv2.imread(str(path))
    if image is None or image.size == 0:
        return ""
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if len(image.shape) == 3 else image
    h, w = gray.shape[:2]
    max_side = max(h, w)
    min_side = max(min(h, w), 1)
    if max_side > 1800:
        scale = 1800.0 / float(max_side)
        gray = cv2.resize(gray, (max(1, int(w * scale)), max(1, int(h * scale))), interpolation=cv2.INTER_AREA)
    elif min_side < 900:
        scale = min(2.0, 900.0 / float(min_side))
        gray = cv2.resize(gray, (max(1, int(w * scale)), max(1, int(h * scale))), interpolation=cv2.INTER_CUBIC)

    variants = [gray]
    try:
        blur = cv2.GaussianBlur(gray, (3, 3), 0)
        _, otsu = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        variants.append(otsu)
    except Exception:
        pass

    try:
        available = set(pytesseract.get_languages(config=""))
    except Exception:
        available = {"eng"}
    if {"fra", "eng"}.issubset(available):
        lang = "fra+eng"
    elif "fra" in available:
        lang = "fra"
    else:
        lang = "eng"

    best = ""
    best_score = -1.0
    for variant in variants[:2]:
        for psm in (6, 11):
            try:
                text = pytesseract.image_to_string(
                    variant,
                    lang=lang,
                    config=f"--oem 3 --psm {psm}",
                    timeout=4.0,
                ) or ""
            except Exception:
                continue
            score = len(re.findall(r"[A-Za-z]", text)) * 0.3 + len(re.findall(r"\d", text)) * 1.2
            if score > best_score:
                best_score = score
                best = text
    return best


def _ocr_text_for_fallback(tmp_path: Path) -> tuple[str, list[dict[str, str]]]:
    warnings: list[dict[str, str]] = [
        {
            "code": "LOCAL_OCR_FALLBACK",
            "message": "Extraction alternative par OCR local utilisee pour produire un JSON exploitable.",
        }
    ]
    try:
        text = _quick_ocr_text_for_fallback(tmp_path)
    except Exception as exc:
        warnings.append(
            {
                "code": "LOCAL_OCR_TEXT_UNAVAILABLE",
                "message": f"Lecture OCR alternative limitee: {type(exc).__name__}: {exc}",
            }
        )
        text = ""
    if not text.strip():
        warnings.append(
            {
                "code": "EMPTY_OCR_TEXT",
                "message": "Texte OCR faible; les champs doivent etre verifies manuellement.",
            }
        )
    return text, warnings


def _money_candidates(text: str) -> list[str]:
    candidates: list[str] = []
    pattern = (
        r"(?<!\d)(?:\d{1,4}(?:[ \u00a0\u202f]\d{3})+|\d{1,6})"
        r"\s*[,.]\s*\d{2,3}(?!\d)"
    )
    for raw in re.findall(pattern, text or ""):
        value = re.sub(r"\s+", "", raw)
        if value not in candidates:
            candidates.append(value)
    for value in _amount_candidates_from_text(text):
        if value not in candidates:
            candidates.append(value)
    return candidates


def _best_amount_for_keys(text: str, keys: tuple[str, ...]) -> str:
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    keyed: list[str] = []
    for line in lines:
        lower = line.casefold()
        if any(key in lower for key in keys):
            keyed.extend(_money_candidates(line))
    candidates = keyed or _money_candidates(text)
    if not candidates:
        return ""
    return max(candidates, key=_amount_to_float)


def _first_business_line(text: str, *, skip: tuple[str, ...]) -> str:
    for line in (text or "").splitlines():
        cleaned = re.sub(r"\s+", " ", line).strip(" -_:;|")
        if len(cleaned) < 3:
            continue
        lower = cleaned.casefold()
        if any(key in lower for key in skip):
            continue
        if len(re.findall(r"[a-zA-Z]", cleaned)) < 3:
            continue
        if len(re.findall(r"\d", cleaned)) > len(cleaned) * 0.45:
            continue
        return cleaned[:90].strip().title()
    return ""


def _domain_store_from_text(text: str) -> str:
    ignored = {"facebook", "google", "instagram", "youtube", "gmail", "hotmail", "mail"}
    normalized = re.sub(r"\s+", " ", text or "")
    for match in re.finditer(
        r"(?:www\s*\.?\s*)?([a-z][a-z0-9-]{1,24})\s*\.\s*(?:com|tn|fr|net|org)(?:\s*\.\s*[a-z]{2})?",
        normalized,
        flags=re.IGNORECASE,
    ):
        domain = match.group(1).strip(" .-").casefold()
        if domain and domain not in ignored:
            return domain.upper() if len(domain) <= 3 else domain.replace("-", " ").title()
    return ""


def _looks_like_receipt_store_noise(value: str) -> bool:
    cleaned = re.sub(r"\s+", " ", value or "").strip()
    if not cleaned:
        return True
    if any(char in cleaned for char in ("°", "Â°")):
        return True
    letters = len(re.findall(r"[A-Za-zÀ-ÿ]", cleaned))
    digits = len(re.findall(r"\d", cleaned))
    if letters < 2:
        return True
    if digits > letters and not re.search(r"\b7\s*-?\s*eleven\b", cleaned, flags=re.IGNORECASE):
        return True
    return False


def _receipt_store_from_text(text: str) -> str:
    lower = (text or "").casefold()
    domain_store = _domain_store_from_text(text)
    if domain_store:
        return domain_store
    known = (
        "zara",
        "carrefour",
        "monoprix",
        "geant",
        "aziza",
        "mg",
        "costco",
        "walmart",
        "decathlon",
        "lc waikiki",
    )
    for brand in known:
        if re.search(rf"\b{re.escape(brand)}\b", lower):
            return brand.upper()
    candidate = _first_business_line(
        text,
        skip=("ticket", "total", "ttc", "tva", "date", "caisse", "paiement", "cash", "visa", "www", "facebook"),
    )
    return "" if _looks_like_receipt_store_noise(candidate) else candidate


def _normalize_receipt_payload_fields(payload: dict[str, Any]) -> dict[str, Any]:
    next_payload = dict(payload)
    raw_text = str(next_payload.get("raw_text") or "")
    detected_store = _receipt_store_from_text(raw_text)
    current_store = str(next_payload.get("store_name") or "").strip()
    if detected_store and (not current_store or _looks_like_receipt_store_noise(current_store)):
        next_payload["store_name"] = detected_store
    if not next_payload.get("date"):
        next_payload["date"] = _first_iso_like_date(raw_text)
    if not next_payload.get("ticket_number"):
        next_payload["ticket_number"] = _ticket_number_from_text(raw_text) or None
    return next_payload


def _normalize_document_payload_fields(kind: str, payload: dict[str, Any]) -> dict[str, Any]:
    if kind in {"receipt", "receipt_local", "receipt_test"}:
        return _normalize_receipt_payload_fields(payload)
    if kind in {"steg_ocr", "steg_gemini", "steg_local"}:
        next_payload = dict(payload)
        raw_text = str(next_payload.get("raw_text") or "")
        if not next_payload.get("date_facture") and next_payload.get("periode_au"):
            next_payload["date_facture"] = next_payload.get("periode_au")
        if raw_text and not next_payload.get("date_facture"):
            excluded = {str(next_payload.get("date_limite_paiement") or "")}
            next_payload["date_facture"] = _steg_invoice_date_from_text(raw_text, excluded)
        return next_payload
    if kind in {"supplier_invoice", "supplier_invoice_local"}:
        next_payload = dict(payload)
        raw_text = str(next_payload.get("raw_text") or "")
        if raw_text and not next_payload.get("invoice_date"):
            next_payload["invoice_date"] = _first_iso_like_date(raw_text) or ""
        return next_payload
    return payload


def _normalize_document_payload_fields_from_source(
    cfg: AppConfig,
    entry: dict[str, Any],
    kind: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    next_payload = _normalize_document_payload_fields(kind, payload)
    if kind not in {"steg_ocr", "steg_gemini", "steg_local"}:
        return next_payload
    if next_payload.get("numero_compteur") and next_payload.get("date_facture"):
        return next_payload

    source_path = resolve_archived_source_path(entry, cfg, next_payload)
    return _normalize_steg_payload_fields_from_image_path(next_payload, source_path)


def _normalize_steg_payload_fields_from_image_path(
    payload: dict[str, Any],
    source_path: Path | None,
) -> dict[str, Any]:
    if source_path is None:
        return payload
    next_payload = dict(payload)
    if next_payload.get("numero_compteur") and next_payload.get("date_facture"):
        return next_payload
    source_fields = _steg_header_fields_from_image(source_path)
    if not next_payload.get("numero_compteur") and source_fields.get("numero_compteur"):
        next_payload["numero_compteur"] = source_fields["numero_compteur"]
    if not next_payload.get("date_facture") and source_fields.get("date_facture"):
        next_payload["date_facture"] = source_fields["date_facture"]
    return next_payload


def _ticket_number_from_text(text: str) -> str:
    base = _extract_receipt_number(text)
    if base:
        return base
    patterns = (
        r"\b(\d{5,14})\s+\d{1,2}[./-]\d{1,2}[./-]\d{2,4}\s+\d{1,2}:\d{2}\b",
        r"(?:date\s+heure|heure\s+date)[^\n]*\n[^\d]{0,24}(\d{5,14})\s+\d{1,2}[./-]\d{1,2}[./-]\d{2,4}",
        r"(?:ticket|recu|receipt|transaction|trx|caisse)\s*(?:n|no|num|numero|#)?\s*[:.-]?\s*([a-z0-9][a-z0-9/-]{2,})",
        r"\b(?:tkt|tc)\s*[:.-]?\s*([a-z0-9][a-z0-9/-]{2,})",
    )
    for pattern in patterns:
        match = re.search(pattern, text or "", flags=re.IGNORECASE)
        if match:
            return match.group(1).strip(" .:-").upper()
    return ""


def _currency_from_text(text: str) -> str:
    lower = (text or "").casefold()
    if any(key in lower for key in (" tnd", "dt", "dinars", "dinar")):
        return "TND"
    if any(key in lower for key in (" eur", "euro")):
        return "EUR"
    if any(key in lower for key in (" usd", "dollar")):
        return "USD"
    return ""


def _simple_receipt_items(text: str, *, total: str) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    skip = ("total", "ttc", "tva", "tax", "paiement", "payment", "rendu", "monnaie", "visa")
    total_norm = re.sub(r"\D", "", total or "")
    for line in (text or "").splitlines():
        cleaned = re.sub(r"\s+", " ", line).strip(" -_:;|")
        if len(cleaned) < 5:
            continue
        lower = cleaned.casefold()
        if any(key in lower for key in skip):
            continue
        amounts = _money_candidates(cleaned)
        if not amounts:
            continue
        amount = amounts[-1]
        if total_norm and re.sub(r"\D", "", amount) == total_norm:
            continue
        desc = cleaned
        for value in amounts:
            desc = desc.replace(value, " ")
        desc = re.sub(r"\s+", " ", desc).strip(" -_:;|")
        if len(desc) < 3 or len(re.findall(r"[a-zA-Z]", desc)) < 2:
            continue
        items.append(
            {
                "description": desc[:120],
                "quantity": "",
                "unit_price": "",
                "line_total": amount,
            }
        )
        if len(items) >= 12:
            break
    return items


def _supplier_invoice_number_from_text(text: str) -> str:
    patterns = (
        r"(?:invoice|facture)\s*(?:n|no|num|numero|number|#)?\s*[:.-]?\s*([a-z0-9][a-z0-9/-]{2,})",
        r"(?:n|no|num|numero|#)\s*(?:facture|invoice)?\s*[:.-]?\s*([a-z0-9][a-z0-9/-]{2,})",
    )
    for pattern in patterns:
        match = re.search(pattern, text or "", flags=re.IGNORECASE)
        if match:
            value = match.group(1).strip(" .:-").upper()
            if len(re.sub(r"\D", "", value)) >= 2:
                return value
    return ""


def _tax_id_from_text(text: str) -> str:
    for pattern in (
        r"(?:tax id|vat|tva|matricule|identifiant fiscal)[^\d]{0,30}(\d{6,20})",
        r"\b(\d{13,20})\b",
    ):
        match = re.search(pattern, text or "", flags=re.IGNORECASE)
        if match:
            return match.group(1)
    return ""


def _simple_supplier_items(text: str, *, total: str) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    skip = ("total", "subtotal", "sous total", "ttc", "tva", "tax", "invoice", "facture", "client")
    total_norm = re.sub(r"\D", "", total or "")
    for line in (text or "").splitlines():
        cleaned = re.sub(r"\s+", " ", line).strip(" -_:;|")
        if len(cleaned) < 6:
            continue
        lower = cleaned.casefold()
        if any(key in lower for key in skip):
            continue
        amounts = _money_candidates(cleaned)
        if not amounts:
            continue
        gross = amounts[-1]
        if total_norm and re.sub(r"\D", "", gross) == total_norm:
            continue
        desc = cleaned
        for value in amounts:
            desc = desc.replace(value, " ")
        desc = re.sub(r"\s+", " ", desc).strip(" -_:;|")
        if len(desc) < 3 or len(re.findall(r"[a-zA-Z]", desc)) < 2:
            continue
        items.append(
            {
                "description": desc[:140],
                "quantity": "",
                "unit": "",
                "unit_price": amounts[0] if len(amounts) > 1 else "",
                "net_amount": "",
                "tax_rate": "",
                "tax_amount": "",
                "gross_amount": gross,
            }
        )
        if len(items) >= 12:
            break
    return items


def _local_fallback_result(
    cfg: AppConfig,
    *,
    filename: str,
    file_bytes: bytes,
    source_origin: str,
    detected_kind: str,
    kind: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    history_relative: str | None = None
    try:
        history_path = save_extraction(
            cfg,
            kind,
            filename,
            payload,
            source_bytes=file_bytes,
            status="ok",
            detected_kind=detected_kind,
        )
        history_relative = str(history_path.relative_to(cfg.extraction_history_dir))
    except Exception as exc:
        warnings = payload.get("warnings")
        if not isinstance(warnings, list):
            warnings = []
        warnings.append({"code": "HISTORY_SAVE_WARNING", "message": f"Historique non enregistre: {exc}"})
        payload["warnings"] = warnings

    return _successful_result(
        kind=kind,
        payload=payload,
        history_relative=history_relative,
        detected_kind=detected_kind,
        source_origin=source_origin,
        filename=filename,
    )


def _fallback_receipt_local_result(
    cfg: AppConfig,
    *,
    filename: str,
    file_bytes: bytes,
    tmp_path: Path,
    source_origin: str,
    reason: str,
) -> dict[str, Any]:
    text, warnings = _ocr_text_for_fallback(tmp_path)
    warnings.insert(0, {"code": "PRIMARY_PIPELINE_FALLBACK", "message": reason})
    total = _best_amount_for_keys(text, ("total", "ttc", "net", "payer", "amount"))
    payload = {
        "document_type": "receipt",
        "store_name": _receipt_store_from_text(text) or None,
        "date": _first_iso_like_date(text),
        "time": "",
        "ticket_number": _ticket_number_from_text(text) or None,
        "currency": _currency_from_text(text) or None,
        "items": _simple_receipt_items(text, total=total),
        "total": total or None,
        "payment_method": "Carte" if re.search(r"\b(visa|mastercard|carte)\b", text or "", re.I) else None,
        "raw_text": text[:80000],
        "warnings": warnings,
        "extraction_source": "ocr_local_receipt_fallback",
        "local_pipeline": {
            "architecture": "OCR local -> heuristiques ticket -> JSON structure",
            "content_source": "tesseract_router_ocr",
            "qwen_used": False,
            "reason": reason,
        },
    }
    if not payload["store_name"] or not payload["total"]:
        payload["warnings"].append(
            {
                "code": "FIELDS_TO_REVIEW",
                "message": "Certains champs du ticket doivent etre verifies dans l'interface.",
            }
        )
    return _local_fallback_result(
        cfg,
        filename=filename,
        file_bytes=file_bytes,
        source_origin=source_origin,
        detected_kind="receipt",
        kind="receipt_local",
        payload=payload,
    )


def _fallback_supplier_local_result(
    cfg: AppConfig,
    *,
    filename: str,
    file_bytes: bytes,
    tmp_path: Path,
    source_origin: str,
    reason: str,
) -> dict[str, Any]:
    text, warnings = _ocr_text_for_fallback(tmp_path)
    warnings.insert(0, {"code": "PRIMARY_PIPELINE_FALLBACK", "message": reason})
    total = _best_amount_for_keys(text, ("total", "ttc", "amount due", "balance", "net a payer", "montant"))
    seller_name = _first_business_line(
        text,
        skip=("invoice", "facture", "client", "customer", "total", "date", "due", "tax", "tva"),
    )
    payload = {
        "document_type": "supplier_invoice",
        "invoice_number": _supplier_invoice_number_from_text(text),
        "invoice_date": _first_iso_like_date(text) or "",
        "due_date": "",
        "currency": _currency_from_text(text),
        "seller": {
            "name": seller_name,
            "address": "",
            "tax_id": _tax_id_from_text(text),
            "iban": "",
            "email": "",
            "phone": "",
        },
        "client": {"name": "", "address": "", "tax_id": "", "email": "", "phone": ""},
        "items": _simple_supplier_items(text, total=total),
        "summary": {
            "subtotal": "",
            "tax_total": "",
            "discount": "",
            "shipping": "",
            "total_amount": total,
            "amount_due": total,
        },
        "confidence": "low" if not total else "medium",
        "missing_fields": [],
        "raw_notes": "Extraction OCR local alternative; verification conseillee.",
        "raw_text": text[:80000],
        "warnings": warnings,
        "extraction_source": "ocr_local_supplier_fallback",
        "local_pipeline": {
            "architecture": "OCR local -> heuristiques facture fournisseur -> JSON structure",
            "content_source": "tesseract_router_ocr",
            "qwen_used": False,
            "reason": reason,
        },
    }
    missing = []
    if not payload["invoice_number"]:
        missing.append("invoice_number")
    if not total:
        missing.append("summary.total_amount")
    if not seller_name:
        missing.append("seller.name")
    payload["missing_fields"] = missing
    if missing:
        payload["warnings"].append(
            {
                "code": "FIELDS_TO_REVIEW",
                "message": "Certains champs de la facture fournisseur doivent etre verifies dans l'interface.",
            }
        )
    return _local_fallback_result(
        cfg,
        filename=filename,
        file_bytes=file_bytes,
        source_origin=source_origin,
        detected_kind="supplier_invoice",
        kind="supplier_invoice_local",
        payload=payload,
    )


def _local_pipeline_blockers(ollama_host: str | None, local_model: str | None) -> list[str]:
    blockers: list[str] = []
    docling_ready = _docling_available()
    paddleocr_ready = _paddleocr_available()
    if not docling_ready:
        blockers.append(
            "Docling n'est pas installe. Il est requis pour produire le Markdown structure."
        )
    if not paddleocr_ready:
        blockers.append(
            "PaddleOCR n'est pas installe. Il est requis comme fallback OCR pour les images/scans et les PDF faibles."
        )
    if not _ollama_available(ollama_host):
        host = (ollama_host or _default_ollama_host()).rstrip("/")
        model = (local_model or _default_local_model()).strip()
        blockers.append(
            f"Ollama ne repond pas sur {host}. Lance Ollama puis verifie le modele: ollama pull {model}"
        )
    return blockers


def process_single_document(
    cfg: AppConfig,
    *,
    filename: str,
    file_bytes: bytes,
    origin: str,
    mode: str,
    extraction_method: str,
    gemini_api_key: str | None,
    gemini_model: str | None,
    ollama_host: str | None,
    local_model: str | None,
    retries: int,
    retry_delay: float,
    temp_dir: str | None = None,
) -> dict[str, Any]:
    suffix = Path(filename).suffix.lower() or ".bin"
    use_local_ocr = extraction_method == "ocr"
    effective_mode = "auto" if origin != "upload" else mode
    detected_kind = MODE_DETECTED_KIND.get(effective_mode, "medical_lab_report")

    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix, dir=temp_dir) as tmp:
        tmp.write(file_bytes)
        tmp_path = Path(tmp.name)
    detected_kind = _detect_kind_safely(
        tmp_path,
        filename=filename,
        origin=origin,
        mode=effective_mode,
    )

    routed = None
    processing_error: str | None = None
    gemini_generic_result = None
    gemini_generic_error = None
    gemini_receipt_result = None
    gemini_receipt_error = None
    gemini_supplier_result = None
    gemini_supplier_error = None

    gkey = (gemini_api_key or "").strip() or cfg.gemini_api_key or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")

    try:
        is_receipt_mode = effective_mode == "receipt"

        if extraction_method == "local":
            if effective_mode == "steg" and suffix in IMAGE_SUFFIXES:
                return _fast_steg_local_result(
                    cfg,
                    filename=filename,
                    file_bytes=file_bytes,
                    tmp_path=tmp_path,
                    source_origin=origin,
                )

            if effective_mode == "auto" and suffix in IMAGE_SUFFIXES:
                try:
                    auto_detected_kind = detect_document_type(
                        tmp_path,
                        filename_hint=filename,
                        path_hint=origin,
                    )
                except Exception:
                    auto_detected_kind = ""
                if auto_detected_kind:
                    detected_kind = auto_detected_kind
                if auto_detected_kind == "steg_invoice":
                    return _fast_steg_local_result(
                        cfg,
                        filename=filename,
                        file_bytes=file_bytes,
                        tmp_path=tmp_path,
                        source_origin=origin,
                    )
                if auto_detected_kind == "medical_lab_report":
                    return _fast_medical_ocr_result(
                        cfg,
                        filename=filename,
                        file_bytes=file_bytes,
                        tmp_path=tmp_path,
                        source_origin=origin,
                        kind="medical_local",
                        extraction_source="hybrid_local_fast_medical_ocr",
                        extra_warning=(
                            "Analyse medicale image: fallback rapide utilise pour garantir "
                            "un resultat sans blocage utilisateur."
                        ),
                    )

            blockers = _local_pipeline_blockers(
                ollama_host or os.getenv("OLLAMA_HOST") or "http://127.0.0.1:11434",
                local_model or os.getenv("OLLAMA_MODEL") or "qwen2.5:7b-instruct",
            )
            if blockers:
                reason = "Pipeline IA local incomplet; fallback OCR local applique."
                if detected_kind == "receipt":
                    return _fallback_receipt_local_result(
                        cfg,
                        filename=filename,
                        file_bytes=file_bytes,
                        tmp_path=tmp_path,
                        source_origin=origin,
                        reason=reason,
                    )
                if detected_kind == "supplier_invoice":
                    return _fallback_supplier_local_result(
                        cfg,
                        filename=filename,
                        file_bytes=file_bytes,
                        tmp_path=tmp_path,
                        source_origin=origin,
                        reason=reason,
                    )
                if detected_kind == "medical_lab_report" and suffix in IMAGE_SUFFIXES:
                    return _fast_medical_ocr_result(
                        cfg,
                        filename=filename,
                        file_bytes=file_bytes,
                        tmp_path=tmp_path,
                        source_origin=origin,
                        kind="medical_local",
                        extraction_source="hybrid_local_fast_medical_ocr",
                        extra_warning=reason,
                    )
                if detected_kind == "steg_invoice" and suffix in IMAGE_SUFFIXES:
                    return _fast_steg_local_result(
                        cfg,
                        filename=filename,
                        file_bytes=file_bytes,
                        tmp_path=tmp_path,
                        source_origin=origin,
                    )
                return _persisted_error_result(
                    cfg,
                    filename=filename,
                    file_bytes=file_bytes,
                    source_origin=origin,
                    detected_kind=detected_kind,
                    error="Pipeline local non pret: " + " ".join(blockers),
                    mode=effective_mode,
                    extraction_method=extraction_method,
                )

            if effective_mode == "medical" and suffix in IMAGE_SUFFIXES:
                return _fast_medical_ocr_result(
                    cfg,
                    filename=filename,
                    file_bytes=file_bytes,
                    tmp_path=tmp_path,
                    source_origin=origin,
                    kind="medical_local",
                    extraction_source="hybrid_local_fast_medical_ocr",
                    extra_warning=(
                        "Analyse medicale image: retour OCR structure rapide utilise pour eviter "
                        "une attente longue de Qwen/Ollama."
                    ),
                )

            try:
                kind, payload = extract_with_docling_qwen(
                    tmp_path,
                    mode=effective_mode,
                    ollama_host=ollama_host or os.getenv("OLLAMA_HOST") or "http://127.0.0.1:11434",
                    model=local_model or os.getenv("OLLAMA_MODEL") or "qwen2.5:7b-instruct",
                )
                detected_kind = LOCAL_KIND_DETECTED.get(kind, kind)
            except LocalPipelineError as exc:
                reason = f"Pipeline Docling/Qwen indisponible; fallback OCR local applique ({exc})."
                if detected_kind == "receipt":
                    return _fallback_receipt_local_result(
                        cfg,
                        filename=filename,
                        file_bytes=file_bytes,
                        tmp_path=tmp_path,
                        source_origin=origin,
                        reason=reason,
                    )
                if detected_kind == "supplier_invoice":
                    return _fallback_supplier_local_result(
                        cfg,
                        filename=filename,
                        file_bytes=file_bytes,
                        tmp_path=tmp_path,
                        source_origin=origin,
                        reason=reason,
                    )
                if detected_kind == "medical_lab_report" and suffix in IMAGE_SUFFIXES:
                    return _fast_medical_ocr_result(
                        cfg,
                        filename=filename,
                        file_bytes=file_bytes,
                        tmp_path=tmp_path,
                        source_origin=origin,
                        kind="medical_local",
                        extraction_source="hybrid_local_fast_medical_ocr",
                        extra_warning=reason,
                    )
                return _persisted_error_result(
                    cfg,
                    filename=filename,
                    file_bytes=file_bytes,
                    source_origin=origin,
                    detected_kind=detected_kind,
                    error=str(exc),
                    mode=effective_mode,
                    extraction_method=extraction_method,
                )
            except Exception as exc:
                return _persisted_error_result(
                    cfg,
                    filename=filename,
                    file_bytes=file_bytes,
                    source_origin=origin,
                    detected_kind=detected_kind,
                    error=f"{type(exc).__name__}: {exc}",
                    mode=effective_mode,
                    extraction_method=extraction_method,
                )

            payload = _normalize_document_payload_fields(kind, payload)
            if kind in {"steg_ocr", "steg_gemini", "steg_local"}:
                payload = _normalize_steg_payload_fields_from_image_path(payload, tmp_path)
            history_relative: str | None = None
            try:
                history_path = save_extraction(
                    cfg,
                    kind,
                    filename,
                    payload,
                    source_bytes=file_bytes,
                    status="ok",
                    detected_kind=detected_kind,
                )
                history_relative = str(history_path.relative_to(cfg.extraction_history_dir))
            except Exception:
                history_relative = None

            return _successful_result(
                kind=kind,
                payload=payload,
                history_relative=history_relative,
                detected_kind=detected_kind,
                source_origin=origin,
                filename=filename,
            )

        if is_receipt_mode and use_local_ocr:
            return _fallback_receipt_local_result(
                cfg,
                filename=filename,
                file_bytes=file_bytes,
                tmp_path=tmp_path,
                source_origin=origin,
                reason="OCR local classique selectionne pour ticket; extraction alternative appliquee.",
            )
        elif is_receipt_mode and not gkey:
            return _fallback_receipt_local_result(
                cfg,
                filename=filename,
                file_bytes=file_bytes,
                tmp_path=tmp_path,
                source_origin=origin,
                reason="Gemini API non configuree; fallback OCR local applique.",
            )
        elif is_receipt_mode and suffix == ".pdf":
            gemini_receipt_error = "Pour un ticket, importez une image (JPG, PNG ou TIFF), pas un PDF."
        elif is_receipt_mode:
            if gkey:
                try:
                    gemini_receipt_result = extract_receipt(
                        tmp_path,
                        api_key=gkey,
                        model=gemini_model,
                        retries=int(retries),
                        retry_delay_sec=float(retry_delay),
                    )
                    detected_kind = "receipt"
                except Exception as exc:
                    return _fallback_receipt_local_result(
                        cfg,
                        filename=filename,
                        file_bytes=file_bytes,
                        tmp_path=tmp_path,
                        source_origin=origin,
                        reason=f"Gemini ticket indisponible; fallback OCR local applique ({exc}).",
                    )
        elif effective_mode == "steg":
            if use_local_ocr:
                if suffix in IMAGE_SUFFIXES:
                    return _fast_steg_local_result(
                        cfg,
                        filename=filename,
                        file_bytes=file_bytes,
                        tmp_path=tmp_path,
                        source_origin=origin,
                        kind="steg_ocr",
                        extraction_source="ocr_fast_steg",
                    )
                routed, processing_error = _try_process_document(tmp_path, "steg", use_gemini=False)
                if routed is not None:
                    detected_kind = routed.get("doc_type") or "steg_invoice"
            elif not gkey:
                if suffix in IMAGE_SUFFIXES:
                    return _fast_steg_local_result(
                        cfg,
                        filename=filename,
                        file_bytes=file_bytes,
                        tmp_path=tmp_path,
                        source_origin=origin,
                        kind="steg_ocr",
                        extraction_source="ocr_fast_steg",
                    )
                routed, processing_error = _try_process_document(tmp_path, "steg", use_gemini=False)
                if routed is not None:
                    detected_kind = routed.get("doc_type") or "steg_invoice"
            elif suffix == ".pdf":
                processing_error = "Pour STEG avec Gemini, importez une image, pas un PDF."
            else:
                if gkey:
                    routed, processing_error = _try_process_document(
                        tmp_path,
                        "steg",
                        use_gemini=True,
                        gemini_api_key=gkey,
                        gemini_model=gemini_model,
                    )
                    if routed is not None:
                        detected_kind = routed.get("doc_type") or "steg_invoice"
        elif effective_mode == "supplier":
            detected_kind = "supplier_invoice"
            if use_local_ocr:
                return _fallback_supplier_local_result(
                    cfg,
                    filename=filename,
                    file_bytes=file_bytes,
                    tmp_path=tmp_path,
                    source_origin=origin,
                    reason="OCR local classique selectionne pour facture fournisseur; extraction alternative appliquee.",
                )
            elif not gkey:
                return _fallback_supplier_local_result(
                    cfg,
                    filename=filename,
                    file_bytes=file_bytes,
                    tmp_path=tmp_path,
                    source_origin=origin,
                    reason="Gemini API non configuree; fallback OCR local applique.",
                )
            else:
                if gkey:
                    try:
                        gemini_supplier_result = extract_supplier_invoice(
                            tmp_path,
                            gemini_api_key=gkey,
                            model=gemini_model,
                            retries=int(retries),
                            retry_delay_sec=float(retry_delay),
                        )
                    except Exception as exc:
                        return _fallback_supplier_local_result(
                            cfg,
                            filename=filename,
                            file_bytes=file_bytes,
                            tmp_path=tmp_path,
                            source_origin=origin,
                            reason=f"Gemini fournisseur indisponible; fallback OCR local applique ({exc}).",
                        )
        elif effective_mode == "auto":
            try:
                doc_kind = detect_document_type(
                    tmp_path,
                    filename_hint=filename,
                    path_hint=origin,
                )
            except Exception:
                doc_kind = "medical_lab_report"
            detected_kind = doc_kind

            if doc_kind == "steg_invoice":
                if use_local_ocr:
                    if suffix in IMAGE_SUFFIXES:
                        return _fast_steg_local_result(
                            cfg,
                            filename=filename,
                            file_bytes=file_bytes,
                            tmp_path=tmp_path,
                            source_origin=origin,
                            kind="steg_ocr",
                            extraction_source="ocr_fast_steg",
                        )
                    routed, processing_error = _try_process_document(tmp_path, "steg", use_gemini=False)
                elif not gkey:
                    if suffix in IMAGE_SUFFIXES:
                        return _fast_steg_local_result(
                            cfg,
                            filename=filename,
                            file_bytes=file_bytes,
                            tmp_path=tmp_path,
                            source_origin=origin,
                            kind="steg_ocr",
                            extraction_source="ocr_fast_steg",
                        )
                    routed, processing_error = _try_process_document(tmp_path, "steg", use_gemini=False)
                elif suffix == ".pdf":
                    processing_error = "Pour STEG avec Gemini, importez une image, pas un PDF."
                else:
                    if gkey:
                        routed, processing_error = _try_process_document(
                            tmp_path,
                            "steg",
                            use_gemini=True,
                            gemini_api_key=gkey,
                            gemini_model=gemini_model,
                        )
            elif doc_kind == "receipt":
                if use_local_ocr:
                    return _fallback_receipt_local_result(
                        cfg,
                        filename=filename,
                        file_bytes=file_bytes,
                        tmp_path=tmp_path,
                        source_origin=origin,
                        reason="Document detecte comme ticket; OCR local alternatif applique.",
                    )
                elif not gkey:
                    return _fallback_receipt_local_result(
                        cfg,
                        filename=filename,
                        file_bytes=file_bytes,
                        tmp_path=tmp_path,
                        source_origin=origin,
                        reason="Document detecte comme ticket; Gemini non configure, fallback OCR local applique.",
                    )
                elif suffix == ".pdf":
                    gemini_receipt_error = "Pour un ticket, importez une image, pas un PDF."
                else:
                    if gkey:
                        try:
                            gemini_receipt_result = extract_receipt(
                                tmp_path,
                                api_key=gkey,
                                model=gemini_model,
                                retries=int(retries),
                                retry_delay_sec=float(retry_delay),
                            )
                        except Exception as exc:
                            return _fallback_receipt_local_result(
                                cfg,
                                filename=filename,
                                file_bytes=file_bytes,
                                tmp_path=tmp_path,
                                source_origin=origin,
                                reason=f"Gemini ticket indisponible; fallback OCR local applique ({exc}).",
                            )
            elif doc_kind == "supplier_invoice":
                if use_local_ocr:
                    return _fallback_supplier_local_result(
                        cfg,
                        filename=filename,
                        file_bytes=file_bytes,
                        tmp_path=tmp_path,
                        source_origin=origin,
                        reason="Document detecte comme facture fournisseur; OCR local alternatif applique.",
                    )
                elif not gkey:
                    return _fallback_supplier_local_result(
                        cfg,
                        filename=filename,
                        file_bytes=file_bytes,
                        tmp_path=tmp_path,
                        source_origin=origin,
                        reason="Document detecte comme facture fournisseur; Gemini non configure, fallback OCR local applique.",
                    )
                else:
                    if gkey:
                        try:
                            gemini_supplier_result = extract_supplier_invoice(
                                tmp_path,
                                gemini_api_key=gkey,
                                model=gemini_model,
                                retries=int(retries),
                                retry_delay_sec=float(retry_delay),
                            )
                        except Exception as exc:
                            return _fallback_supplier_local_result(
                                cfg,
                                filename=filename,
                                file_bytes=file_bytes,
                                tmp_path=tmp_path,
                                source_origin=origin,
                                reason=f"Gemini fournisseur indisponible; fallback OCR local applique ({exc}).",
                            )
            elif use_local_ocr and suffix in IMAGE_SUFFIXES:
                return _fast_medical_ocr_result(
                    cfg,
                    filename=filename,
                    file_bytes=file_bytes,
                    tmp_path=tmp_path,
                    source_origin=origin,
                )
            elif use_local_ocr:
                routed, processing_error = _try_process_document(tmp_path, "medical", use_gemini=False)
            elif not gkey:
                if suffix in IMAGE_SUFFIXES:
                    return _fast_medical_ocr_result(
                        cfg,
                        filename=filename,
                        file_bytes=file_bytes,
                        tmp_path=tmp_path,
                        source_origin=origin,
                        extra_warning="Gemini API non configuree; fallback OCR medical local applique.",
                    )
                routed, processing_error = _try_process_document(tmp_path, "medical", use_gemini=False)
            else:
                if gkey:
                    try:
                        gemini_generic_result = extract_medical_report(
                            tmp_path,
                            api_key=gkey,
                            model=gemini_model,
                            retries=int(retries),
                            retry_delay_sec=float(retry_delay),
                        )
                    except Exception as exc:
                        if suffix in IMAGE_SUFFIXES:
                            return _fast_medical_ocr_result(
                                cfg,
                                filename=filename,
                                file_bytes=file_bytes,
                                tmp_path=tmp_path,
                                source_origin=origin,
                                extra_warning=f"Gemini medical indisponible; fallback OCR local applique ({exc}).",
                            )
                        gemini_generic_error = str(exc)
        elif effective_mode == "medical":
            detected_kind = "medical_lab_report"
            if use_local_ocr and suffix in IMAGE_SUFFIXES:
                return _fast_medical_ocr_result(
                    cfg,
                    filename=filename,
                    file_bytes=file_bytes,
                    tmp_path=tmp_path,
                    source_origin=origin,
                )
            if use_local_ocr:
                routed, processing_error = _try_process_document(tmp_path, "medical", use_gemini=False)
            elif not gkey:
                if suffix in IMAGE_SUFFIXES:
                    return _fast_medical_ocr_result(
                        cfg,
                        filename=filename,
                        file_bytes=file_bytes,
                        tmp_path=tmp_path,
                        source_origin=origin,
                        extra_warning="Gemini API non configuree; fallback OCR medical local applique.",
                    )
                routed, processing_error = _try_process_document(tmp_path, "medical", use_gemini=False)
            else:
                if gkey:
                    try:
                        gemini_generic_result = extract_medical_report(
                            tmp_path,
                            api_key=gkey,
                            model=gemini_model,
                            retries=int(retries),
                            retry_delay_sec=float(retry_delay),
                        )
                    except Exception as exc:
                        if suffix in IMAGE_SUFFIXES:
                            return _fast_medical_ocr_result(
                                cfg,
                                filename=filename,
                                file_bytes=file_bytes,
                                tmp_path=tmp_path,
                                source_origin=origin,
                                extra_warning=f"Gemini medical indisponible; fallback OCR local applique ({exc}).",
                            )
                        gemini_generic_error = str(exc)
        else:
            processing_error = f"Mode non pris en charge : {effective_mode!r}"
    finally:
        if detected_kind != "steg_invoice":
            tmp_path.unlink(missing_ok=True)

    if gemini_receipt_error:
        tmp_path.unlink(missing_ok=True)
        return _persisted_error_result(
            cfg,
            filename=filename,
            file_bytes=file_bytes,
            source_origin=origin,
            detected_kind=detected_kind,
            error=gemini_receipt_error,
            mode=effective_mode,
            extraction_method=extraction_method,
        )
    if gemini_supplier_error:
        tmp_path.unlink(missing_ok=True)
        return _persisted_error_result(
            cfg,
            filename=filename,
            file_bytes=file_bytes,
            source_origin=origin,
            detected_kind=detected_kind,
            error=gemini_supplier_error,
            mode=effective_mode,
            extraction_method=extraction_method,
        )
    if gemini_generic_error:
        tmp_path.unlink(missing_ok=True)
        return _persisted_error_result(
            cfg,
            filename=filename,
            file_bytes=file_bytes,
            source_origin=origin,
            detected_kind=detected_kind,
            error=gemini_generic_error,
            mode=effective_mode,
            extraction_method=extraction_method,
        )
    if processing_error:
        tmp_path.unlink(missing_ok=True)
        return _persisted_error_result(
            cfg,
            filename=filename,
            file_bytes=file_bytes,
            source_origin=origin,
            detected_kind=detected_kind,
            error=processing_error,
            mode=effective_mode,
            extraction_method=extraction_method,
        )

    history_relative: str | None = None
    payload: dict[str, Any]
    kind: str
    if gemini_receipt_result is not None:
        kind = "receipt"
        payload = gemini_receipt_result
    elif gemini_supplier_result is not None:
        kind = "supplier_invoice"
        payload = gemini_supplier_result
    elif gemini_generic_result is not None:
        kind = "medical_gemini"
        payload = gemini_generic_result
    elif routed is not None and routed.get("kind") == "steg":
        payload = routed["result"]
        extraction_source = str(payload.get("extraction_source") or "ocr").lower()
        kind = "steg_gemini" if extraction_source == "gemini" else "steg_ocr"
    elif routed is not None and routed.get("kind") == "medical":
        payload = routed["result"].model_dump()
        kind = "medical_ocr"
    else:
        tmp_path.unlink(missing_ok=True)
        return _persisted_error_result(
            cfg,
            filename=filename,
            file_bytes=file_bytes,
            source_origin=origin,
            detected_kind=detected_kind,
            error="Aucun resultat d'extraction.",
            mode=effective_mode,
            extraction_method=extraction_method,
        )

    payload = _normalize_document_payload_fields(kind, payload)
    if kind in {"steg_ocr", "steg_gemini", "steg_local"}:
        try:
            payload = _normalize_steg_payload_fields_from_image_path(payload, tmp_path)
        finally:
            tmp_path.unlink(missing_ok=True)
    else:
        tmp_path.unlink(missing_ok=True)
    try:
        history_path = save_extraction(
            cfg,
            kind,
            filename,
            payload,
            source_bytes=file_bytes,
            status="ok",
            detected_kind=detected_kind,
        )
        history_relative = str(history_path.relative_to(cfg.extraction_history_dir))
    except Exception:
        history_relative = None

    return _successful_result(
        kind=kind,
        payload=payload,
        history_relative=history_relative,
        detected_kind=detected_kind,
        source_origin=origin,
        filename=filename,
    )


def _timeout_message(mode: str, extraction_method: str, seconds: float) -> str:
    base = (
        f"Extraction arretee apres {int(seconds)} secondes pour eviter que l'interface reste bloquee."
    )
    if extraction_method == "local" and mode == "medical":
        return (
            base
            + " Pour une analyse medicale image, verifie qu'Ollama/Qwen est lance, "
            "ou essaie OCR local classique pour un test plus rapide."
        )
    if extraction_method == "local":
        return (
            base
            + " Le pipeline Docling + Qwen peut etre lent au premier chargement du modele. "
            "Reessaie avec OCR local classique pour un test rapide."
        )
    return base


def _extraction_process_target(connection: Any, cfg: AppConfig, kwargs: dict[str, Any]) -> None:
    """Run one extraction in an isolated process so a timeout can terminate it safely."""
    try:
        connection.send(("ok", process_single_document(cfg, **kwargs)))
    except BaseException as exc:
        connection.send(("error", f"{type(exc).__name__}: {exc}"))
    finally:
        connection.close()


def _run_process_with_timeout(
    target: Any,
    args: tuple[Any, ...],
    timeout_seconds: float,
) -> tuple[str, Any]:
    """Execute a picklable worker and guarantee it is gone before returning."""
    context = multiprocessing.get_context("spawn")
    parent_connection, child_connection = context.Pipe(duplex=False)
    process = context.Process(target=target, args=(child_connection, *args), daemon=False)
    process.start()
    child_connection.close()
    if not parent_connection.poll(timeout_seconds):
        process.terminate()
        process.join(5)
        if process.is_alive():
            process.kill()
            process.join(5)
        parent_connection.close()
        return "timeout", None
    try:
        outcome = parent_connection.recv()
    except EOFError:
        outcome = ("error", f"Extraction worker exited with code {process.exitcode}.")
    finally:
        parent_connection.close()
        process.join(5)
    return outcome


def _process_single_document_with_timeout(
    cfg: AppConfig,
    *,
    file_item: dict[str, Any],
    mode: str,
    extraction_method: str,
    gemini_api_key: str | None,
    gemini_model: str | None,
    ollama_host: str | None,
    local_model: str | None,
    retries: int,
    retry_delay: float,
) -> dict[str, Any]:
    filename = str(file_item["name"])
    file_bytes = bytes(file_item["bytes"])
    origin = str(file_item.get("origin") or "upload")
    timeout_seconds = cfg.extraction_timeout_seconds
    worker_temp_dir = tempfile.mkdtemp(prefix="docia-extract-")
    kwargs = {
        "filename": filename,
        "file_bytes": file_bytes,
        "origin": origin,
        "mode": mode,
        "extraction_method": extraction_method,
        "gemini_api_key": gemini_api_key,
        "gemini_model": gemini_model or cfg.gemini_model,
        "ollama_host": ollama_host,
        "local_model": local_model,
        "retries": retries,
        "retry_delay": retry_delay,
        "temp_dir": worker_temp_dir,
    }
    try:
        outcome, value = _run_process_with_timeout(
            _extraction_process_target,
            (cfg, kwargs),
            timeout_seconds,
        )
    finally:
        shutil.rmtree(worker_temp_dir, ignore_errors=True)
    if outcome == "ok":
        return value
    if outcome == "timeout":
        effective_mode = "auto" if origin != "upload" else mode
        return _persisted_error_result(
            cfg,
            filename=filename,
            file_bytes=file_bytes,
            source_origin=origin,
            detected_kind=MODE_DETECTED_KIND.get(effective_mode, "medical_lab_report"),
            error=_timeout_message(effective_mode, extraction_method, timeout_seconds),
            mode=effective_mode,
            extraction_method=extraction_method,
        )
    effective_mode = "auto" if origin != "upload" else mode
    return _persisted_error_result(
        cfg,
        filename=filename,
        file_bytes=file_bytes,
        source_origin=origin,
        detected_kind=MODE_DETECTED_KIND.get(effective_mode, "medical_lab_report"),
        error=str(value),
        mode=effective_mode,
        extraction_method=extraction_method,
    )


def process_batch(
    cfg: AppConfig,
    *,
    files: list[dict[str, Any]],
    mode: str,
    extraction_method: str,
    gemini_api_key: str | None,
    gemini_model: str | None,
    ollama_host: str | None,
    local_model: str | None,
    retries: int,
    retry_delay: float,
) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    ok_count = 0
    error_count = 0
    for file_item in files:
        result = _process_single_document_with_timeout(
            cfg,
            file_item=file_item,
            mode=mode,
            extraction_method=extraction_method,
            gemini_api_key=gemini_api_key,
            gemini_model=gemini_model,
            ollama_host=ollama_host,
            local_model=local_model,
            retries=retries,
            retry_delay=retry_delay,
        )
        items.append(result)
        if result["status"] == "ok":
            ok_count += 1
        else:
            error_count += 1

    last_success = next((item for item in reversed(items) if item["status"] == "ok"), None)
    return {
        "summary": {
            "total": len(items),
            "okCount": ok_count,
            "errorCount": error_count,
            "mode": mode,
            "method": extraction_method,
        },
        "items": items,
        "latestSuccess": last_success,
    }


def _default_ollama_host() -> str:
    return get_config().ollama_host


def _default_local_model() -> str:
    return get_config().ollama_model


def _docling_available() -> bool:
    return importlib.util.find_spec("docling") is not None


def _paddleocr_available() -> bool:
    return importlib.util.find_spec("paddleocr") is not None


def _tesseract_available(configured_path: str | None) -> bool:
    if configured_path and Path(configured_path).is_file():
        return True
    return shutil.which("tesseract") is not None


def _ollama_available(host: str | None = None) -> bool:
    target = (host or _default_ollama_host()).rstrip("/")
    request = urllib.request.Request(f"{target}/api/tags", method="GET")
    try:
        with urllib.request.urlopen(request, timeout=1.5) as response:
            return 200 <= response.status < 300
    except (OSError, urllib.error.URLError):
        return False


def build_meta_payload(cfg: AppConfig) -> dict[str, Any]:
    docling_ready = _docling_available()
    paddleocr_ready = _paddleocr_available()
    ollama_ready = _ollama_available(cfg.ollama_host)
    return {
        "appName": "DocIA",
        "apiVersion": "v2",
        "themes": THEME_OPTIONS,
        "modes": MODE_OPTIONS,
        "methods": METHOD_OPTIONS,
        "localPipeline": {
            "doclingAvailable": docling_ready,
            "paddleocrAvailable": paddleocr_ready,
            "ollamaAvailable": ollama_ready,
            "available": docling_ready and paddleocr_ready and ollama_ready,
        },
        "geminiConfigured": bool(cfg.gemini_api_key or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")),
        "auth": {
            "enabled": cfg.auth_enabled,
            "loginUrl": "/api/auth/login",
            "meUrl": "/api/auth/me",
            "tokenType": "bearer",
            "ttlMinutes": cfg.auth_token_ttl_minutes,
            "usernameHint": cfg.auth_username if cfg.auth_enabled else None,
        },
        "navigation": [
            {"href": "/dashboard", "label": "Tableau de bord"},
            {"href": "/documents", "label": "Documents"},
            {"href": "/extractions", "label": "Extractions"},
            {"href": "/history", "label": "Historiques"},
            {"href": "/settings", "label": "Parametres"},
        ],
    }


def build_dashboard_payload(cfg: AppConfig) -> dict[str, Any]:
    entries = [entry for entry in list_history_entries(cfg) if _history_entry_is_displayable(entry)]
    summaries = [history_summary(entry, cfg) for entry in entries]
    total = len(summaries)
    ok_count = sum(1 for item in summaries if item["status"] == "ok")
    error_count = total - ok_count
    warning_count = sum(int(item["warningsCount"]) for item in summaries)
    success_rate = round((ok_count / total) * 100, 2) if total else 0.0
    warning_rate = round((warning_count / total), 2) if total else 0.0
    quality_values = [
        float(item["qualityScore"])
        for item in summaries
        if isinstance(item.get("qualityScore"), (int, float))
    ]
    ai_health = round(sum(quality_values) / len(quality_values), 2) if quality_values else 0.0

    by_kind: dict[str, int] = {}
    by_method: dict[str, int] = {}
    by_family: dict[str, int] = {}
    by_status: dict[str, int] = {}
    by_day: dict[str, int] = {}
    series_by_kind: dict[str, dict[str, int]] = {}

    for item in summaries:
        by_kind[item["kindLabel"]] = by_kind.get(item["kindLabel"], 0) + 1
        by_method[item["method"]] = by_method.get(item["method"], 0) + 1
        by_family[item["family"]] = by_family.get(item["family"], 0) + 1
        status_label = "Succes" if item["status"] == "ok" else "Erreur"
        by_status[status_label] = by_status.get(status_label, 0) + 1
        if item["savedDate"]:
            by_day[item["savedDate"]] = by_day.get(item["savedDate"], 0) + 1
            bucket = series_by_kind.setdefault(item["kindLabel"], {})
            bucket[item["savedDate"]] = bucket.get(item["savedDate"], 0) + 1

    daily_volume = [
        {"date": key, "documents": value}
        for key, value in sorted(by_day.items(), key=lambda pair: pair[0])
    ]
    palette = ["#7c5cff", "#4cc38a", "#ffb340", "#5987ff", "#ef6a6a"]
    all_dates = [item["date"] for item in daily_volume]
    sorted_series_labels = sorted(
        series_by_kind,
        key=lambda label: sum(series_by_kind[label].values()),
        reverse=True,
    )
    trend_series = []
    for index, label in enumerate(sorted_series_labels[:5]):
        values = series_by_kind[label]
        trend_series.append(
            {
                "label": label,
                "color": palette[index % len(palette)],
                "points": [
                    {"date": day, "value": int(values.get(day, 0))}
                    for day in all_dates
                ],
            }
        )
    latest_detail = build_history_detail(cfg, entries[0]) if entries else None

    gemini_count = by_method.get("Gemini API", 0)
    local_count = by_method.get("Docling + Qwen2.5 local", 0)
    insights = [
        f"{success_rate:.1f}% de succes global sur l'historique courant.",
        f"Score qualite moyen des champs extraits : {ai_health:.1f}%.",
        f"{local_count} document(s) traites en local Docling + Qwen, {gemini_count} via Gemini et {by_method.get('OCR local', 0)} en OCR local.",
    ]

    return {
        "overview": {
            "totalDocuments": total,
            "successCount": ok_count,
            "errorCount": error_count,
            "successRate": success_rate,
            "warningCount": warning_count,
            "warningRate": warning_rate,
            "aiHealthScore": ai_health,
        },
        "recentActivity": summaries[:8],
        "latestResult": latest_detail,
        "distributions": {
            "byKind": [{"label": label, "value": value} for label, value in by_kind.items()],
            "byMethod": [{"label": label, "value": value} for label, value in by_method.items()],
            "byFamily": [{"label": label, "value": value} for label, value in by_family.items()],
            "byStatus": [{"label": label, "value": value} for label, value in by_status.items()],
            "dailyVolume": daily_volume,
            "trendSeries": trend_series,
        },
        "insights": insights,
    }


def build_history_list_payload(
    cfg: AppConfig,
    *,
    kind: str = "",
    search: str = "",
    type_query: str = "",
    date_from: date | None = None,
    date_to: date | None = None,
    page: int = 1,
    page_size: int = 12,
) -> dict[str, Any]:
    raw_entries = list_history_entries(cfg)
    entries = filter_history_entries(
        raw_entries,
        kind=kind,
        search=search,
        type_query=type_query,
        date_from=date_from,
        date_to=date_to,
    )
    total = len(entries)
    page_size = max(1, min(page_size, 50))
    total_pages = max(1, (total + page_size - 1) // page_size)
    page = max(1, min(page, total_pages))
    start = (page - 1) * page_size
    visible = entries[start:start + page_size]
    kinds = sorted(
        {
            str(entry.get("kind") or "")
            for entry in raw_entries
            if _history_entry_is_displayable(entry)
        }
    )
    available_dates = sorted(
        {
            saved
            for entry in raw_entries
            if _history_entry_is_displayable(entry)
            if (saved := entry_saved_date(entry)) is not None
        },
        reverse=True,
    )
    return {
        "items": [history_summary(entry, cfg) for entry in visible],
        "filters": {
            "kind": kind,
            "search": search,
            "typeQuery": type_query,
            "dateFrom": date_from.isoformat() if date_from else None,
            "dateTo": date_to.isoformat() if date_to else None,
            "availableKinds": [{"value": value, "label": kind_label(value)} for value in kinds],
            "availableDates": [
                {"value": value.isoformat(), "label": format_date_fr(value.isoformat()) or value.isoformat()}
                for value in available_dates
            ],
        },
        "pagination": {
            "page": page,
            "pageSize": page_size,
            "total": total,
            "totalPages": total_pages,
        },
    }


MONTHS_FR = {
    1: "Jan",
    2: "Fev",
    3: "Mars",
    4: "Avr",
    5: "Mai",
    6: "Juin",
    7: "Juil",
    8: "Aout",
    9: "Sept",
    10: "Oct",
    11: "Nov",
    12: "Dec",
}


def format_date_fr(raw: str | None) -> str | None:
    if not raw:
        return None
    try:
        parsed = date.fromisoformat(raw)
    except ValueError:
        return raw
    return f"{parsed.day:02d} {MONTHS_FR.get(parsed.month, parsed.month)} {parsed.year}"


def build_models_payload(cfg: AppConfig) -> dict[str, Any]:
    entries = list_history_entries(cfg)
    summaries = [history_summary(entry, cfg) for entry in entries]
    by_kind: dict[str, int] = {}
    for item in summaries:
        by_kind[item["kindLabel"]] = by_kind.get(item["kindLabel"], 0) + 1

    def latest_used_for(method_name: str) -> str | None:
        for item in summaries:
            if item["method"] == method_name:
                return format_date_fr(item["savedDate"])
        return None

    tesseract_path = cfg.tesseract_cmd or ""
    gemini_available = bool(cfg.gemini_api_key or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"))
    ocr_available = _tesseract_available(tesseract_path)
    ollama_host = _default_ollama_host()
    local_model = _default_local_model()
    docling_available = _docling_available()
    paddleocr_available = _paddleocr_available()
    ollama_available = _ollama_available(ollama_host)
    local_available = docling_available and paddleocr_available and ollama_available
    return {
        "runtime": {
            "geminiModel": cfg.gemini_model,
            "geminiConfigured": gemini_available,
            "tesseractConfigured": ocr_available,
            "tesseractPath": tesseract_path,
            "ollamaHost": ollama_host,
            "localModel": local_model,
            "doclingConfigured": docling_available,
            "paddleocrConfigured": paddleocr_available,
            "ollamaConfigured": ollama_available,
        },
        "models": [
            {
                "id": "docling-qwen-local",
                "name": "Pipeline IA local",
                "provider": "Docling / PaddleOCR / Ollama",
                "version": local_model,
                "precision": None,
                "lastUsed": latest_used_for("Pipeline IA local"),
                "status": "available" if local_available else "limited",
                "available": local_available,
                "toggleable": True,
                "methodValue": "local",
                "description": "Moteur principal : pretraitement, Docling vers Markdown, controle qualite, fallback PaddleOCR si besoin, puis JSON extrait par Qwen2.5 via Ollama.",
                "reason": None
                if local_available
                else "Installez Docling, PaddleOCR et lancez Ollama avec le modele Qwen2.5 pour activer le pipeline complet.",
            },
            {
                "id": "gemini-api",
                "name": "Gemini API",
                "provider": "Google",
                "version": cfg.gemini_model,
                "precision": None,
                "lastUsed": latest_used_for("Gemini API"),
                "status": "available" if gemini_available else "limited",
                "available": gemini_available,
                "toggleable": True,
                "methodValue": "gemini",
                "description": "Vision + extraction structuree pour medical, ticket, fournisseur et STEG.",
                "reason": None if gemini_available else "Ajoutez GEMINI_API_KEY dans le .env du backend.",
            },
            {
                "id": "ocr-local",
                "name": "OCR local",
                "provider": "Tesseract / EasyOCR",
                "version": "v5.x",
                "precision": None,
                "lastUsed": latest_used_for("OCR local classique"),
                "status": "available" if ocr_available else "limited",
                "available": ocr_available,
                "toggleable": True,
                "methodValue": "ocr",
                "description": "OCR local hors Qwen pour comparer ou depanner.",
                "reason": None if ocr_available else "Tesseract n'est pas configure sur cette machine.",
            },
        ],
        "coverage": [{"label": label, "value": value} for label, value in by_kind.items()],
    }
