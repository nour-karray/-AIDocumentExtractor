"""Génération d'un PDF « rapport d'extraction » (mise en page type DOCEXTRACT)."""

from __future__ import annotations

import os
import platform
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Any

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

COLOR_HEADER_BG = colors.HexColor("#1a3a5c")
COLOR_ACCENT = colors.HexColor("#90caf9")
COLOR_ROW_ALT = colors.HexColor("#e8f4fc")
COLOR_BORDER = colors.HexColor("#64b5f6")

_KIND_DOC_LABEL: dict[str, str] = {
    "medical_gemini": "MEDICAL",
    "medical_ocr": "MEDICAL (OCR)",
    "medical_local": "MEDICAL (DOCLING + QWEN)",
    "steg_gemini": "FACTURE STEG",
    "steg_ocr": "FACTURE STEG (OCR)",
    "steg_local": "FACTURE STEG (DOCLING + QWEN)",
    "receipt": "TICKET DE CAISSE",
    "receipt_local": "TICKET DE CAISSE (DOCLING + QWEN)",
    "supplier_invoice": "FACTURE FOURNISSEUR",
    "supplier_invoice_local": "FACTURE FOURNISSEUR (DOCLING + QWEN)",
    "document_local": "DOCUMENT (DOCLING + QWEN)",
}

_FONT_BODY = "Helvetica"
_FONT_BOLD = "Helvetica-Bold"
_FONTS_READY = False


def _register_fonts() -> None:
    """Préfère une police TTF (Arial / DejaVu) pour les accents ; sinon Helvetica PDF."""
    global _FONT_BODY, _FONT_BOLD, _FONTS_READY
    if _FONTS_READY:
        return
    _FONTS_READY = True
    candidates: list[Path] = []
    if platform.system() == "Windows":
        windir = Path(os.environ.get("WINDIR", r"C:\Windows"))
        candidates.extend(
            [
                windir / "Fonts" / "arial.ttf",
                windir / "Fonts" / "Arial.ttf",
                windir / "Fonts" / "calibri.ttf",
            ]
        )
    else:
        candidates.extend(
            [
                Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
                Path("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"),
            ]
        )
    for p in candidates:
        if not p.is_file():
            continue
        try:
            body_name = "DXSansBody"
            bold_name = "DXSansBold"
            pdfmetrics.registerFont(TTFont(body_name, str(p)))
            bold_path = p.parent / "arialbd.ttf"
            if p.stem.lower() == "arial" and bold_path.is_file():
                pdfmetrics.registerFont(TTFont(bold_name, str(bold_path)))
            else:
                pdfmetrics.registerFont(TTFont(bold_name, str(p)))
            _FONT_BODY = body_name
            _FONT_BOLD = bold_name
            return
        except Exception:
            continue


def _fmt_report_datetime(iso_str: str | None) -> str:
    if not iso_str:
        return "—"
    try:
        dt = datetime.fromisoformat(str(iso_str).replace("Z", "+00:00"))
        if dt.tzinfo:
            dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
        return dt.strftime("%d/%m/%Y %H:%M")
    except (ValueError, TypeError):
        return str(iso_str)[:19]


_style_base: ParagraphStyle | None = None
_style_bold: ParagraphStyle | None = None
_style_seq = 0


def _cell_style_base() -> ParagraphStyle:
    global _style_base, _style_seq
    _register_fonts()
    if _style_base is None:
        _style_seq += 1
        styles = getSampleStyleSheet()
        _style_base = ParagraphStyle(
            name=f"DXCell{_style_seq}",
            parent=styles["Normal"],
            fontName=_FONT_BODY,
            fontSize=9,
            leading=11,
            spaceAfter=0,
            spaceBefore=0,
        )
    return _style_base


def _cell_style_bold() -> ParagraphStyle:
    global _style_bold, _style_seq
    _register_fonts()
    if _style_bold is None:
        _style_seq += 1
        _style_bold = ParagraphStyle(
            name=f"DXCellBold{_style_seq}",
            parent=_cell_style_base(),
            fontName=_FONT_BOLD,
            fontSize=10,
            leading=12,
        )
    return _style_bold


def _p(text: Any, style: ParagraphStyle) -> Paragraph:
    t = "" if text is None else str(text)
    t = t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return Paragraph(t, style)


