"""
Extraction legere pour comptes-rendus / bilans d'analyses medicales (scans, photos).
Meme philosophie que le pipeline STEG: Tesseract, champs par regles, export JSON/CSV.
"""
from __future__ import annotations

import csv
import json
import os
import re
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
import pytesseract

from src.extraction.steg_invoice_extractor import (
    configure_tesseract,
    crop_relative,
    deskew_image,
    normalize_digits,
    preprocess_roi,
    read_image,
)

try:
    from rapidfuzz import fuzz
except Exception:
    fuzz = None


_easyocr_reader = None


def _medical_easyocr_enabled() -> bool:
    return os.getenv("MEDICAL_ENABLE_EASYOCR", "0").strip().lower() in ("1", "true", "yes", "on")


def _medical_fast_ocr_enabled() -> bool:
    return os.getenv("MEDICAL_FAST_OCR", "1").strip().lower() in ("1", "true", "yes", "on")


def _medical_ocr_timeout_seconds() -> float:
    try:
        return max(float(os.getenv("MEDICAL_OCR_TIMEOUT_SECONDS", "4")), 1.0)
    except ValueError:
        return 4.0


def _easyocr_text(gray_or_bin: np.ndarray) -> str:
    if not _medical_easyocr_enabled():
        return ""
    global _easyocr_reader
    try:
        import easyocr
    except Exception:
        return ""
    try:
        if _easyocr_reader is None:
            _easyocr_reader = easyocr.Reader(["fr", "en"], gpu=False, verbose=False)
        lines = _easyocr_reader.readtext(gray_or_bin, detail=0, paragraph=False)
        if not isinstance(lines, list):
            return ""
        txt = "\n".join(str(x) for x in lines if x)
        return normalize_digits(txt)
    except Exception:
        return ""


def _medical_text_score(text: str) -> int:
    if not text:
        return 0
    t = text.lower()
    score = 0
    # Penalise fortement les OCR trop bruites.
    bad_ratio = sum(1 for c in t if c in "@#[]{}|~") / max(len(t), 1)
    if bad_ratio > 0.05:
        score -= 20
    score += len(re.findall(r"\d+[.,]?\d*", t))
    score += len(re.findall(r"\b(g/l|mg/l|mmol/l|ui/l|u/l|/mm3|%)\b", t))
    score += len(
        re.findall(
            r"\b(h[eé]moglob|glyc[eé]m|tsh|crp|plaquette|leucocyt|cholesterol|triglyc|creatinin)\b",
            t,
        )
    ) * 2
    return score


def _strip_accents(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value or "")
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def _build_ocr_variants(gray: np.ndarray) -> list[np.ndarray]:
    variants: list[np.ndarray] = [gray]
    try:
        up = cv2.resize(gray, None, fx=1.6, fy=1.6, interpolation=cv2.INTER_CUBIC)
        variants.append(up)
        variants.append(cv2.GaussianBlur(up, (3, 3), 0))
        variants.append(
            cv2.adaptiveThreshold(
                up, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 11
            )
        )
        _, otsu = cv2.threshold(up, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        variants.append(otsu)
    except Exception:
        pass
    return variants


def _enhance_medical_scan(image: np.ndarray) -> np.ndarray:
    """Améliore contraste/netteté pour OCR local sur photos de bilans."""
    if image is None or image.size == 0:
        return image
    try:
        lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)
        l_ch, a_ch, b_ch = cv2.split(lab)
        clahe = cv2.createCLAHE(clipLimit=2.4, tileGridSize=(8, 8))
        l2 = clahe.apply(l_ch)
        out = cv2.cvtColor(cv2.merge([l2, a_ch, b_ch]), cv2.COLOR_LAB2BGR)
        blur = cv2.GaussianBlur(out, (0, 0), 1.0)
        out = cv2.addWeighted(out, 1.22, blur, -0.22, 0)
        return np.clip(out, 0, 255).astype(np.uint8)
    except Exception:
        return image


@dataclass
class MedicalAnalysisResult:
    file_name: str
    reference_dossier: str | None
    date_prelevement: str | None
    date_resultat: str | None
    laboratoire: str | None
    patient_nom: str | None
    # Bilan biologique: parametre, valeur, unite, valeurs_normales (priorite metier)
    resultats_analyses: list[dict[str, str | None]]
    confidence_note: str


