"""Validation Pydantic, normalisation et scores pour les sorties Gemini « page simple »."""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from src.models.schemas import (
    GeminiMedicalAnalysisRow,
    GeminiMedicalPagePayload,
    ProcessingWarning,
    ReceiptGeminiPayload,
    StegGeminiPayload,
    SupplierInvoiceGeminiPayload,
)


def _w(code: str, message: str, context: str | None = None) -> dict[str, Any]:
    return ProcessingWarning(code=code, message=message, context=context).model_dump()


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def normalize_medical_gemini_page(raw: Any) -> dict[str, Any]:
    """
    Valide la charge utile médicale Gemini, normalise les types et ajoute
    ``warnings`` (liste de dicts) et ``extraction_quality`` (0..1).
    """
    if not isinstance(raw, dict):
        raw = {}
    warnings: list[dict[str, Any]] = []
    try:
        m = GeminiMedicalPagePayload.model_validate(raw)
    except ValidationError as exc:
        warnings.append(
            _w(
                "SCHEMA_VALIDATION",
                "Le JSON du modele ne respectait pas entierement le schema attendu ; champs corriges ou ignores.",
                str(exc)[:500],
            )
        )
        safe_rows: list[GeminiMedicalAnalysisRow] = []
        if isinstance(raw.get("analyses"), list):
            for row in raw["analyses"]:
                if not isinstance(row, dict):
                    continue
                try:
                    safe_rows.append(GeminiMedicalAnalysisRow.model_validate(row))
                except ValidationError:
                    continue

        def _hdr_field(key: str) -> str | None:
            v = raw.get(key)
            if v is None:
                return None
            s = str(v).strip()
            return s or None

        m = GeminiMedicalPagePayload(
            patient_name=_hdr_field("patient_name"),
            doctor_name=_hdr_field("doctor_name"),
            date=_hdr_field("date"),
            analyses=safe_rows,
        )

    analyses_out: list[dict[str, Any]] = []
    partial_rows = 0
    for row in m.analyses:
        d = row.model_dump()
        analyses_out.append(d)
        tn, val = d.get("test_name"), d.get("value")
        if not tn or not val:
            partial_rows += 1

    if not m.patient_name:
        warnings.append(_w("MISSING_PATIENT", "Nom du patient absent ou illisible."))
    if not m.doctor_name:
        warnings.append(_w("MISSING_DOCTOR", "Nom du medecin absent ou illisible."))
    if not m.date:
        warnings.append(_w("MISSING_DATE", "Date principale absente ou illisible."))
    if not analyses_out:
        warnings.append(_w("NO_ANALYSES", "Aucune ligne d'analyse exploitable dans le JSON."))
    elif partial_rows:
        warnings.append(
            _w(
                "PARTIAL_ANALYSIS_ROWS",
                f"{partial_rows} ligne(s) d'analyse sans nom ou sans valeur lisible.",
            )
        )

    n = len(analyses_out)
    complete = sum(
        1
        for a in analyses_out
        if (a.get("test_name") or "").strip() and (a.get("value") or "").strip()
    )
    q = 0.0
    q += 0.18 if m.patient_name else 0.0
    q += 0.12 if m.doctor_name else 0.0
    q += 0.12 if m.date else 0.0
    if n:
        q += 0.58 * (complete / n)
    else:
        q += 0.0

    quality = _clamp01(q)
    if warnings and quality > 0.85:
        quality = _clamp01(quality - 0.08 * min(len(warnings), 4))

    out: dict[str, Any] = {
        "patient_name": m.patient_name,
        "doctor_name": m.doctor_name,
        "date": m.date,
        "analyses": analyses_out,
        "warnings": warnings,
        "extraction_quality": round(quality, 3),
        "extraction_source": "gemini",
    }
    return out


