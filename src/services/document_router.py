from __future__ import annotations

import os
from pathlib import Path
from typing import Dict

from src.extraction.steg_invoice_extractor import configure_tesseract, extract_fields_from_invoice
from src.services.gemini_payload_normalize import enrich_steg_router_result
from src.services.medical_pipeline import process_medical_file
from src.services.supplier_invoice_ocr import build_document_router_text


def _weighted_supplier_invoice_score(txt: str) -> int:
    """Score facture fournisseur B2B (FR/EN/AR) — indépendant d'une mise en page fixe."""
    strong = (
        "invoice no",
        "invoice number",
        "invoice #",
        "credit note",
        "facture n",
        "n° facture",
        "numero facture",
        "seller",
        "supplier",
        "fournisseur",
        "vendor",
        "bill to",
        "sold to",
        "ship to",
        "vat",
        " tva",
        "tva ",
        "iban",
        "swift",
        "tax id",
        "due date",
        "amount due",
        "balance due",
        "net price",
        "gross",
        "subtotal",
        "total ttc",
        "montant ttc",
        "ht ",
        " ht",
        "رقم الفاتورة",
        "فاتورة",
        "المورد",
        "البائع",
        "العميل",
        "الحريف",
        "الضريبة",
        "الإجمالي",
        "المبلغ",
        "تاريخ الإصدار",
        "ضريبة القيمة المضافة",
        "الأداء على القيمة المضافة",
    )
    weak = (
        "invoice",
        "facture",
        "buyer",
        "client",
        "customer",
        "total",
        "tax",
        "amount",
        "quantity",
        "qty",
        "unit",
        "description",
        "remise",
        "discount",
        "shipping",
        "freight",
        "payment terms",
        "po ",
        "purchase order",
        "تاريخ",
    )
    s = 0
    for k in strong:
        if k in txt:
            s += 2
    for k in weak:
        if k in txt:
            s += 1
    return s


def _supplier_invoice_anchor(txt: str) -> bool:
    return any(
        a in txt
        for a in (
            "invoice",
            "facture",
            "فاتورة",
            "رقم الفاتورة",
            "seller",
            "supplier",
            "fournisseur",
            "البائع",
            "المورد",
        )
    )


def _count_hits(txt: str, keys: tuple[str, ...]) -> int:
    return sum(1 for k in keys if k in txt)


def _weighted_receipt_score(txt: str) -> int:
    """Score ticket : mots forts pondérés + liste large (OCR bruité)."""
    strong = (
        "merci",
        "tva",
        "ttc",
        "t.t.c",
        "reçu",
        "recu",
        "ticket",
        "caisse",
        "paiement",
        "payment",
        "visa",
        "mastercard",
        "carte bancaire",
        "terminal",
        "tpe",
        "transaction",
        "sous-total",
        "sous total",
        "subtotal",
        "remise",
        "discount",
        "articles",
        "quantité",
        "quantite",
        "qty",
        "espèces",
        "especes",
        "rendu",
        "monnaie",
        "bienvenue",
        "tnd",
        "dinars",
        "net à payer",
        "net a payer",
        "total tnd",
        "total dt",
        "total d.t",
    )
    weak = (
        "magasin",
        "store",
        "checkout",
        "caissier",
        "vendeur",
        "monoprix",
        "carrefour",
        "geant",
        "géant",
        "zara",
        "achat",
        "courses",
        "euro",
        "eur ",
        " eur",
    )
    s = 0
    for k in strong:
        if k in txt:
            s += 2
    for k in weak:
        if k in txt:
            s += 1
    return s


def _weighted_steg_score(txt: str) -> int:
    """Score STEG : mots forts + indices de facture d'electricite (OCR bruité)."""
    strong = (
        "steg",
        "steg tunisie",
        "facture",
        "facture steg",
        "reference",
        "référence",
        "ref client",
        "ref. client",
        "priere de payer",
        "prière de payer",
        "montant a payer",
        "montant à payer",
        "date limite",
        "date limite paiement",
        "consommation kwh",
        "kwh",
        "kw/h",
        "compteur",
        "abonne",
        "abonné",
        "energie",
        "énergie",
        "tranche",
        "tarif",
        "tnd",
        "dt",
        "الستاغ",
        "الشركة التونسية للكهرباء",
        "الرجاء",
    )
    weak = (
        "periode du",
        "période du",
        "periode au",
        "période au",
        "coupon",
        "echeance",
        "échéance",
        "client",
        "code client",
        "index",
        "ancien index",
        "nouvel index",
    )
    s = 0
    for k in strong:
        if k in txt:
            s += 2
    for k in weak:
        if k in txt:
            s += 1
    return s