def _header_block(meta: dict[str, Any], kind: str, source_filename: str) -> list[Any]:
    st_bold = _cell_style_bold()
    st = _cell_style_base()
    doc_type = _KIND_DOC_LABEL.get(kind, (kind or "DOCUMENT").upper())

    title_style = ParagraphStyle(
        "DXTitleW",
        parent=st_bold,
        fontSize=22,
        textColor=colors.white,
        alignment=1,
        fontName=_FONT_BOLD,
    )
    banner = Table([[Paragraph("DOCEXTRACT", title_style)]], colWidths=[17 * cm])
    banner.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), COLOR_HEADER_BG),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 14),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 14),
            ]
        )
    )

    sub_style = ParagraphStyle(
        "DXSub",
        parent=st,
        fontSize=11,
        textColor=COLOR_HEADER_BG,
        alignment=1,
        fontName=_FONT_BODY,
    )
    sub = Table([[Paragraph("Rapport d'extraction automatique", sub_style)]], colWidths=[17 * cm])
    sub.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), COLOR_ACCENT),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )

    meta_rows = [
        [_p("Fichier source", st_bold), _p(source_filename or "—", st)],
        [_p("Date rapport", st_bold), _p(_fmt_report_datetime(meta.get("saved_at")), st)],
        [_p("Type document", st_bold), _p(doc_type, st)],
        [_p("Généré par", st_bold), _p("pfaEXTRACT / Gemini AI", st)],
    ]
    meta_tbl = Table(meta_rows, colWidths=[4.2 * cm, 12.8 * cm])
    meta_tbl.setStyle(
        TableStyle(
            [
                ("BOX", (0, 0), (-1, -1), 0.8, COLOR_BORDER),
                ("INNERGRID", (0, 0), (-1, -1), 0.4, COLOR_BORDER),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ("ROWBACKGROUNDS", (0, 0), (-1, -1), [colors.white, COLOR_ROW_ALT]),
            ]
        )
    )

    line = Table([[""]], colWidths=[17 * cm], rowHeights=[0.08 * cm])
    line.setStyle(TableStyle([("LINEABOVE", (0, 0), (-1, -1), 1.2, COLOR_BORDER)]))

    return [banner, sub, Spacer(1, 0.25 * cm), meta_tbl, Spacer(1, 0.35 * cm), line, Spacer(1, 0.45 * cm)]


def _section_title(title: str) -> Paragraph:
    st = _cell_style_bold()
    return Paragraph(f"<b>{title}</b>", ParagraphStyle("DXSec", parent=st, fontSize=12, spaceAfter=8))


def _draw_page_footer(canvas: Any, doc: SimpleDocTemplate) -> None:
    _register_fonts()
    canvas.saveState()
    canvas.setFont(_FONT_BODY, 8)
    canvas.setFillColor(colors.HexColor("#667085"))
    canvas.drawRightString(A4[0] - doc.rightMargin, 0.65 * cm, f"Page {doc.page}")
    canvas.restoreState()


def _analysis_row_gemini(row: dict[str, Any]) -> list[str]:
    """Ligne PDF : Analyse, Valeur, Unité uniquement (ignore Normes / Statut du JSON)."""
    name = (
        row.get("test_name")
        or row.get("raw_test_name")
        or row.get("name")
        or row.get("Analyse")
    )
    val = row.get("value")
    if val is None:
        val = row.get("value_text")
    if val is None:
        val = row.get("Valeur")
    val_s = "—" if val in (None, "") else str(val)
    unit = row.get("unit")
    if unit in (None, ""):
        unit = row.get("Unité")
    unit_s = "—" if unit in (None, "") else str(unit)
    name_s = "—" if name in (None, "") else str(name)
    return [name_s, val_s, unit_s]


def _analysis_row_ocr(t: dict[str, Any]) -> list[str]:
    """Ligne PDF : Analyse, Valeur, Unité uniquement (pas normes / statut)."""
    name = str(t.get("raw_test_name") or "—")
    val = t.get("value")
    if val is None and t.get("value_text"):
        val = t.get("value_text")
    val_s = "—" if val is None else str(val)
    unit = str(t.get("unit") or "—")
    return [name, val_s, unit]


def _row_three_cells(row: list[str]) -> list[str]:
    """Force exactement 3 cellules (évite que ReportLab n’ajoute des colonnes si une ligne est trop longue)."""
    cells = [str(x) for x in list(row)[:3]]
    while len(cells) < 3:
        cells.append("—")
    return cells


