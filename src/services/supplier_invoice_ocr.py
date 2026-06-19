"""OCR Tesseract (multilingue, multipasse) pour la détection routeur et les hints Gemini."""

from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import pytesseract

from src.extraction.steg_invoice_extractor import configure_tesseract, read_image
from src.services.document_preprocessing import preprocess_document
from src.utils.arabic_invoice_utils import clean_arabic_ocr_text, normalize_numeric_digits, rtl_script_ratio


_ROUTER_OCR_PSMS = (6, 4, 11)
_ROUTER_OCR_MIN_SIDE = 1050
_ROUTER_PDF_RASTER_DPI = int(os.getenv("ROUTER_OCR_PDF_DPI", "200"))


def extract_pdf_embedded_text(path: Path, max_pages: int = 3) -> str:
    """Texte extractible (PDF natif) pour hints routeur — complète l'OCR sur scans."""
    try:
        from pypdf import PdfReader
    except Exception:
        return ""
    try:
        reader = PdfReader(str(path.resolve()))
        parts: list[str] = []
        for page in reader.pages[:max_pages]:
            t = page.extract_text()
            if t:
                parts.append(t)
        return "\n".join(parts)
    except Exception:
        return ""


def build_document_router_text(file_path: Path) -> str:
    """Texte combiné (PDF natif + Tesseract ara/eng) pour classification automatique."""
    chunks: list[str] = []
    if file_path.suffix.lower() == ".pdf":
        chunks.append(extract_pdf_embedded_text(file_path))
    gray = load_gray_for_invoice_ocr(file_path)
    if gray is not None:
        ocr_full, _ = ocr_invoice_multilingual(gray, max_chars=12000)
        chunks.append(ocr_full)
    merged = "\n".join(chunks)
    merged = normalize_numeric_digits(merged)
    merged = clean_arabic_ocr_text(merged)
    return merged.lower()


def _pil_gray_from_pdf_first_page(path: Path) -> np.ndarray | None:
    try:
        from pdf2image import convert_from_path
    except Exception:
        return None
    try:
        pages = convert_from_path(
            str(path.resolve()),
            dpi=_ROUTER_PDF_RASTER_DPI,
            first_page=1,
            last_page=1,
            fmt="png",
        )
        if not pages:
            return None
        pil = pages[0].convert("L")
        return np.array(pil, dtype=np.uint8)
    except Exception:
        return None


def _preferred_tesseract_lang_chains() -> list[str]:
    """Chaînes langues selon les packs installés (priorité documents TN / FR / AR)."""
    try:
        avail = set(pytesseract.get_languages(config=""))
    except Exception:
        avail = {"eng"}

    def chain(*want: str) -> str | None:
        parts = [w for w in want if w in avail]
        return "+".join(parts) if parts else None

    seen: list[str] = []
    for combo in (
        ("fra", "ara", "eng"),
        ("ara", "fra", "eng"),
        ("ara", "eng"),
        ("eng", "fra"),
        ("fra", "eng"),
        ("ara",),
        ("eng",),
    ):
        s = chain(*combo)
        if s and s not in seen:
            seen.append(s)
    return seen or ["eng"]


def _score_router_candidate(text: str) -> float:
    """Heuristique fusionnée (score PFAdocumentEXTRACTION + signaux factures / STEG / tickets)."""
    if not text or not text.strip():
        return 0.0
    digits = len(re.findall(r"\d", text))
    letters = len(re.findall(r"[A-Za-z\u0600-\u06FF]", text))
    money_like = len(
        re.findall(r"\d+[.,]\d{2,3}|\d{1,3}(?:[ \u00a0\u202f]\d{3})+", text)
    )
    kw = len(
        re.findall(
            r"montant|total|payer|tva|ttc|facture|invoice|steg|reference|r[ée]f[ée]rence|"
            r"laboratoire|glyc|ticket|re[çc]u|caisse|kwh|compteur|abonn[ée]|مرجع|فاتورة|"
            r"الاداء|دينار|tnd|iban|swift",
            text,
            re.I,
        )
    )
    return digits * 1.0 + letters * 0.14 + money_like * 2.1 + kw * 1.35


def _maybe_upscale_gray(gray: np.ndarray) -> np.ndarray:
    if gray is None or gray.size == 0:
        return gray
    h, w = gray.shape[:2]
    m = min(h, w)
    if m >= _ROUTER_OCR_MIN_SIDE:
        return gray
    scale = _ROUTER_OCR_MIN_SIDE / float(max(m, 1))
    nw, nh = max(1, int(w * scale)), max(1, int(h * scale))
    return cv2.resize(gray, (nw, nh), interpolation=cv2.INTER_CUBIC)