def detect_document_type(
    file_path: Path,
    *,
    filename_hint: str | None = None,
    path_hint: str | None = None,
) -> str:
    """
    Indication heuristique du type de document (nom de fichier + OCR / texte PDF léger).

    Retourne l'un de : ``steg_invoice``, ``receipt``, ``supplier_invoice``, ``medical_lab_report``.
    """
    name = (filename_hint or file_path.name).lower()
    combined_path_hint = " ".join(
        part
        for part in (str(file_path), filename_hint or "", path_hint or "")
        if part
    )
    path_hint = combined_path_hint.replace("\\", "/").lower()
    if "steg" in name or any(
        key in path_hint for key in ("/steg_", "/steg/", "/electricite/")
    ):
        return "steg_invoice"
    supplier_name_hints = (
        "supplier_invoice",
        "facture_fournisseur",
        "fournisseur",
        "supplier",
        "vendor_invoice",
        "purchase_invoice",
    )
    if any(k in name for k in supplier_name_hints) or "supplier_invoice" in path_hint:
        return "supplier_invoice"
    if "invoice" in name and not any(
        x in name for x in ("receipt", "ticket", "caisse", "recu", "reçu")
    ):
        return "supplier_invoice"
    medical_name_hint = any(k in name for k in ["analyse", "labo", "medical", "médical"])
    receipt_name_keys = (
        "ticket",
        "caisse",
        "receipt",
        "recu",
        "reçu",
        "ticket_caisse",
        "ticket-caisse",
        "ticket caisse",
        "achat",
        "courses",
        "shopping",
    )
    if any(k in name for k in receipt_name_keys) or any(
        key in path_hint for key in ("/ticketscasse/", "/receipt/", "/receipt_test/")
    ):
        return "receipt"
    if medical_name_hint or any(key in path_hint for key in ("/medical/", "/analyse_medical/")):
        return "medical_lab_report"

    suffix = file_path.suffix.lower()
    if suffix not in {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".pdf"}:
        return "medical_lab_report"

    try:
        txt = build_document_router_text(file_path)
    except Exception:
        txt = ""

    if not txt.strip():
        if medical_name_hint:
            return "medical_lab_report"
        return "medical_lab_report"

    steg_keys = (
        "steg",
        "reference",
        "référence",
        "montant a payer",
        "montant à payer",
        "priere de payer",
        "prière de payer",
        "consommation kwh",
        "kwh",
        "compteur",
        "abonne",
        "abonné",
        "date limite",
        "الرجاء",
    )
    med_keys = (
        "laboratoire",
        "laboratoire ",
        " hémoglob",
        "hemoglob",
        "glycem",
        "glycém",
        "tsh",
        "vitamine",
        " vn ",
        "valeurs normales",
        "compte-rendu",
        "compte rendu",
        "prélèvement",
        "prelevement",
        "biologie",
        "pathologie",
        "formule sanguine",
        "numération",
        "plaquettes",
        "leucocytes",
        "crp",
        "u/l",
        "g/l",
    )
    steg_hits = _count_hits(txt, steg_keys)
    med_hits = _count_hits(txt, med_keys)
    receipt_score = _weighted_receipt_score(txt)
    steg_score = _weighted_steg_score(txt)
    supplier_score = _weighted_supplier_invoice_score(txt)

    # Médical prioritaire si vocabulaire labo net (avant ticket / STEG)
    if med_hits >= 3 and med_hits * 2 >= receipt_score:
        return "medical_lab_report"

    # STEG prioritaire si score clairement dominant (évite confusion avec tickets contenant "payer/total")
    if steg_score >= 6 and steg_score >= receipt_score:
        return "steg_invoice"

    # Facture fournisseur générique (pas STEG, pas ticket dominant)
    if (
        steg_score < 5
        and steg_hits < 4
        and "steg" not in txt
        and supplier_score >= 5
        and supplier_score > receipt_score
        and (_supplier_invoice_anchor(txt) or supplier_score >= 14)
    ):
        return "supplier_invoice"

    # Ticket : score pondéré (mots forts x2) + faible concurrence STEG/médical
    if receipt_score >= 4 and receipt_score > max(steg_hits * 2, steg_score) and receipt_score > med_hits * 2:
        return "receipt"
    if receipt_score >= 2 and steg_hits < 2 and steg_score < 5 and receipt_score > med_hits * 2:
        return "receipt"
    if receipt_score >= 2 and steg_hits <= 1 and steg_score < 4 and med_hits <= 1:
        return "receipt"

    # STEG après ticket si indices suffisants
    if (steg_hits >= med_hits and steg_hits >= 2) or steg_score >= 4:
        return "steg_invoice"

    if medical_name_hint:
        return "medical_lab_report"

    return "medical_lab_report"