def normalize_receipt_gemini(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raw = {}
    warnings: list[dict[str, Any]] = []
    try:
        r = ReceiptGeminiPayload.model_validate(raw)
    except ValidationError as exc:
        warnings.append(
            _w(
                "SCHEMA_VALIDATION",
                "JSON ticket partiellement corrige pour correspondre au schema.",
                str(exc)[:500],
            )
        )
        r = ReceiptGeminiPayload.model_validate(
            {
                "store_name": raw.get("store_name"),
                "date": raw.get("date"),
                "time": raw.get("time"),
                "ticket_number": raw.get("ticket_number"),
                "currency": raw.get("currency"),
                "items": raw.get("items") if isinstance(raw.get("items"), list) else [],
                "total": raw.get("total"),
                "payment_method": raw.get("payment_method"),
            }
        )

    items_out = [it.model_dump() for it in r.items]
    if not r.store_name:
        warnings.append(_w("MISSING_STORE", "Nom du magasin absent ou illisible."))
    if not r.total:
        warnings.append(_w("MISSING_TOTAL", "Total absent ou illisible."))
    if not items_out:
        warnings.append(_w("NO_ITEMS", "Aucune ligne article dans le ticket."))

    described = sum(1 for it in items_out if (it.get("description") or "").strip())
    n_it = len(items_out)
    q = 0.0
    q += 0.22 if r.store_name else 0.0
    q += 0.18 if r.date or r.time else 0.0
    q += 0.2 if r.total else 0.0
    q += 0.15 if r.currency else 0.0
    if n_it:
        q += 0.25 * (described / n_it)
    quality = _clamp01(q)
    if warnings and quality > 0.9:
        quality = _clamp01(quality - 0.06 * min(len(warnings), 3))

    return {
        "store_name": r.store_name,
        "date": r.date,
        "time": r.time,
        "ticket_number": r.ticket_number,
        "currency": r.currency,
        "items": items_out,
        "total": r.total,
        "payment_method": r.payment_method,
        "warnings": warnings,
        "extraction_quality": round(quality, 3),
        "extraction_source": "gemini",
    }


def normalize_steg_gemini_core(raw: Any) -> dict[str, Any]:
    """Valide les champs STEG (sans ``file_name``). Ajoute warnings et extraction_quality."""
    if not isinstance(raw, dict):
        raw = {}
    core = {k: v for k, v in raw.items() if k not in ("file_name", "extraction_source")}
    warnings: list[dict[str, Any]] = []
    try:
        s = StegGeminiPayload.model_validate(core)
    except ValidationError as exc:
        warnings.append(
            _w(
                "SCHEMA_VALIDATION",
                "Champs facture STEG partiellement recuperes.",
                str(exc)[:500],
            )
        )
        s = StegGeminiPayload.model_validate(
            {
                "reference": core.get("reference"),
                "montant_a_payer": core.get("montant_a_payer"),
                "date_limite_paiement": core.get("date_limite_paiement"),
                "periode_du": core.get("periode_du"),
                "periode_au": core.get("periode_au"),
                "coupon_reference_raw": core.get("coupon_reference_raw"),
                "coupon_montant": core.get("coupon_montant"),
                "confidence_note": core.get("confidence_note"),
            }
        )

    if not s.reference:
        warnings.append(_w("MISSING_REFERENCE", "Reference client absente ou illisible."))
    if not s.montant_a_payer:
        warnings.append(_w("MISSING_AMOUNT", "Montant a payer absent ou illisible."))
    if not s.date_limite_paiement:
        warnings.append(_w("MISSING_DUE_DATE", "Date limite de paiement absente ou illisible."))

    note = (s.confidence_note or "").strip().lower()
    if note == "high":
        base = 0.88
    elif note == "medium":
        base = 0.62
    elif note == "low":
        base = 0.38
    else:
        base = 0.52
        if not note:
            warnings.append(_w("MISSING_CONFIDENCE_NOTE", "Le modele n'a pas indique de niveau de confiance."))

    filled = sum(bool(x) for x in (s.reference, s.montant_a_payer, s.date_limite_paiement, s.periode_du, s.periode_au))
    q = base * (0.55 + 0.09 * filled)
    quality = _clamp01(q)
    if warnings:
        quality = _clamp01(quality - 0.05 * min(len(warnings), 4))

    out = s.model_dump()
    out["warnings"] = warnings
    out["extraction_quality"] = round(quality, 3)
    out["extraction_source"] = str(raw.get("extraction_source") or "gemini")
    return out


def _coerce_supplier_invoice_dict(raw: dict[str, Any]) -> dict[str, Any]:
    """Reconstruction tolérante avant validation Pydantic."""
    seller = raw.get("seller") if isinstance(raw.get("seller"), dict) else {}
    client = raw.get("client") if isinstance(raw.get("client"), dict) else {}
    summary = raw.get("summary") if isinstance(raw.get("summary"), dict) else {}
    items = raw.get("items") if isinstance(raw.get("items"), list) else []
    items_d = [x for x in items if isinstance(x, dict)]
    return {
        "document_type": raw.get("document_type"),
        "invoice_number": raw.get("invoice_number"),
        "invoice_date": raw.get("invoice_date"),
        "due_date": raw.get("due_date"),
        "currency": raw.get("currency"),
        "seller": seller,
        "client": client,
        "items": items_d,
        "summary": summary,
        "confidence": raw.get("confidence"),
        "missing_fields": raw.get("missing_fields"),
        "raw_notes": raw.get("raw_notes"),
    }


def normalize_supplier_invoice_gemini(
    raw: Any,
    *,
    ocr_meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Valide la charge utile facture fournisseur, normalise et ajoute warnings / extraction_quality."""
    if not isinstance(raw, dict):
        raw = {}
    warnings: list[dict[str, Any]] = []
    try:
        m = SupplierInvoiceGeminiPayload.model_validate(raw)
    except ValidationError as exc:
        warnings.append(
            _w(
                "SCHEMA_VALIDATION",
                "JSON facture fournisseur partiellement corrige pour correspondre au schema.",
                str(exc)[:500],
            )
        )
        try:
            m = SupplierInvoiceGeminiPayload.model_validate(_coerce_supplier_invoice_dict(raw))
        except ValidationError:
            m = SupplierInvoiceGeminiPayload.model_validate(_coerce_supplier_invoice_dict({}))

    seller_d = m.seller.model_dump()
    client_d = m.client.model_dump()
    summary_d = m.summary.model_dump()
    items_out = [it.model_dump() for it in m.items]

    if not m.invoice_number:
        warnings.append(_w("MISSING_INVOICE_NUMBER", "Numero de facture absent ou illisible."))
    if not m.invoice_date:
        warnings.append(_w("MISSING_INVOICE_DATE", "Date de facture absente ou illisible."))
    if not (seller_d.get("name") or "").strip():
        warnings.append(_w("MISSING_SELLER", "Nom du vendeur / fournisseur absent ou illisible."))
    if not (summary_d.get("total_amount") or "").strip() and not (summary_d.get("amount_due") or "").strip():
        warnings.append(_w("MISSING_TOTAL", "Total / montant du absent ou illisible."))
    if not items_out:
        warnings.append(_w("NO_LINE_ITEMS", "Aucune ligne article detectee dans le JSON."))

    filled = 0.0
    if m.invoice_number:
        filled += 1
    if m.invoice_date:
        filled += 1
    if m.due_date:
        filled += 0.5
    if m.currency:
        filled += 0.5
    if (seller_d.get("name") or "").strip():
        filled += 1
    if (client_d.get("name") or "").strip():
        filled += 0.7
    if (seller_d.get("tax_id") or "").strip() or (client_d.get("tax_id") or "").strip():
        filled += 0.4
    if (summary_d.get("total_amount") or "").strip() or (summary_d.get("amount_due") or "").strip():
        filled += 1.2
    if (summary_d.get("tax_total") or "").strip():
        filled += 0.4
    n_it = len(items_out)
    if n_it:
        ok_lines = sum(1 for it in items_out if (it.get("description") or "").strip())
        filled += 1.5 * (ok_lines / n_it)

    quality = _clamp01(filled / 8.2)
    if warnings and quality > 0.88:
        quality = _clamp01(quality - 0.06 * min(len(warnings), 4))

    rtl_ratio = None
    if isinstance(ocr_meta, dict) and "rtl_ratio" in ocr_meta:
        try:
            rtl_ratio = float(ocr_meta["rtl_ratio"])
        except (TypeError, ValueError):
            rtl_ratio = None

    out: dict[str, Any] = {
        "document_type": m.document_type or "supplier_invoice",
        "invoice_number": m.invoice_number,
        "invoice_date": m.invoice_date,
        "due_date": m.due_date,
        "currency": m.currency,
        "seller": seller_d,
        "client": client_d,
        "items": items_out,
        "summary": summary_d,
        "confidence": m.confidence,
        "missing_fields": list(m.missing_fields),
        "raw_notes": m.raw_notes,
        "warnings": warnings,
        "extraction_quality": round(quality, 3),
        "extraction_source": "gemini",
    }
    if rtl_ratio is not None:
        out["ocr_rtl_text_ratio"] = rtl_ratio
    return out


def enrich_steg_router_result(result: dict[str, Any]) -> dict[str, Any]:
    """
    Enrichit un dict STEG retourne par le routeur (Gemini deja normalise en amont, ou OCR).
    Pour l'OCR : ajoute warnings / extraction_quality a partir des champs presents.
    """
    if not isinstance(result, dict):
        return result
    src = str(result.get("extraction_source") or "ocr").lower()
    if src == "gemini":
        merged = dict(result)
        if "extraction_quality" not in merged or "warnings" not in merged:
            core = normalize_steg_gemini_core(result)
            for k, v in core.items():
                if k == "file_name":
                    continue
                merged[k] = v
        return merged

    warnings: list[dict[str, Any]] = []
    if not result.get("reference"):
        warnings.append(_w("MISSING_REFERENCE", "Reference client non detectee (OCR)."))
    if not result.get("montant_a_payer"):
        warnings.append(_w("MISSING_AMOUNT", "Montant a payer non detecte (OCR)."))

    note = str(result.get("confidence_note") or "").strip().lower()
    if note == "high":
        base = 0.78
    elif note == "medium":
        base = 0.55
    elif note == "low":
        base = 0.38
        warnings.append(_w("LOW_OCR_CONFIDENCE", "Indice de confiance OCR faible : verifier les montants et dates."))
    else:
        base = 0.48
    filled = sum(
        bool(result.get(k))
        for k in ("reference", "montant_a_payer", "date_limite_paiement", "periode_du", "periode_au")
    )
    quality = _clamp01(base + 0.08 * filled)
    if warnings and quality > 0.82:
        quality = _clamp01(quality - 0.06 * min(len(warnings), 3))

    out = dict(result)
    out["warnings"] = warnings
    out["extraction_quality"] = round(quality, 3)
    return out