def _validate_ymd(y: int, mo: int, d: int) -> str | None:
    if mo < 1 or mo > 12 or d < 1 or d > 31 or y < 1990 or y > 2100:
        return None
    return f"{y:04d}-{mo:02d}-{d:02d}"


def _parse_iso_dates(text: str) -> list[str]:
    text = normalize_digits(text)
    out: list[str] = []
    for m in re.finditer(
        r"(20\d{2})\s*[./\s-]\s*(\d{1,2})\s*[./\s-]\s*(\d{1,2})", text
    ):
        d = _validate_ymd(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        if d:
            out.append(d)
    for m in re.finditer(
        r"(\d{1,2})\s*[./\s-]\s*(\d{1,2})\s*[./\s-]\s*(20\d{2})", text
    ):
        d = _validate_ymd(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        if d:
            out.append(d)
    return out


def _date_near(text: str, keywords: list[str], window: int = 100) -> str | None:
    tl = text.lower()
    for kw in keywords:
        i = tl.find(kw.lower())
        if i < 0:
            continue
        chunk = text[i : i + window]
        dates = _parse_iso_dates(chunk)
        if dates:
            return dates[0]
    return None


def _extract_dates_semantic(text: str) -> tuple[str | None, str | None]:
    """(date_prelevement, date_resultat) via mots-cles FR usuels."""
    dp = _date_near(
        text,
        [
            "prelevement",
            "prélèvement",
            "preleve",
            "echantillon",
            "échantillon",
            "date de p",
        ],
    )
    dr = _date_near(
        text,
        [
            "compte-rendu",
            "compte rendu",
            "edité",
            "édité",
            "emis",
            "émis",
            "resultat",
            "résultat",
            "signé",
            "signe",
            "valable",
        ],
    )
    if not dp or not dr:
        all_d = _parse_iso_dates(text)
        if all_d:
            if not dp:
                dp = all_d[0]
            if not dr and len(all_d) > 1:
                dr = all_d[-1]
            elif not dr:
                dr = all_d[0]
    return dp, dr


def _extract_reference(text: str) -> str | None:
    t = normalize_digits(re.sub(r"\s+", " ", text))
    patterns = [
        r"(?:n[°o]?\s*(?:dossier|patient|analyse)?|ref\.?|reference|référence|code)\s*[.:]?\s*([A-Z0-9][A-Z0-9\s\-]{3,28})",
        r"\b(?:ID|N[°o])\s*[.:]?\s*([A-Z0-9]{6,20})\b",
    ]
    for pat in patterns:
        m = re.search(pat, t, re.IGNORECASE)
        if m:
            cand = re.sub(r"\s+", " ", m.group(1).strip())
            if len(cand) >= 4:
                return cand[:48]
    nums = re.findall(r"\b(\d{8,14})\b", t)
    if nums:
        return max(nums, key=len)
    return None


def _extract_patient(text: str) -> str | None:
    patterns = [
        r"(?:patient|nom\s*(?:et)?\s*pr[eé]nom|identit[eé]|beneficiaire|bénéficiaire)\s*[.:]?\s*(.+)",
    ]
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE | re.DOTALL)
        if not m:
            continue
        line = m.group(1).strip().split("\n")[0].strip()
        line = re.sub(r"\s+", " ", line)
        if 3 < len(line) < 90 and not re.match(r"^\d+$", line):
            return line
    # Fallback fréquent sur vos modèles: "Mme NOM PRENOM" ou "M NOM PRENOM"
    m2 = re.search(r"\b(?:mme|mr|m)\s+([A-Z][A-Z\s\-]{4,80})\b", normalize_digits(text), re.IGNORECASE)
    if m2:
        line = re.sub(r"\s+", " ", m2.group(1)).strip()
        if len(line) >= 5:
            return line.title()
    return None


def _ocr_body_region(image: np.ndarray) -> str:
    """Zone centrale (tableaux d'analyses), souvent plus lisible que la page entiere."""
    body = crop_relative(image, 0.02, 0.18, 0.98, 0.90)
    if body.size == 0:
        return ""
    gray = cv2.cvtColor(body, cv2.COLOR_BGR2GRAY)
    candidates: list[str] = []
    for v in _build_ocr_variants(gray):
        for psm in (4, 6, 11):
            txt = normalize_digits(_ocr_medical(v, f"--oem 3 --psm {psm}"))
            if txt.strip():
                candidates.append(txt)
        eo = _easyocr_text(v)
        if eo.strip():
            candidates.append(eo)
    if not candidates:
        return ""
    return max(candidates, key=_medical_text_score)


def _parse_ligne_resultat_bio(line: str) -> dict[str, str | None] | None:
    """Une ligne type bilan: nom d'analyse + valeur numerique + unite (+ parfois V.N.)."""
    line = re.sub(r"[·•]", ".", line)
    line = re.sub(r"\.{3,}", " ", line)
    line = re.sub(r"\s+", " ", line).strip()
    if len(line) < 6 or len(line) > 240:
        return None
    if re.search(
        r"\b(demande par|date recu|date reçu|date edit|né\(e\) le|dossier n|nom\s*[:\s]|page\s+\d|qr\s*code)\b",
        line,
        re.I,
    ):
        return None
    if re.match(r"^(EXAMENS?|V\.?\s*N\.?|REFERENCE|UNIT)\s*$", line, re.I):
        return None

    unit_alt = (
        r"(?:Millions/mm3|g\s*%|µg/l|ug/l|µg/L|uIU/mL|uUI/mL|UI/L|mUI/L|nmol/l|µmol/l"
        r"|mmol/l|mg/dl|g/dl|g/l|/mm3|/mL|fL|pg|%|mm3)"
    )

    m = re.match(
        rf"^(.+?)\s+([\d\s]+[,.]?\d*)\s+({unit_alt})\s*(?:\(?\s*V\.?\s*N\.?\s*:\s*([^)]+)\)?)?$",
        line,
        re.I,
    )
    if m:
        param = re.sub(r"[*_]+$", "", m.group(1).strip())
        param = re.sub(r"^[=:.\s|]+", "", param).strip()[:120]
        val = re.sub(r"\s+", "", m.group(2))
        unit = m.group(3).strip()
        vn = (m.group(4) or "").strip()[:150] or None
        if len(param) >= 2 and val:
            return {
                "parametre": param,
                "valeur": val,
                "unite": unit,
                "valeurs_normales": vn,
            }

    m = re.match(
        rf"^(.+?)\s*[.:]\s*([\d\s]+[,.]?\d*)\s+({unit_alt})\b",
        line,
        re.I,
    )
    if m:
        param = re.sub(r"^[=:.\s|]+", "", m.group(1).strip()).strip()[:120]
        val = re.sub(r"\s+", "", m.group(2))
        unit = m.group(3).strip()
        if len(param) >= 2 and val:
            return {
                "parametre": param,
                "valeur": val,
                "unite": unit,
                "valeurs_normales": None,
            }

    # Cas tableau labo: "GLOBULES ROUGES 4.60 Millions/mm3 ... 3.80 à 5.40"
    m = re.match(
        rf"^([A-Za-zÀ-ÿ0-9\-\s/]+?)\s+(\d{{1,4}}[,.]?\d*)\s+({unit_alt})(?:\s+.*?(\d{{1,3}}[,.]?\d*\s*(?:a|à|-)\s*\d{{1,3}}[,.]?\d*))?\s*$",
        line,
        re.I,
    )
    if m:
        param = re.sub(r"^[=:.\s|]+", "", m.group(1).strip()).strip()[:120]
        val = re.sub(r"\s+", "", m.group(2))
        unit = m.group(3).strip()
        vn = (m.group(4) or "").strip()[:150] or None
        if len(param) >= 2 and val:
            return {
                "parametre": param,
                "valeur": val,
                "unite": unit,
                "valeurs_normales": vn,
            }

    m = re.search(
        rf"(?:RESULTAT|R[ée]sultat)\s*[.:]?\s*([\d\s]+[,.]?\d*)\s*({unit_alt})\b",
        line,
        re.I,
    )
    if m:
        before = line[: m.start()].strip()
        param = before.split(":")[-1].strip()[-80:] or "RESULTAT"
        return {
            "parametre": param[:120],
            "valeur": re.sub(r"\s+", "", m.group(1)),
            "unite": m.group(2).strip(),
            "valeurs_normales": None,
        }

    # Lignes avec pourcentage + compte absolu: "NEUTROPHILES 49.1 % | 2 062 /mm3"
    if "|" in line and re.search(r"\d", line) and re.search(unit_alt, line, re.I):
        left = line.split("|")[0].strip()
        if len(left) >= 4:
            return {
                "parametre": left[:120],
                "valeur": "",
                "unite": None,
                "valeurs_normales": None,
                "ligne_complete": line[:200],
            }

    return None


_KNOWN_MEDICAL_LABELS = [
    "globules rouges",
    "hematocrite",
    "hematocrite",
    "hemoglobine",
    "vgm",
    "tcmh",
    "ccmh",
    "globules blancs",
    "neutrophiles",
    "lymphocytes",
    "monocytes",
    "eosinophiles",
    "basophiles",
    "plaquettes",
    "vitesse de sedimentation",
    "crp",
    "glycemie",
    "glucose",
    "uree",
    "creatinine",
    "cholesterol",
    "triglycerides",
    "tsh",
    "vitamine d",
]


def _clean_param_label(raw: str | None) -> str | None:
    if not raw:
        return None
    x = normalize_digits(raw).lower()
    x = re.sub(r"[|`~^_=+]+", " ", x)
    x = re.sub(r"[^a-z0-9àâäçéèêëîïôöùûüÿ/\-%\s]", " ", x)
    x = re.sub(r"\b(pn|nn|n)\b", " ", x)
    x = re.sub(r"(.)\1{4,}", r"\1\1", x)
    x = re.sub(r"\s+", " ", x).strip(" .:-")
    if len(x) < 3:
        return None
    alpha_ratio = sum(1 for c in x if c.isalpha()) / max(len(x), 1)
    if alpha_ratio < 0.4:
        return None
    if fuzz is not None:
        best_label = None
        best_score = 0
        for ref in _KNOWN_MEDICAL_LABELS:
            s = max(fuzz.ratio(x, ref), fuzz.partial_ratio(x, ref))
            if s > best_score:
                best_score = s
                best_label = ref
        if best_label and best_score >= 78:
            x = best_label
    return x


def _post_clean_resultats(rows: list[dict[str, str | None]]) -> list[dict[str, str | None]]:
    cleaned: list[dict[str, str | None]] = []
    seen = set()
    for r in rows:
        label = _clean_param_label(r.get("parametre"))
        if not label:
            continue
        value = (r.get("valeur") or "").strip()
        unit = (r.get("unite") or "").strip()
        if not value and not unit:
            continue
        key = (label, value, unit)
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(
            {
                **r,
                "parametre": label,
                "valeur": value or None,
                "unite": unit or None,
            }
        )
    return cleaned


def _extract_resultats_analyses(body_text: str, full_text: str) -> list[dict[str, str | None]]:
    """Parse les lignes OCR pour extraire le bilan (priorite sur le corps du document)."""
    seen: set = set()
    out: list[dict[str, str | None]] = []
    for block in (body_text, full_text):
        if not block:
            continue
        for raw in block.splitlines():
            row = _parse_ligne_resultat_bio(raw)
            if not row:
                continue
            key = (row.get("parametre"), row.get("valeur"), row.get("ligne_complete"))
            if key in seen:
                continue
            seen.add(key)
            out.append(row)
    return _post_clean_resultats(out)


def _extract_resultats_from_tesseract_data(gray: np.ndarray) -> list[dict[str, str | None]]:
    """
    Extraction complémentaire ligne par ligne via image_to_data.
    Plus robuste que image_to_string sur documents bruités.
    """
    try:
        data = pytesseract.image_to_data(
            gray,
            config="--oem 3 --psm 6",
            lang="fra+eng",
            output_type=pytesseract.Output.DICT,
            timeout=_medical_ocr_timeout_seconds(),
        )
    except Exception:
        return []

    rows: list[tuple[int, int, str]] = []
    n = len(data.get("text", []))
    for i in range(n):
        token = normalize_digits((data["text"][i] or "").strip())
        if not token:
            continue
        try:
            conf = float(data["conf"][i])
        except Exception:
            conf = -1.0
        if conf < 5:
            continue
        top = int(data["top"][i])
        left = int(data["left"][i])
        rows.append((top, left, token))

    if not rows:
        return []

    rows.sort(key=lambda x: (x[0], x[1]))
    lines: list[list[tuple[int, int, str]]] = []
    y_tol = max(10, int(gray.shape[0] * 0.015))
    for r in rows:
        if not lines:
            lines.append([r])
            continue
        prev_y = int(np.median([x[0] for x in lines[-1]]))
        if abs(r[0] - prev_y) <= y_tol:
            lines[-1].append(r)
        else:
            lines.append([r])

    parsed: list[dict[str, str | None]] = []
    for line in lines:
        txt = " ".join(t[2] for t in sorted(line, key=lambda x: x[1]))
        row = _parse_ligne_resultat_bio(txt)
        if row:
            parsed.append(row)
    return _post_clean_resultats(parsed)


def _looks_like_result_number(text: str) -> bool:
    txt = normalize_digits(text or "").strip().replace(",", ".")
    return bool(re.fullmatch(r"[<>]?\d{1,4}(?:\.\d{1,3})?", txt))


def _looks_like_reference_range(text: str) -> bool:
    txt = normalize_digits(text or "").strip().replace(",", ".")
    return bool(re.fullmatch(r"\d{1,4}(?:\.\d{1,3})?\s*(?:-|a|Ã )\s*\d{1,4}(?:\.\d{1,3})?", txt, re.I))


def _normalize_reference_range_token(text: str) -> str | None:
    txt = normalize_digits(text or "").strip().replace(",", ".")
    match = re.fullmatch(
        r"(\d{1,4}(?:\.\d{1,3})?)\s*(?:-|a|Ã )\s*(\d{1,4}(?:\.\d{1,3})?)",
        txt,
        re.I,
    )
    if not match:
        return None

    def fix_number(raw: str) -> str:
        if "." in raw:
            return raw
        if len(raw) == 3:
            return f"{int(raw[:-2])}.{raw[-2:]}"
        return raw

    return f"{fix_number(match.group(1))}-{fix_number(match.group(2))}"


def _clean_unit_token(text: str) -> str | None:
    txt = normalize_digits(text or "").strip()
    txt = txt.replace("I", "l").replace("ı", "l").replace("1", "l")
    txt = re.sub(r"\s+", "", txt)
    low = _strip_accents(txt).lower()
    low = low.replace("muı", "mui").replace("mul", "mui")
    if re.fullmatch(r"g/?l", low):
        return "g/l"
    if re.fullmatch(r"mmol/?l", low):
        return "mmol/l"
    if re.fullmatch(r"m?ui/?l", low):
        return "mUI/l"
    if re.fullmatch(r"u?mol/?l", low):
        return "umol/l"
    if re.fullmatch(r"mg/?d?l", low):
        return txt
    if low in {"%", "g%", "ng/ml", "ui/l"}:
        return txt
    return None


def _infer_unit_for_label(label: str) -> str | None:
    low = _strip_accents(label).lower()
    if any(k in low for k in ("glycem", "cholesterol", "triglycer")):
        return "g/l"
    if "tsh" in low or "thyreostimuline" in low:
        return "mUI/l"
    return None


def _table_label_from_text(text: str) -> str | None:
    compact = _strip_accents(text or "").lower()
    compact = re.sub(r"[^a-z0-9/%\s]", " ", compact)
    compact = re.sub(r"\s+", " ", compact).strip()
    if not compact:
        return None
    if "glycem" in compact:
        return "Glycemie a jeun"
    if "thyreostimuline" in compact or re.search(r"\btsh\b", compact):
        return "Thyreostimuline (TSH)"
    if "cholesterol" in compact and "hdl" in compact:
        return "Cholesterol HDL"
    if "cholesterol" in compact and "ldl" in compact:
        return "Cholesterol LDL"
    if "cholesterol" in compact and "total" in compact and "hdl" not in compact:
        return "Cholesterol total"
    if "triglycer" in compact:
        return "Triglycerides"
    if "uree" in compact:
        return "Uree"
    if "creatinin" in compact:
        return "Creatinine"
    if re.search(r"\bcrp\b", compact):
        return "CRP"
    return None


def _group_ocr_tokens_into_rows(tokens: list[dict[str, object]], image_height: int) -> list[list[dict[str, object]]]:
    if not tokens:
        return []
    y_tol = max(14, int(image_height * 0.012))
    rows: list[list[dict[str, object]]] = []
    for token in sorted(tokens, key=lambda t: (int(t["y"]), int(t["x"]))):
        if not rows:
            rows.append([token])
            continue
        prev_y = int(np.median([int(t["y"]) for t in rows[-1]]))
        if abs(int(token["y"]) - prev_y) <= y_tol:
            rows[-1].append(token)
        else:
            rows.append([token])
    return [sorted(row, key=lambda t: int(t["x"])) for row in rows]


def extract_result_rows_from_medical_ocr_data(gray: np.ndarray) -> list[dict[str, str | None]]:
    """
    Rescue OCR par positions pour les tableaux de biologie.

    Sur plusieurs scans, Tesseract lit le nom de l'examen, la valeur et l'unite sur
    des lignes legerement differentes. Cette passe utilise les coordonnees des mots
    pour associer la colonne de resultat au libelle detecte.
    """
    try:
        data = pytesseract.image_to_data(
            gray,
            config="--oem 3 --psm 6",
            lang="fra+eng",
            output_type=pytesseract.Output.DICT,
            timeout=_medical_ocr_timeout_seconds(),
        )
    except Exception:
        return []

    height, width = gray.shape[:2]
    tokens: list[dict[str, object]] = []
    for i, raw in enumerate(data.get("text", [])):
        text = normalize_digits((raw or "").strip())
        if not text:
            continue
        try:
            conf = float(data["conf"][i])
        except Exception:
            conf = -1.0
        if conf < -1:
            continue
        tokens.append(
            {
                "text": text,
                "x": int(data["left"][i]),
                "y": int(data["top"][i]),
                "w": int(data["width"][i]),
                "h": int(data["height"][i]),
                "conf": conf,
            }
        )

    rows = _group_ocr_tokens_into_rows(tokens, height)
    label_rows: list[tuple[str, int, str]] = []
    for row in rows:
        row_text = " ".join(str(t["text"]) for t in row)
        label = _table_label_from_text(row_text)
        if label:
            label_rows.append((label, int(np.median([int(t["y"]) for t in row])), row_text))

    out: list[dict[str, str | None]] = []
    seen: set[str] = set()
    x_min = int(width * 0.30)
    x_max = int(width * 0.68)

    for label, y, row_text in label_rows:
        if label in seen:
            continue
        window = 170 if "TSH" in label or "Thyreostimuline" in label else 72
        nearby = [
            t
            for t in tokens
            if abs(int(t["y"]) - y) <= window
            and x_min <= int(t["x"]) <= x_max
            and _looks_like_result_number(str(t["text"]))
        ]
        if not nearby:
            continue
        nearby.sort(key=lambda t: (abs(int(t["y"]) - y), int(t["x"])))
        value_token = nearby[0]
        value = normalize_digits(str(value_token["text"])).replace(",", ".").lstrip("<>")

        unit = None
        candidate_units = [
            t
            for t in tokens
            if abs(int(t["y"]) - int(value_token["y"])) <= 18
            and int(t["x"]) >= int(value_token["x"])
            and int(t["x"]) <= int(value_token["x"]) + int(width * 0.16)
        ]
        for token in sorted(candidate_units, key=lambda t: int(t["x"])):
            unit = _clean_unit_token(str(token["text"]))
            if unit:
                break
        unit = unit or _infer_unit_for_label(label)

        reference = None
        ref_candidates = [
            _normalize_reference_range_token(str(t["text"]))
            for t in tokens
            if int(t["x"]) >= int(width * 0.74)
            and abs(int(t["y"]) - int(value_token["y"])) <= 45
            and _looks_like_reference_range(str(t["text"]))
        ]
        if ref_candidates:
            reference = next((ref for ref in ref_candidates if ref), None)

        line_bits = [
            str(t["text"])
            for t in sorted(tokens, key=lambda t: (int(t["y"]), int(t["x"])))
            if abs(int(t["y"]) - y) <= window
            and int(t["x"]) <= int(width * 0.76)
        ]
        out.append(
            {
                "parametre": label,
                "valeur": value,
                "unite": unit,
                "valeurs_normales": reference,
                "ligne_complete": " ".join(line_bits)[:220] or row_text[:220],
            }
        )
        seen.add(label)

    return _post_clean_resultats(out)


def _extract_laboratoire(full_text: str, header_text: str) -> str | None:
    for block in (full_text, header_text):
        m = re.search(
            r"(?:laboratoire|labo\.?|centre\s+(?:de\s+)?(?:analyses|biologie)|polyclinique|clinique|hopital|hôpital)\s*[.:]?\s*([^\n]{5,100})",
            block,
            re.IGNORECASE,
        )
        if m:
            return re.sub(r"\s+", " ", m.group(1).strip())[:120]
    for line in header_text.splitlines():
        ln = line.strip()
        if len(ln) > 14 and re.search(r"[A-Za-zÀ-ÿ]{5,}", ln):
            if not re.match(r"^(date|n°|tel|fax|page)\b", ln, re.I):
                return ln[:120]
    # Fallback "LABORATOIRE D'ANALYSES MEDICALES"
    m2 = re.search(r"(laboratoire\s+d[' ]analyses?\s+m[eé]dicales?)", full_text, re.I)
    if m2:
        return m2.group(1).strip().title()
    return None


def _ocr_medical(img: np.ndarray, config: str) -> str:
    langs = ("fra+eng", "eng") if _medical_fast_ocr_enabled() else ("fra+eng", "eng+fra", "eng")
    for lang in langs:
        try:
            return pytesseract.image_to_string(
                img,
                config=config,
                lang=lang,
                timeout=_medical_ocr_timeout_seconds(),
            )
        except Exception:
            continue
    return ""


def _ocr_medical_best(img: np.ndarray, psm_values: tuple[int, ...] = (6, 4, 11)) -> str:
    candidates: list[str] = []
    variants = _build_ocr_variants(img)
    if _medical_fast_ocr_enabled():
        variants = variants[:2]
        psm_values = tuple(psm_values[:2])
    for v in variants:
        for psm in psm_values:
            txt = normalize_digits(_ocr_medical(v, f"--oem 3 --psm {psm}"))
            if txt.strip():
                candidates.append(txt)
        eo = _easyocr_text(v)
        if eo.strip():
            candidates.append(eo)
    if not candidates:
        return ""
    return max(candidates, key=_medical_text_score)


def extract_combined_ocr_text(image_path: Path) -> str:
    """
    Texte OCR concatene (page entiere + zone analyses) pour envoi a un LLM (ex. Gemini).
    """
    configure_tesseract()
    raw = read_image(image_path)
    image = _enhance_medical_scan(deskew_image(raw))
    gray_full = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    text_full = _ocr_medical_best(gray_full, psm_values=(6, 4, 11))
    text_body = _ocr_body_region(image)
    return f"--- PAGE ---\n{text_full}\n--- ZONE ANALYSES ---\n{text_body}"


def extract_fields_from_medical(
    image_path: Path, debug_dir: Path | None = None
) -> MedicalAnalysisResult:
    configure_tesseract()
    raw = read_image(image_path)
    image = _enhance_medical_scan(deskew_image(raw))

    gray_full = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    text_full = _ocr_medical_best(gray_full, psm_values=(6, 4, 11))
    text_body = _ocr_body_region(image)

    header_roi = crop_relative(image, 0.02, 0.02, 0.98, 0.26)
    header_bin = preprocess_roi(header_roi, upscale=2.0)
    text_header = _ocr_medical_best(header_bin, psm_values=(6, 11))

    resultats = _extract_resultats_analyses(text_body, text_full)
    # Rescue pass: tente de récupérer des lignes de résultats manquées.
    if len(resultats) < 4:
        rescued = _extract_resultats_from_tesseract_data(gray_full)
        if len(rescued) > len(resultats):
            resultats = rescued

    dp, dr = _extract_dates_semantic(text_full)
    ref = _extract_reference(text_full)
    patient = _extract_patient(text_full)
    labo = _extract_laboratoire(text_full, text_header)

    n_res = len(resultats)
    meta = sum(1 for x in (ref, dp, dr, labo, patient) if x)
    if n_res >= 8 and meta >= 2:
        conf = "high"
    elif n_res >= 4 or (n_res >= 2 and meta >= 2):
        conf = "high" if n_res >= 6 else "medium"
    elif n_res >= 1 or meta >= 2:
        conf = "medium"
    else:
        conf = "low"

    if debug_dir:
        debug_dir.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(debug_dir / f"{image_path.stem}_med_aligned.png"), image)

    return MedicalAnalysisResult(
        file_name=image_path.name,
        reference_dossier=ref,
        date_prelevement=dp,
        date_resultat=dr,
        laboratoire=labo,
        patient_nom=patient,
        resultats_analyses=resultats,
        confidence_note=conf,
    )