def _medical_results_rows(body: dict[str, Any]) -> list[list[str]]:
    """Lignes tableau médical : d’abord ``analyses`` (Gemini), sinon ``tests`` (OCR). Toujours 3 colonnes."""
    raw: list[list[str]] = []
    for r in body.get("analyses") or []:
        if isinstance(r, dict):
            raw.append(_analysis_row_gemini(r))
    if not raw:
        for t in body.get("tests") or []:
            if isinstance(t, dict):
                raw.append(_analysis_row_ocr(t))
    return [_row_three_cells(r) for r in raw]


def build_extraction_report_pdf(data: dict[str, Any], kind: str) -> bytes:
    """Construit un PDF rapport (A4) à partir du JSON d'historique et du type ``kind``."""
    global _style_base, _style_bold
    _style_base = None
    _style_bold = None

    meta = data.get("_meta") if isinstance(data.get("_meta"), dict) else {}
    body = {k: v for k, v in data.items() if k != "_meta"}
    source_fn = str(meta.get("source_filename") or "—")

    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=2 * cm,
        rightMargin=2 * cm,
        topMargin=1.2 * cm,
        bottomMargin=1.2 * cm,
        title="Rapport extraction",
    )
    story: list[Any] = []
    story.extend(_header_block(meta, kind, source_fn))

    st = _cell_style_base()
    st_b = _cell_style_bold()

    if kind == "medical_gemini":
        story.append(_section_title("Informations Patient & Médecin"))
        pinfo = [
            [_p("Patient", st_b), _p(body.get("patient_name") or "—", st)],
            [_p("Médecin", st_b), _p(body.get("doctor_name") or "—", st)],
            [_p("Date", st_b), _p(body.get("date") or "—", st)],
        ]
        t1 = Table(pinfo, colWidths=[3.2 * cm, 13.8 * cm])
        t1.setStyle(
            TableStyle(
                [
                    ("BOX", (0, 0), (-1, -1), 0.6, COLOR_BORDER),
                    ("INNERGRID", (0, 0), (-1, -1), 0.4, COLOR_BORDER),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("ROWBACKGROUNDS", (0, 0), (-1, -1), [colors.white, COLOR_ROW_ALT]),
                    ("LEFTPADDING", (0, 0), (-1, -1), 8),
                    ("TOPPADDING", (0, 0), (-1, -1), 6),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ]
            )
        )
        story.append(t1)
        story.append(Spacer(1, 0.5 * cm))
        story.append(_section_title("Résultats d'analyses"))
        rows = _medical_results_rows(body)
        hdr = [_row_three_cells(["Analyse", "Valeur", "Unité"])]
        if not rows:
            rows = [_row_three_cells(["—", "—", "—"])]
        tw = [6.5 * cm, 3.5 * cm, 7.0 * cm]
        t2 = Table(hdr + rows, colWidths=tw, repeatRows=1)
        t2.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), COLOR_HEADER_BG),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("FONTNAME", (0, 0), (-1, 0), _FONT_BOLD),
                    ("FONTSIZE", (0, 0), (-1, 0), 9),
                    ("FONTNAME", (0, 1), (-1, -1), _FONT_BODY),
                    ("FONTSIZE", (0, 1), (-1, -1), 8),
                    ("ALIGN", (0, 0), (-1, -1), "LEFT"),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("BOX", (0, 0), (-1, -1), 0.6, COLOR_BORDER),
                    ("INNERGRID", (0, 0), (-1, -1), 0.35, COLOR_BORDER),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, COLOR_ROW_ALT]),
                    ("LEFTPADDING", (0, 0), (-1, -1), 5),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                    ("TOPPADDING", (0, 0), (-1, -1), 5),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ]
            )
        )
        story.append(t2)

    elif kind in ("medical_ocr", "medical_local"):
        lab = body.get("lab_info") or {}
        patient = body.get("patient_info") or {}
        if not isinstance(lab, dict):
            lab = {}
        if not isinstance(patient, dict):
            patient = {}
        story.append(_section_title("Informations Patient & Médecin"))
        pinfo = [
            [_p("Laboratoire", st_b), _p(lab.get("lab_name") or "—", st)],
            [_p("Médecin", st_b), _p(lab.get("doctor_name") or "—", st)],
            [_p("Patient", st_b), _p(patient.get("patient_name") or "—", st)],
        ]
        t1 = Table(pinfo, colWidths=[3.2 * cm, 13.8 * cm])
        t1.setStyle(
            TableStyle(
                [
                    ("BOX", (0, 0), (-1, -1), 0.6, COLOR_BORDER),
                    ("INNERGRID", (0, 0), (-1, -1), 0.4, COLOR_BORDER),
                    ("ROWBACKGROUNDS", (0, 0), (-1, -1), [colors.white, COLOR_ROW_ALT]),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 8),
                    ("TOPPADDING", (0, 0), (-1, -1), 6),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ]
            )
        )
        story.append(t1)
        story.append(Spacer(1, 0.5 * cm))
        story.append(_section_title("Résultats d'analyses"))
        rows = _medical_results_rows(body)
        hdr = [_row_three_cells(["Analyse", "Valeur", "Unité"])]
        if not rows:
            rows = [_row_three_cells(["—", "—", "—"])]
        tw = [6.5 * cm, 3.5 * cm, 7.0 * cm]
        t2 = Table(hdr + rows, colWidths=tw, repeatRows=1)
        t2.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), COLOR_HEADER_BG),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("FONTNAME", (0, 0), (-1, 0), _FONT_BOLD),
                    ("FONTSIZE", (0, 0), (-1, 0), 9),
                    ("FONTNAME", (0, 1), (-1, -1), _FONT_BODY),
                    ("FONTSIZE", (0, 1), (-1, -1), 8),
                    ("ALIGN", (0, 0), (-1, -1), "LEFT"),
                    ("BOX", (0, 0), (-1, -1), 0.6, COLOR_BORDER),
                    ("INNERGRID", (0, 0), (-1, -1), 0.35, COLOR_BORDER),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, COLOR_ROW_ALT]),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 5),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                    ("TOPPADDING", (0, 0), (-1, -1), 5),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ]
            )
        )
        story.append(t2)

    elif kind in ("steg_gemini", "steg_ocr", "steg_local"):
        story.append(_section_title("Facture STEG — champs extraits"))
        rows_kv = [
            ["Référence", str(body.get("reference") or "—")],
            ["N° compteur", str(body.get("numero_compteur") or body.get("identifiant_compteur") or "—")],
            ["Date facture", str(body.get("date_facture") or "—")],
            ["Montant à payer", str(body.get("montant_a_payer") or "—")],
            ["Date limite paiement", str(body.get("date_limite_paiement") or "—")],
            ["Période Du", str(body.get("periode_du") or "—")],
            ["Période Au", str(body.get("periode_au") or "—")],
            ["Montant coupon", str(body.get("coupon_montant") or "—")],
            ["Confiance", str(body.get("confidence_note") or "—")],
        ]
        tbl_data = [[_p(k, st_b), _p(v, st)] for k, v in rows_kv]
        t1 = Table(tbl_data, colWidths=[4.5 * cm, 12.5 * cm])
        t1.setStyle(
            TableStyle(
                [
                    ("BOX", (0, 0), (-1, -1), 0.6, COLOR_BORDER),
                    ("INNERGRID", (0, 0), (-1, -1), 0.4, COLOR_BORDER),
                    ("ROWBACKGROUNDS", (0, 0), (-1, -1), [colors.white, COLOR_ROW_ALT]),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 8),
                    ("TOPPADDING", (0, 0), (-1, -1), 6),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ]
            )
        )
        story.append(t1)

    elif kind in ("receipt", "receipt_local"):
        story.append(_section_title("Ticket de caisse"))
        rows_kv = [
            ["Magasin", str(body.get("store_name") or "—")],
            ["Date", str(body.get("date") or "—")],
            ["Heure", str(body.get("time") or "—")],
            ["N° ticket", str(body.get("ticket_number") or "—")],
            ["Total", str(body.get("total") or "—")],
            ["Devise", str(body.get("currency") or "—")],
            ["Paiement", str(body.get("payment_method") or "—")],
        ]
        tbl_data = [[_p(k, st_b), _p(v, st)] for k, v in rows_kv]
        t1 = Table(tbl_data, colWidths=[4.5 * cm, 12.5 * cm])
        t1.setStyle(
            TableStyle(
                [
                    ("BOX", (0, 0), (-1, -1), 0.6, COLOR_BORDER),
                    ("INNERGRID", (0, 0), (-1, -1), 0.4, COLOR_BORDER),
                    ("ROWBACKGROUNDS", (0, 0), (-1, -1), [colors.white, COLOR_ROW_ALT]),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 8),
                    ("TOPPADDING", (0, 0), (-1, -1), 6),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ]
            )
        )
        story.append(t1)
        items = body.get("items") or []
        if isinstance(items, list) and items and isinstance(items[0], dict):
            story.append(Spacer(1, 0.4 * cm))
            story.append(_section_title("Articles"))
            keys = list(items[0].keys())
            hdr = [keys]
            data_rows = [[str(it.get(k, "")) for k in keys] for it in items if isinstance(it, dict)]
            ncols = len(keys)
            col_w = 17.0 / max(ncols, 1)
            tw = [col_w * cm] * ncols
            t2 = Table(hdr + data_rows, colWidths=tw, repeatRows=1)
            t2.setStyle(
                TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (-1, 0), COLOR_HEADER_BG),
                        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                        ("FONTNAME", (0, 0), (-1, 0), _FONT_BOLD),
                        ("FONTNAME", (0, 1), (-1, -1), _FONT_BODY),
                        ("BOX", (0, 0), (-1, -1), 0.6, COLOR_BORDER),
                        ("INNERGRID", (0, 0), (-1, -1), 0.35, COLOR_BORDER),
                        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, COLOR_ROW_ALT]),
                    ]
                )
            )
            story.append(t2)

    elif kind in ("supplier_invoice", "supplier_invoice_local"):
        story.append(_section_title("Informations générales"))
        rtl = body.get("ocr_rtl_text_ratio")
        rtl_s = f"{float(rtl):.3f}" if isinstance(rtl, (int, float)) else (str(rtl) if rtl not in (None, "") else "—")
        gen_kv = [
            ["N° facture", str(body.get("invoice_number") or "—")],
            ["Date facture", str(body.get("invoice_date") or "—")],
            ["Échéance", str(body.get("due_date") or "—")],
            ["Devise", str(body.get("currency") or "—")],
            ["Confiance (modèle)", str(body.get("confidence") or "—")],
            ["Indice RTL (OCR)", rtl_s],
        ]
        t0 = Table([[_p(k, st_b), _p(v, st)] for k, v in gen_kv], colWidths=[4.5 * cm, 12.5 * cm])
        t0.setStyle(
            TableStyle(
                [
                    ("BOX", (0, 0), (-1, -1), 0.6, COLOR_BORDER),
                    ("INNERGRID", (0, 0), (-1, -1), 0.4, COLOR_BORDER),
                    ("ROWBACKGROUNDS", (0, 0), (-1, -1), [colors.white, COLOR_ROW_ALT]),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 8),
                    ("TOPPADDING", (0, 0), (-1, -1), 6),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ]
            )
        )
        story.append(t0)
        story.append(Spacer(1, 0.35 * cm))

        seller = body.get("seller") if isinstance(body.get("seller"), dict) else {}
        client = body.get("client") if isinstance(body.get("client"), dict) else {}
        story.append(_section_title("Fournisseur"))
        skv = [
            ["Nom", str(seller.get("name") or "—")],
            ["Adresse", str(seller.get("address") or "—")],
            ["Identifiant fiscal", str(seller.get("tax_id") or "—")],
            ["IBAN", str(seller.get("iban") or "—")],
            ["Email", str(seller.get("email") or "—")],
            ["Téléphone", str(seller.get("phone") or "—")],
        ]
        t1 = Table([[_p(k, st_b), _p(v, st)] for k, v in skv], colWidths=[4.5 * cm, 12.5 * cm])
        t1.setStyle(
            TableStyle(
                [
                    ("BOX", (0, 0), (-1, -1), 0.6, COLOR_BORDER),
                    ("INNERGRID", (0, 0), (-1, -1), 0.4, COLOR_BORDER),
                    ("ROWBACKGROUNDS", (0, 0), (-1, -1), [colors.white, COLOR_ROW_ALT]),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 8),
                    ("TOPPADDING", (0, 0), (-1, -1), 6),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ]
            )
        )
        story.append(t1)
        story.append(Spacer(1, 0.35 * cm))

        story.append(_section_title("Client"))
        ckv = [
            ["Nom", str(client.get("name") or "—")],
            ["Adresse", str(client.get("address") or "—")],
            ["Identifiant fiscal", str(client.get("tax_id") or "—")],
            ["Email", str(client.get("email") or "—")],
            ["Téléphone", str(client.get("phone") or "—")],
        ]
        t1c = Table([[_p(k, st_b), _p(v, st)] for k, v in ckv], colWidths=[4.5 * cm, 12.5 * cm])
        t1c.setStyle(
            TableStyle(
                [
                    ("BOX", (0, 0), (-1, -1), 0.6, COLOR_BORDER),
                    ("INNERGRID", (0, 0), (-1, -1), 0.4, COLOR_BORDER),
                    ("ROWBACKGROUNDS", (0, 0), (-1, -1), [colors.white, COLOR_ROW_ALT]),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 8),
                    ("TOPPADDING", (0, 0), (-1, -1), 6),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ]
            )
        )
        story.append(t1c)
        story.append(Spacer(1, 0.35 * cm))

        summary = body.get("summary") if isinstance(body.get("summary"), dict) else {}
        story.append(_section_title("Résumé montants"))
        sk = [
            ["Sous-total", str(summary.get("subtotal") or "—")],
            ["Total TVA", str(summary.get("tax_total") or "—")],
            ["Remise", str(summary.get("discount") or "—")],
            ["Livraison / frais", str(summary.get("shipping") or "—")],
            ["Total", str(summary.get("total_amount") or "—")],
            ["Montant dû", str(summary.get("amount_due") or "—")],
        ]
        ts = Table([[_p(k, st_b), _p(v, st)] for k, v in sk], colWidths=[4.5 * cm, 12.5 * cm])
        ts.setStyle(
            TableStyle(
                [
                    ("BOX", (0, 0), (-1, -1), 0.6, COLOR_BORDER),
                    ("INNERGRID", (0, 0), (-1, -1), 0.4, COLOR_BORDER),
                    ("ROWBACKGROUNDS", (0, 0), (-1, -1), [colors.white, COLOR_ROW_ALT]),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 8),
                    ("TOPPADDING", (0, 0), (-1, -1), 6),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ]
            )
        )
        story.append(ts)

        items = body.get("items") or []
        if isinstance(items, list) and items and isinstance(items[0], dict):
            story.append(Spacer(1, 0.4 * cm))
            story.append(_section_title("Articles"))
            keys = [
                "description",
                "quantity",
                "unit",
                "unit_price",
                "net_amount",
                "tax_rate",
                "tax_amount",
                "gross_amount",
            ]
            hdr = [keys]
            data_rows = []
            for it in items:
                if not isinstance(it, dict):
                    continue
                data_rows.append([str(it.get(k, "") or "") for k in keys])
            if data_rows:
                ncols = len(keys)
                col_w = 17.0 / max(ncols, 1)
                tw = [col_w * cm] * ncols
                t2 = Table(hdr + data_rows, colWidths=tw, repeatRows=1)
                t2.setStyle(
                    TableStyle(
                        [
                            ("BACKGROUND", (0, 0), (-1, 0), COLOR_HEADER_BG),
                            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                            ("FONTNAME", (0, 0), (-1, 0), _FONT_BOLD),
                            ("FONTNAME", (0, 1), (-1, -1), _FONT_BODY),
                            ("FONTSIZE", (0, 1), (-1, -1), 7),
                            ("BOX", (0, 0), (-1, -1), 0.6, COLOR_BORDER),
                            ("INNERGRID", (0, 0), (-1, -1), 0.35, COLOR_BORDER),
                            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, COLOR_ROW_ALT]),
                        ]
                    )
                )
                story.append(t2)

    else:
        story.append(_section_title("Données extraites (résumé)"))
        story.append(_p("Type non détaillé dans le modèle — affichage des champs principaux.", st))
        story.append(Spacer(1, 0.3 * cm))
        flat: list[list[Any]] = []
        for k, v in list(body.items())[:40]:
            if isinstance(v, (dict, list)):
                v = str(v)[:500]
            flat.append([_p(k, st_b), _p(v, st)])
        if not flat:
            flat = [[_p("—", st_b), _p("—", st)]]
        t1 = Table(flat, colWidths=[4.5 * cm, 12.5 * cm])
        t1.setStyle(
            TableStyle(
                [
                    ("BOX", (0, 0), (-1, -1), 0.6, COLOR_BORDER),
                    ("INNERGRID", (0, 0), (-1, -1), 0.4, COLOR_BORDER),
                    ("ROWBACKGROUNDS", (0, 0), (-1, -1), [colors.white, COLOR_ROW_ALT]),
                ]
            )
        )
        story.append(t1)

    doc.build(story, onFirstPage=_draw_page_footer, onLaterPages=_draw_page_footer)
    return buf.getvalue()