def process_any_document(
    file_path: Path,
    *,
    mode: str = "auto",
    use_gemini: bool = False,
    gemini_api_key: str | None = None,
    gemini_model: str | None = None,
) -> Dict:
    chosen = mode
    if mode == "auto":
        dt = detect_document_type(file_path)
        if dt == "steg_invoice":
            chosen = "steg"
        elif dt == "receipt":
            chosen = "receipt"
        elif dt == "supplier_invoice":
            chosen = "supplier"
        else:
            chosen = "medical"

    if chosen == "supplier":
        from pipelines.extract_supplier_invoice_gemini import extract_supplier_invoice

        if not (
            gemini_api_key
            or os.getenv("GEMINI_API_KEY")
            or os.getenv("GOOGLE_API_KEY")
        ):
            raise EnvironmentError(
                "GEMINI_API_KEY (ou GOOGLE_API_KEY) requise pour la facture fournisseur."
            )
        data = extract_supplier_invoice(
            file_path,
            gemini_api_key=gemini_api_key,
            model=gemini_model or os.getenv("GEMINI_MODEL"),
        )
        return {"kind": "supplier_invoice", "doc_type": "supplier_invoice", "result": data}

    if chosen == "receipt":
        from pipelines.extract_receipt_gemini import extract_receipt

        suf = file_path.suffix.lower()
        if suf == ".pdf":
            raise ValueError(
                "Ticket : fournissez une image (JPG, PNG, TIFF, WebP), pas un PDF."
            )
        if not (gemini_api_key or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")):
            raise EnvironmentError(
                "GEMINI_API_KEY requise pour l'extraction ticket (mode auto)."
            )
        data = extract_receipt(file_path, model=gemini_model or os.getenv("GEMINI_MODEL"))
        return {"kind": "receipt", "doc_type": "receipt", "result": data}

    if chosen == "steg":
        if use_gemini:
            from pipelines.extract_steg_invoice_gemini import extract_steg_invoice

            suf = file_path.suffix.lower()
            if suf == ".pdf":
                raise ValueError(
                    "Extraction STEG via Gemini : fournissez une image (JPG, PNG, TIFF, WebP), pas un PDF."
                )
            data = extract_steg_invoice(file_path, model=gemini_model)
            steg_payload = {
                "file_name": file_path.name,
                **data,
            }
            return {
                "kind": "steg",
                "doc_type": "steg_invoice",
                "result": enrich_steg_router_result(steg_payload),
            }

        configure_tesseract()
        res = extract_fields_from_invoice(file_path)
        steg_ocr = {
            "file_name": res.file_name,
            "reference": res.reference,
            "montant_a_payer": res.montant_a_payer,
            "date_limite_paiement": res.date_limite_paiement,
            "periode_du": res.periode_du,
            "periode_au": res.periode_au,
            "coupon_reference_raw": res.coupon_reference_raw,
            "coupon_montant": res.coupon_montant,
            "confidence_note": res.confidence_note,
            "extraction_source": "ocr",
        }
        return {
            "kind": "steg",
            "doc_type": "steg_invoice",
            "result": enrich_steg_router_result(steg_ocr),
        }

    med = process_medical_file(
        file_path,
        use_gemini=use_gemini,
        gemini_api_key=gemini_api_key,
        gemini_model=gemini_model,
    )
    return {"kind": "medical", "doc_type": "medical_lab_report", "result": med}