def extract_fields_from_medical_text(text: str, source_name: str = "document.pdf") -> MedicalAnalysisResult:
    """Extraction medicale depuis le texte natif d'un PDF, sans OCR image."""
    text_full = normalize_digits(text or "")
    text_header = "\n".join(text_full.splitlines()[:30])
    resultats = _extract_resultats_analyses(text_full, text_full)
    dp, dr = _extract_dates_semantic(text_full)
    ref = _extract_reference(text_full)
    patient = _extract_patient(text_full)
    labo = _extract_laboratoire(text_full, text_header)

    n_res = len(resultats)
    meta = sum(1 for x in (ref, dp, dr, labo, patient) if x)
    if n_res >= 8 and meta >= 2:
        conf = "high"
    elif n_res >= 4 or (n_res >= 2 and meta >= 2):
        conf = "high" if n_res >= 6 else "medium"
    elif n_res >= 1 or meta >= 2:
        conf = "medium"
    else:
        conf = "low"

    return MedicalAnalysisResult(
        file_name=source_name,
        reference_dossier=ref,
        date_prelevement=dp,
        date_resultat=dr,
        laboratoire=labo,
        patient_nom=patient,
        resultats_analyses=resultats,
        confidence_note=conf,
    )


def extract_batch_medical(
    input_dir: Path,
    output_json: Path,
    output_csv: Path,
    debug_dir: Path | None = None,
    limit: int | None = None,
    progress_callback: Callable[[int, int, str], None] | None = None,
) -> list[MedicalAnalysisResult]:
    configure_tesseract()
    supported = {".jpg", ".jpeg", ".png", ".tif", ".tiff"}
    images = sorted(
        p for p in input_dir.iterdir() if p.is_file() and p.suffix.lower() in supported
    )
    if limit is not None and limit > 0:
        images = images[:limit]

    results: list[MedicalAnalysisResult] = []
    total = len(images)
    for idx, img_path in enumerate(images, start=1):
        if progress_callback:
            progress_callback(idx, total, img_path.name)
        results.append(extract_fields_from_medical(img_path, debug_dir=debug_dir))

    output_json.parent.mkdir(parents=True, exist_ok=True)
    with output_json.open("w", encoding="utf-8") as f:
        json.dump(
            [
                {
                    "file_name": r.file_name,
                    "resultats_analyses": r.resultats_analyses,
                    "reference_dossier": r.reference_dossier,
                    "date_prelevement": r.date_prelevement,
                    "date_resultat": r.date_resultat,
                    "laboratoire": r.laboratoire,
                    "patient_nom": r.patient_nom,
                    "confidence_note": r.confidence_note,
                }
                for r in results
            ],
            f,
            ensure_ascii=False,
            indent=2,
        )

    with output_csv.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(
            [
                "file_name",
                "resultats_analyses_json",
                "reference_dossier",
                "date_prelevement",
                "date_resultat",
                "laboratoire",
                "patient_nom",
                "confidence_note",
            ]
        )
        for r in results:
            w.writerow(
                [
                    r.file_name,
                    json.dumps(r.resultats_analyses, ensure_ascii=False),
                    r.reference_dossier or "",
                    r.date_prelevement or "",
                    r.date_resultat or "",
                    r.laboratoire or "",
                    r.patient_nom or "",
                    r.confidence_note,
                ]
            )

    return results