def _gray_preprocess_variants(gray: np.ndarray) -> list[np.ndarray]:
    """Original redimensionné + CLAHE + binarisation Otsu (comme scripts OCR PFA historiques)."""
    base = _maybe_upscale_gray(gray)
    variants = [base]
    try:
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        variants.append(clahe.apply(base))
    except Exception:
        pass
    try:
        blur = cv2.GaussianBlur(base, (3, 3), 0)
        _, otsu = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        variants.append(otsu)
    except Exception:
        pass
    return variants


def _tesseract_try_string(img: np.ndarray, *, lang: str, psm: int) -> str:
    cfg = f"--oem 3 --psm {psm}"
    return pytesseract.image_to_string(img, lang=lang, config=cfg) or ""


def _bottom_strip_best(
    gray: np.ndarray,
    *,
    lang_chains: list[str],
) -> str:
    """Bande bas de page (zones Total / paiement / mentions légales), inspiré pfa20."""
    if gray is None or gray.size == 0:
        return ""
    h, w = gray.shape[:2]
    y0 = int(h * 0.66)
    roi = gray[y0:h, 0:w]
    if roi.size == 0:
        return ""
    roi = cv2.resize(roi, None, fx=1.85, fy=1.85, interpolation=cv2.INTER_CUBIC)
    best = ""
    best_sc = -1.0
    primary_langs = lang_chains[: min(3, len(lang_chains))]
    for lang in primary_langs:
        for psm in (6, 11):
            try:
                t = _tesseract_try_string(roi, lang=lang, psm=psm).strip()
            except Exception:
                continue
            sc = _score_router_candidate(t)
            if sc > best_sc and t:
                best_sc = sc
                best = t
    return best


def load_gray_for_invoice_ocr(path: Path) -> np.ndarray | None:
    """Image entière ou première page PDF en niveaux de gris."""
    suf = path.suffix.lower()
    if suf == ".pdf":
        g = _pil_gray_from_pdf_first_page(path)
        return g
    try:
        with tempfile.TemporaryDirectory() as prep_dir:
            try:
                preprocessed = preprocess_document(path, Path(prep_dir))
                img = read_image(preprocessed.path)
            except Exception:
                img = read_image(path)
        return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    except Exception:
        return None


def ocr_invoice_multilingual(gray: np.ndarray, *, max_chars: int = 12000) -> tuple[str, dict[str, Any]]:
    """
    OCR multipasse : plusieurs prétraitements × langues installées × PSM, meilleur score conservé,
    plus lecture renforcée de la bande bas de page (STEG / totaux / mentions).

    S'inspire des projets PFAdocumentEXTRACTION (variantes + scoring) et pfa20 (multi-PSM + bande bas).
    """
    configure_tesseract()
    lang_chains = _preferred_tesseract_lang_chains()
    variants = _gray_preprocess_variants(gray)

    best_body = ""
    best_score = -1.0

    for prep in variants:
        for lang in lang_chains:
            for psm in _ROUTER_OCR_PSMS:
                try:
                    chunk = _tesseract_try_string(prep, lang=lang, psm=psm).strip()
                except Exception:
                    continue
                sc = _score_router_candidate(chunk)
                if sc > best_score and chunk:
                    best_score = sc
                    best_body = chunk

    strip_txt = _bottom_strip_best(_maybe_upscale_gray(gray), lang_chains=lang_chains)
    merged_parts = [p for p in (best_body, strip_txt) if p]
    raw = "\n---\n".join(merged_parts) if len(merged_parts) > 1 else (merged_parts[0] if merged_parts else "")
    normalized_digits = normalize_numeric_digits(raw)
    cleaned = clean_arabic_ocr_text(normalized_digits)
    meta = {
        "rtl_ratio": round(rtl_script_ratio(cleaned), 4),
        "langs_attempted": list(lang_chains),
        "char_count": len(cleaned),
        "ocr_engine": "tesseract_multipass_router_v2",
        "best_body_score": round(float(best_score), 4),
    }
    if len(cleaned) > max_chars:
        cleaned = cleaned[:max_chars] + "\n...[truncated]"
    return cleaned, meta


def build_router_ocr_blob(file_path: Path) -> str:
    """Alias : texte pour scoring mots-clés (PDF natif + OCR multilingue)."""
    return build_document_router_text(file_path)


def build_gemini_ocr_hint(file_path: Path) -> tuple[str, dict[str, Any]]:
    """Fragment OCR optionnel passé au prompt Gemini (complète la vision)."""
    gray = load_gray_for_invoice_ocr(file_path)
    if gray is None:
        return "", {"error": "no_gray"}
    return ocr_invoice_multilingual(gray, max_chars=6000)
