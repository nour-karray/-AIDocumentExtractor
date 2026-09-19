import csv
import json
import os
import re
import shutil
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
import pytesseract
from pytesseract import Output


def _steg_easyocr_enabled() -> bool:
    """EasyOCR est très lent (chargement modèle + CPU). Désactivé par défaut."""
    return os.getenv("STEG_ENABLE_EASYOCR", "").strip().lower() in ("1", "true", "yes", "on")


# Nombre max de variantes binaires par ROI (adaptive / otsu / …) pour limiter les appels Tesseract
_STEG_MAX_VARIANTS = 3


TESSERACT_CANDIDATES = [
    Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe"),
    Path(r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe"),
    Path(r"C:\Program Files\Tesseract\tesseract.exe"),
    Path.home() / r"AppData\Local\Programs\Tesseract-OCR\tesseract.exe",
]


@dataclass
class ExtractionResult:
    file_name: str
    reference: str | None
    montant_a_payer: str | None
    # Date limite ISO YYYY-MM-DD (Priere de payer avant le)
    date_limite_paiement: str | None
    # Periode de consommation (ISO), ex: Du 2024.03.28 Au 2024.06.03
    periode_du: str | None
    periode_au: str | None
    coupon_reference_raw: str | None
    coupon_montant: str | None
    confidence_note: str


ARABIC_DIGIT_MAP = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")


def normalize_digits(text: str) -> str:
    return text.translate(ARABIC_DIGIT_MAP)


def configure_tesseract() -> None:
    """Configure le binaire Tesseract (PATH, TESSERACT_CMD, emplacements Windows courants)."""

    def _use(cmd: str) -> None:
        pytesseract.pytesseract.tesseract_cmd = cmd

    env_cmd = os.getenv("TESSERACT_CMD", "").strip()
    if env_cmd:
        exp = Path(env_cmd).expanduser()
        if exp.exists():
            _use(str(exp))
            return

    cur = str(getattr(pytesseract.pytesseract, "tesseract_cmd", "") or "").strip()
    if cur:
        cexp = Path(cur).expanduser()
        if cexp.exists():
            return

    found = shutil.which("tesseract")
    if found:
        _use(found)
        return

    for candidate in TESSERACT_CANDIDATES:
        if candidate.exists():
            _use(str(candidate))
            return

    raise FileNotFoundError(
        "Tesseract introuvable. Installez Tesseract-OCR (avec langues ara/fra/eng), "
        "ajoutez-le au PATH systeme ou definissez TESSERACT_CMD vers tesseract.exe."
    )


def read_image(image_path: Path) -> np.ndarray:
    image = cv2.imread(str(image_path))
    if image is None:
        raise ValueError(f"Impossible de lire l'image: {image_path}")
    return image


def downscale_if_too_large(image: np.ndarray, max_side: int = 2400) -> np.ndarray:
    """Réduit les très grandes images pour limiter plantages / fuites mémoire Tesseract."""
    h, w = image.shape[:2]
    m = max(h, w)
    if m <= max_side:
        return image
    scale = max_side / float(m)
    nw, nh = max(1, int(w * scale)), max(1, int(h * scale))
    return cv2.resize(image, (nw, nh), interpolation=cv2.INTER_AREA)


def upscale_if_too_small(image: np.ndarray, min_side: int = 1050) -> np.ndarray:
    """Agrandit les photos trop petites : Tesseract gagne en précision sur le texte fin."""
    if image is None or image.size == 0:
        return image
    h, w = image.shape[:2]
    m = min(h, w)
    if m >= min_side:
        return image
    scale = min_side / float(max(m, 1))
    nw, nh = max(1, int(w * scale)), max(1, int(h * scale))
    return cv2.resize(image, (nw, nh), interpolation=cv2.INTER_CUBIC)


def order_points(pts: np.ndarray) -> np.ndarray:
    rect = np.zeros((4, 2), dtype="float32")
    s = pts.sum(axis=1)
    rect[0] = pts[np.argmin(s)]
    rect[2] = pts[np.argmax(s)]
    diff = np.diff(pts, axis=1)
    rect[1] = pts[np.argmin(diff)]
    rect[3] = pts[np.argmax(diff)]
    return rect


def four_point_transform(image: np.ndarray, pts: np.ndarray) -> np.ndarray:
    rect = order_points(pts)
    (tl, tr, br, bl) = rect
    width_a = np.linalg.norm(br - bl)
    width_b = np.linalg.norm(tr - tl)
    max_width = max(int(width_a), int(width_b))
    height_a = np.linalg.norm(tr - br)
    height_b = np.linalg.norm(tl - bl)
    max_height = max(int(height_a), int(height_b))
    dst = np.array(
        [[0, 0], [max_width - 1, 0], [max_width - 1, max_height - 1], [0, max_height - 1]],
        dtype="float32",
    )
    m = cv2.getPerspectiveTransform(rect, dst)
    return cv2.warpPerspective(image, m, (max_width, max_height))


def rectify_document(image: np.ndarray) -> np.ndarray:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    blur = cv2.GaussianBlur(gray, (5, 5), 0)
    edged = cv2.Canny(blur, 50, 150)
    contours, _ = cv2.findContours(edged, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    contours = sorted(contours, key=cv2.contourArea, reverse=True)[:5]
    for c in contours:
        peri = cv2.arcLength(c, True)
        approx = cv2.approxPolyDP(c, 0.02 * peri, True)
        if len(approx) == 4 and cv2.contourArea(approx) > image.shape[0] * image.shape[1] * 0.2:
            return four_point_transform(image, approx.reshape(4, 2).astype("float32"))
    return image


def rectify_document_if_plausible(image: np.ndarray) -> np.ndarray:
    """
    Redresse la perspective si un grand quadrilatère (feuille) est détecté.
    Rejette les warps absurdes (mauvais contour = table, bruit).
    """
    h, w = image.shape[:2]
    if h * w < 180_000:
        return image
    warped = rectify_document(image)
    if warped is image:
        return image
    oh, ow = warped.shape[:2]
    ratio_area = (oh * ow) / float(max(h * w, 1))
    if ratio_area < 0.22 or ratio_area > 1.12:
        return image
    ar = ow / max(oh, 1)
    if ar < 0.58 or ar > 1.78:
        return image
    return warped


_easyocr_reader = None


def _easyocr_read_lines(bgr: np.ndarray) -> str:
    """Texte brut EasyOCR — uniquement si STEG_ENABLE_EASYOCR=1 (sinon no-op, pour la vitesse)."""
    if not _steg_easyocr_enabled():
        return ""
    global _easyocr_reader
    try:
        import easyocr
    except ImportError:
        return ""
    if bgr is None or bgr.size == 0:
        return ""
    try:
        if _easyocr_reader is None:
            _easyocr_reader = easyocr.Reader(["fr", "en"], gpu=False, verbose=False)
        lines = _easyocr_reader.readtext(bgr, detail=0, paragraph=False)
        if isinstance(lines, list):
            return " ".join(str(x) for x in lines if x)
        return str(lines) if lines else ""
    except Exception:
        return ""


def extract_montant_from_red_box(image: np.ndarray) -> str | None:
    """
    STEG affiche souvent le total à payer dans un encadré rouge (bas de page).
    Détection HSV + OCR ciblé — mieux qu’un tableau générique sur photo pliée.
    """
    roi = crop_relative(image, 0.02, 0.38, 0.96, 0.99)
    if roi.size == 0:
        return None
    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    m1 = cv2.inRange(hsv, np.array([0, 60, 40]), np.array([12, 255, 255]))
    m2 = cv2.inRange(hsv, np.array([168, 60, 40]), np.array([180, 255, 255]))
    mask = cv2.bitwise_or(m1, m2)
    mask = cv2.morphologyEx(
        mask, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (7, 7)), iterations=2
    )
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    patches: list[np.ndarray] = []
    rh, rw = roi.shape[:2]
    for c in sorted(contours, key=cv2.contourArea, reverse=True)[:8]:
        if cv2.contourArea(c) < max(400, rh * rw // 800):
            continue
        x, y, cw, ch = cv2.boundingRect(c)
        pad_x = max(6, cw // 6)
        pad_y = max(6, ch // 4)
        x0, y0 = max(0, x - pad_x), max(0, y - pad_y)
        x1, y1 = min(rw, x + cw + pad_x), min(rh, y + ch + pad_y)
        if x1 - x0 < 30 or y1 - y0 < 12:
            continue
        patches.append(roi[y0:y1, x0:x1])

    if not patches:
        patches = [roi]

    found: list[str] = []
    for patch in patches:
        gray = cv2.cvtColor(patch, cv2.COLOR_BGR2GRAY)
        sc = cv2.resize(gray, (int(gray.shape[1] * 2.2), int(gray.shape[0] * 2.2)), interpolation=cv2.INTER_CUBIC)
        for img in (gray, sc):
            txt = normalize_digits(
                ocr_text(img, config="--oem 3 --psm 7 -c tessedit_char_whitelist=0123456789,.", lang="eng")
            )
            for a in parse_amount_candidates(txt):
                if is_plausible_steg_line_amount(a):
                    found.append(a)
            txt2 = normalize_digits(ocr_text(img, config="--oem 3 --psm 6", lang="eng+ara"))
            for a in parse_amount_candidates(txt2):
                if is_plausible_steg_line_amount(a):
                    found.append(a)
    if not found:
        return None
    return max(found, key=amount_to_millimes)


def deskew_image(
    image: np.ndarray,
    max_angle: float = 15.0,
    min_angle: float = 0.35,
) -> np.ndarray:
    """
    Corrige une inclinaison fine (skew) apres rotation 0/90/180/270.
    Methode: minAreaRect sur le masque du texte (lignes horizontales dominantes).
    """
    if image is None or image.size == 0:
        return image
    h, w = image.shape[:2]
    if h < 50 or w < 50:
        return image

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (3, 3), 0)
    # Texte en blanc sur fond noir pour regrouper les pixels utiles
    inv = cv2.bitwise_not(gray)
    _, thresh = cv2.threshold(inv, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
    # Dilatation horizontale pour lier les caracteres en lignes
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (max(15, w // 40), 3))
    dilated = cv2.dilate(thresh, kernel, iterations=2)

    coords = np.column_stack(np.where(dilated > 0))
    if len(coords) < max(500, (h * w) // 200):
        return image

    rect = cv2.minAreaRect(coords)
    angle = rect[-1]
    if angle < -45:
        skew = 90 + angle
    else:
        skew = -angle

    if abs(skew) < min_angle or abs(skew) > max_angle:
        return image

    center = (w / 2.0, h / 2.0)
    M = cv2.getRotationMatrix2D(center, skew, 1.0)
    cos = abs(M[0, 0])
    sin = abs(M[0, 1])
    nW = int(h * sin + w * cos)
    nH = int(h * cos + w * sin)
    M[0, 2] += nW / 2 - center[0]
    M[1, 2] += nH / 2 - center[1]
    return cv2.warpAffine(
        image,
        M,
        (nW, nH),
        flags=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_REPLICATE,
    )


def enhance_steg_scan(image: np.ndarray) -> np.ndarray:
    """
    Contraste adaptatif (CLAHE sur LAB) pour photos STEG (faible lumière, papier jauni).
    OpenCV uniquement, pas de dépendance supplémentaire.
    """
    if image is None or image.size == 0 or image.ndim < 3:
        return image
    try:
        lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)
        l_ch, a_ch, b_ch = cv2.split(lab)
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        l2 = clahe.apply(l_ch)
        out = cv2.cvtColor(cv2.merge([l2, a_ch, b_ch]), cv2.COLOR_LAB2BGR)
        # Léger unsharp pour photos floues (mobile) sans saturer le bruit
        try:
            blur = cv2.GaussianBlur(out, (0, 0), 1.0)
            out = cv2.addWeighted(out, 1.22, blur, -0.22, 0)
            out = np.clip(out, 0, 255).astype(np.uint8)
        except Exception:
            pass
        return out
    except Exception:
        return image


def preprocess_roi(roi: np.ndarray, upscale: float = 2.0) -> np.ndarray:
    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape
    resized = cv2.resize(gray, (int(w * upscale), int(h * upscale)), interpolation=cv2.INTER_CUBIC)
    denoised = cv2.GaussianBlur(resized, (3, 3), 0)
    bin_img = cv2.adaptiveThreshold(
        denoised, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 35, 15
    )
    return bin_img


def generate_preprocessed_variants(roi: np.ndarray, upscale: float = 2.0) -> list[np.ndarray]:
    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape
    resized = cv2.resize(gray, (int(w * upscale), int(h * upscale)), interpolation=cv2.INTER_CUBIC)
    blur = cv2.GaussianBlur(resized, (3, 3), 0)
    adaptive = cv2.adaptiveThreshold(
        blur, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 35, 15
    )
    _, otsu = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    adaptive_inv = cv2.bitwise_not(adaptive)
    return [adaptive, otsu, adaptive_inv]


def clean_amount(raw: str) -> str | None:
    candidates = parse_amount_candidates(raw)
    if not candidates:
        return None
    return choose_best_amount(candidates)


def parse_amount_candidates(text: str) -> list[str]:
    compact = normalize_digits(text).replace(" ", "").replace("O", "0").replace(".", ",")
    # Extract well-formed Tunisian amount tokens and avoid greedy merged strings.
    comma_amounts = re.findall(r"\d{1,7},\d{3}", compact)
    ints = re.findall(r"(?<!\d)\d{2,7}(?!\d)", compact)
    combined: list[str] = []
    for token in comma_amounts + ints:
        token = token.strip(".,")
        if not token:
            continue
        combined.append(token)
    # Keep order while removing duplicates
    seen = set()
    cleaned: list[str] = []
    for c in combined:
        if c not in seen:
            seen.add(c)
            cleaned.append(c)
    return cleaned


def choose_best_amount(candidates: list[str]) -> str | None:
    if not candidates:
        return None
    # Prefer amounts in Tunisian bill style: integer + 3 decimals (e.g. 222,000)
    preferred = [c for c in candidates if re.fullmatch(r"\d{1,6},\d{3}", c)]
    if preferred:
        # Sur une même zone OCR, le « montant à payer » est souvent le plus élevé.
        return max(preferred, key=amount_to_millimes)
    # Fallback on reasonable-size integers
    ints = [c for c in candidates if re.fullmatch(r"\d{2,7}", c)]
    if ints:
        return max(ints, key=len)
    return max(candidates, key=len)


def amount_to_millimes(value: str) -> int:
    if "," in value:
        left, right = value.split(",", 1)
        right = (right + "000")[:3]
        return int(left) * 1000 + int(right)
    return int(value) * 1000


def choose_payment_amount(candidates: list[str]) -> str | None:
    if not candidates:
        return None
    strong = [c for c in candidates if re.fullmatch(r"\d{1,7},\d{3}", c)]
    if strong:
        # In payment zone, prefer the strongest amount; if several, take highest.
        return max(strong, key=amount_to_millimes)
    best = choose_best_amount(candidates)
    if best and re.fullmatch(r"\d{4,7}", best):
        # OCR sometimes drops comma; restore Tunisian style (xxx,xxx)
        return f"{best[:-3]},{best[-3:]}"
    return best


def is_strong_amount(value: str | None) -> bool:
    return bool(value and re.fullmatch(r"\d{1,6},\d{3}", value))


def is_plausible_steg_line_amount(value: str | None) -> bool:
    """Evite les faux positifs (dates collees, bruit OCR). Montants STEG: au plus 4 chiffres avant la virgule (ex: 1200,000 ou 777,000)."""
    if not value:
        return False
    if not re.fullmatch(r"\d{1,4},\d{3}", value):
        return False
    left, _ = value.split(",", 1)
    if len(left) > 1 and left.startswith("0"):
        return False
    try:
        return int(left) <= 9999
    except ValueError:
        return False


def format_reference_from_digits(digits: str) -> str | None:
    if len(digits) != 9:
        return None
    return f"{digits[:5]} {digits[5:8]} {digits[8:]}"


def derive_reference_from_footer_compact(coupon_reference: str) -> str | None:
    digits = re.sub(r"\D", "", coupon_reference)
    if not digits:
        return None

    if digits.startswith("000006"):
        # Regle demandee: commencer a la 8eme position.
        tail = digits[7:]
        if len(tail) == 8:
            tail = tail + "0"
        if len(tail) >= 9:
            return format_reference_from_digits(tail[:9])

        # Fallback: apres le prefixe 000006
        after_prefix = digits[6:]
        if len(after_prefix) >= 9:
            return format_reference_from_digits(after_prefix[:9])

    if len(digits) >= 9:
        return format_reference_from_digits(digits[-9:])
    return None


def extract_reference(text: str) -> str | None:
    text = normalize_digits(text)
    normalized = re.sub(r"[^\d\s]", " ", text)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    spaced_patterns = re.findall(r"\d{5}\s+\d{3}\s+\d", normalized)
    if spaced_patterns:
        return spaced_patterns[0]

    compact_digits = re.sub(r"\D", "", normalized)
    if len(compact_digits) >= 9:
        return format_reference_from_digits(compact_digits[:9])
    return None


def compact_to_spaced_reference(digits: str) -> str | None:
    if len(digits) < 9:
        return None
    digits = digits[:9]
    return f"{digits[:5]} {digits[5:8]} {digits[8]}"


def extract_reference_candidates_from_text(text: str) -> list[str]:
    text = normalize_digits(text)
    candidates: list[str] = []
    normalized = re.sub(r"[^\d\s]", " ", text)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    candidates.extend(re.findall(r"\d{5}\s+\d{3}\s+\d", normalized))
    compact = re.sub(r"\D", "", text)
    if len(compact) == 9:
        ref = compact_to_spaced_reference(compact)
        if ref:
            candidates.append(ref)
    elif 9 < len(compact) <= 12:
        # OCR peut coller 1-3 chiffres parasites avant/apres la reference.
        for i in range(0, len(compact) - 9 + 1):
            ref = compact_to_spaced_reference(compact[i : i + 9])
            if ref:
                candidates.append(ref)
    elif len(compact) > 12:
        # Texte trop long: limiter aux bords pour eviter trop de faux positifs.
        for chunk in (compact[:9], compact[-9:]):
            ref = compact_to_spaced_reference(chunk)
            if ref:
                candidates.append(ref)
    return candidates


def _extract_steg_text_hints(image: np.ndarray) -> str:
    """OCR global rapide sur zones-clés STEG (haut + recap bas)."""
    parts: list[str] = []
    rois = [
        (0.02, 0.02, 0.98, 0.40),  # en-tête: référence/date
        (0.02, 0.40, 0.98, 0.90),  # recap + montant/date limite
    ]
    for x1, y1, x2, y2 in rois:
        roi = crop_relative(image, x1, y1, x2, y2)
        if roi.size == 0:
            continue
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        h, w = gray.shape[:2]
        scaled = cv2.resize(gray, (int(w * 1.7), int(h * 1.7)), interpolation=cv2.INTER_CUBIC)
        for img, psm in ((gray, 6), (scaled, 6), (scaled, 11)):
            txt = normalize_digits(ocr_text(img, config=f"--oem 3 --psm {psm}", lang="eng+ara"))
            if txt.strip():
                parts.append(txt)
    return "\n".join(parts)


def _extract_amount_from_text_hints(text: str) -> str | None:
    t = normalize_digits(text).lower()
    t = re.sub(r"(\d{1,4})\s+(\d{3})(?!\d)", r"\1,\2", t)
    patterns = [
        r"montant\s*[àa]?\s*payer[^\d]{0,90}(\d{1,4},\d{3})",
        r"المبلغ\s*المطلوب[^\d]{0,90}(\d{1,4},\d{3})",
        r"\(\s*19\s*\)[^\d]{0,90}(\d{1,4},\d{3})",
    ]
    cands: list[str] = []
    for pat in patterns:
        for m in re.finditer(pat, t, re.IGNORECASE | re.DOTALL):
            v = m.group(1)
            if is_plausible_steg_line_amount(v):
                cands.append(v)
    return max(cands, key=amount_to_millimes) if cands else None


def vote_best_reference(candidates: list[str]) -> str | None:
    if not candidates:
        return None
    cleaned = [re.sub(r"\s+", " ", c.strip()) for c in candidates if c.strip()]
    if not cleaned:
        return None
    counts = Counter(cleaned)
    return counts.most_common(1)[0][0]


def extract_periode_du_au(
    image: np.ndarray,
    exclude_iso_dates: set[str] | None = None,
) -> tuple[str | None, str | None]:
    """
    Période de consommation STEG (Du … Au …).
    ``exclude_iso_dates`` : exclure la date limite de paiement (sinon confondue avec « Au »).
    """
    skip = exclude_iso_dates or set()
    rois = [
        (0.00, 0.74, 1.00, 0.96),
        (0.00, 0.64, 1.00, 0.90),
        (0.02, 0.22, 0.98, 0.58),
        (0.02, 0.28, 0.98, 0.72),
        (0.02, 0.35, 0.98, 0.78),
    ]
    texts: list[str] = []
    for x1, y1, x2, y2 in rois:
        roi = crop_relative(image, x1, y1, x2, y2)
        if roi.size == 0:
            continue
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        h, w = gray.shape[:2]
        scaled = cv2.resize(gray, (int(w * 2.0), int(h * 2.0)), interpolation=cv2.INTER_CUBIC)
        for img, psm in ((gray, 6), (scaled, 6), (scaled, 11)):
            texts.append(normalize_digits(ocr_text(img, config=f"--oem 3 --psm {psm}", lang="eng+ara")))
        for variant in generate_preprocessed_variants(roi, upscale=2.1)[:3]:
            for psm in (6, 11):
                texts.append(
                    normalize_digits(ocr_text(variant, config=f"--oem 3 --psm {psm}", lang="eng+ara"))
                )

    date_pat = r"(20\d{2})[.\-/](\d{1,2})[.\-/](\d{1,2})"

    def _to_iso(m: re.Match) -> str | None:
        return _validate_ymd(int(m.group(1)), int(m.group(2)), int(m.group(3)))

    du_candidates: list[str] = []
    au_candidates: list[str] = []
    kw_period = re.compile(
        r"consomm|factur|période|periode|lecture|kwh|du\s|de\s|من|إلى|الفترة",
        re.IGNORECASE,
    )

    for txt in texts:
        t = re.sub(r"\s+", " ", txt)
        for line in re.split(r"[\n|]", t):
            line = line.strip()
            if len(line) < 12 or not kw_period.search(line):
                continue
            line_dates: list[str] = []
            for m in re.finditer(date_pat, line):
                d = _to_iso(m)
                if d and d not in skip:
                    line_dates.append(d)
            u = sorted(set(line_dates))
            if len(u) >= 2:
                du_candidates.append(u[0])
                au_candidates.append(u[-1])

        for m in re.finditer(rf"{date_pat}\s*[-–—/]+\s*{date_pat}", t):
            inner = list(re.finditer(date_pat, m.group(0)))
            if len(inner) >= 2:
                d_a = _to_iso(inner[0])
                d_b = _to_iso(inner[1])
                if d_a and d_b and d_a not in skip and d_b not in skip:
                    first, last = (d_a, d_b) if d_a <= d_b else (d_b, d_a)
                    du_candidates.append(first)
                    au_candidates.append(last)

        for m in re.finditer(rf"(?:du|de)\s*[:]?\s*{date_pat}", t, re.IGNORECASE):
            d = _to_iso(m)
            if d and d not in skip:
                du_candidates.append(d)
        for m in re.finditer(rf"(?:\bau\b)\s*[:]?\s*{date_pat}", t, re.IGNORECASE):
            d = _to_iso(m)
            if d and d not in skip:
                au_candidates.append(d)

        inv = re.search(
            rf"\bau\b\s*[:]?\s*{date_pat}.{{0,55}}(?:du|de)\s*[:]?\s*{date_pat}",
            t,
            re.IGNORECASE,
        )
        if inv:
            ds = list(re.finditer(date_pat, inv.group(0)))
            if len(ds) >= 2:
                d_au = _to_iso(ds[0])
                d_du = _to_iso(ds[1])
                if d_du and d_du not in skip:
                    du_candidates.append(d_du)
                if d_au and d_au not in skip:
                    au_candidates.append(d_au)

    periode_du = Counter(du_candidates).most_common(1)[0][0] if du_candidates else None
    periode_au = Counter(au_candidates).most_common(1)[0][0] if au_candidates else None

    pool_dates: list[str] = []
    for txt in texts:
        for m in re.finditer(date_pat, txt):
            d = _to_iso(m)
            if d and d not in skip:
                pool_dates.append(d)
    pool = sorted(set(pool_dates))

    if periode_au and not periode_du:
        before = [d for d in pool if d < periode_au]
        if before:
            periode_du = max(before)
    if periode_du and not periode_au:
        after = [d for d in pool if d > periode_du and d not in skip]
        if after:
            periode_au = min(after)

    if not periode_du and not periode_au and len(pool) >= 2:
        periode_du, periode_au = pool[0], pool[-1]
    elif not periode_du and periode_au:
        before = [d for d in pool if d < periode_au]
        if before:
            periode_du = max(before)
    elif not periode_au and periode_du:
        after = [d for d in pool if d > periode_du]
        if after:
            cand = [d for d in after if d not in skip]
            if cand:
                periode_au = min(cand)

    if periode_du and periode_au and periode_du > periode_au:
        periode_du, periode_au = periode_au, periode_du

    return periode_du, periode_au


def ocr_text(image: np.ndarray, config: str, lang: str = "eng") -> str:
    return pytesseract.image_to_string(image, config=config, lang=lang)


def crop_relative(image: np.ndarray, x1: float, y1: float, x2: float, y2: float) -> np.ndarray:
    h, w = image.shape[:2]
    xa, ya = int(w * x1), int(h * y1)
    xb, yb = int(w * x2), int(h * y2)
    return image[ya:yb, xa:xb]


def _validate_ymd(y: int, mo: int, d: int) -> str | None:
    if mo < 1 or mo > 12 or d < 1 or d > 31 or y < 2000 or y > 2099:
        return None
    return f"{y:04d}-{mo:02d}-{d:02d}"


def _is_plausible_steg_deadline_year(y: int) -> bool:
    """Filtre le bruit OCR (ex. 2000-xx) sur les factures recentes STEG."""
    return 2012 <= y <= 2038


def _filter_plausible_deadline(iso: str | None) -> str | None:
    if not iso:
        return None
    try:
        y = int(iso[:4])
    except ValueError:
        return None
    return iso if _is_plausible_steg_deadline_year(y) else None


def normalize_date_yyyy_mm_dd(fragment: str) -> str | None:
    """Convertit 2025.10.27, 2025-10-27, 2025/10/27, 2025 10 27, 20251027 en YYYY-MM-DD."""
    fragment = normalize_digits(re.sub(r"\s+", "", fragment.strip()))
    m = re.search(r"(20\d{2})[.\-/](\d{1,2})[.\-/](\d{1,2})", fragment)
    if m:
        return _validate_ymd(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    m = re.match(r"^(20\d{2})(\d{2})(\d{2})$", fragment)
    if m:
        return _validate_ymd(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    return None


def try_parse_date_in_string(s: str) -> str | None:
    """Toutes les formes usuelles STEG / OCR sur une ligne ou un bloc."""
    s = normalize_digits(s)
    for m in re.finditer(
        r"(20\d{2})\s*[.\s,/\-]\s*(\d{1,2})\s*[.\s,/\-]\s*(\d{1,2})", s
    ):
        d = _validate_ymd(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        if d:
            return d
    m = re.search(r"(20\d{2})(\d{2})(\d{2})(?!\d)", re.sub(r"\s+", "", s))
    if m:
        return _validate_ymd(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    return None


def parse_steg_payment_deadline_from_text(text: str) -> str | None:
    """Extrait la date apres les libelles STEG (FR/AR)."""
    text = normalize_digits(text)
    tnorm = re.sub(r"\s+", " ", text)
    tcompact = re.sub(r"\s+", "", tnorm.lower())
    patterns = [
        r"pri[eèéê]re\s+de\s+payer\s+avant\s+le\D{0,60}",
        r"payer\s+avant\s+le\D{0,50}",
        r"avant\s+le\D{0,40}",
        r"payeravantle\D{0,40}",
    ]
    for pat in patterns:
        m = re.search(pat, tnorm, re.IGNORECASE)
        if m:
            tail = tnorm[m.end() : m.end() + 45]
            d = _filter_plausible_deadline(try_parse_date_in_string(tail))
            if d:
                return d
            d = _filter_plausible_deadline(try_parse_date_in_string(m.group(0)))
            if d:
                return d
    m = re.search(
        r"payeravantle\D{0,35}",
        tcompact,
        re.IGNORECASE,
    )
    if m:
        d = _filter_plausible_deadline(try_parse_date_in_string(m.group(0)))
        if d:
            return d
    for m in re.finditer(
        r"(20\d{2})\s*[.\s\-/]\s*(\d{1,2})\s*[.\s\-/]\s*(\d{1,2})", tnorm
    ):
        start = max(0, m.start() - 120)
        window = tnorm[start : m.end() + 8]
        if re.search(
            r"payer|avant|pri[eèéê]re|الدفع|قبل|دفع|le\s*$",
            window,
            re.IGNORECASE,
        ):
            d = _filter_plausible_deadline(
                _validate_ymd(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            )
            if d:
                return d
    if re.search(r"الدفع|قبل", text, re.IGNORECASE):
        d = try_parse_date_in_string(text)
        if d:
            return _filter_plausible_deadline(d)
    # Ne pas utiliser "payer" seul: matche "Montant a payer" et renvoie la 1re date de la facture.
    return None


def _words_to_lines(
    words: list[tuple[str, int, int, int, int]], img_h: int
) -> list[list[tuple[str, int, int, int, int]]]:
    if not words:
        return []
    y_tol = max(14, int(0.02 * img_h))
    words_sorted = sorted(words, key=lambda w: w[2] + w[4] // 2)
    lines: list[list[tuple[str, int, int, int, int]]] = []
    current: list[tuple[str, int, int, int, int]] = []
    ref_y = -10_000
    for w in words_sorted:
        yc = w[2] + w[4] // 2
        if not current or abs(yc - ref_y) <= y_tol:
            current.append(w)
            ref_y = sum(w[2] + w[4] // 2 for w in current) // len(current)
        else:
            lines.append(sorted(current, key=lambda x: x[1]))
            current = [w]
            ref_y = yc
    if current:
        lines.append(sorted(current, key=lambda x: x[1]))
    return lines


def _line_triggers_payment_deadline_context(line_text: str) -> bool:
    lt = line_text.lower()
    # STEG etiquette (19) = montant a payer; souvent pres de la date limite sur la meme zone
    if re.search(
        r"\(\s*19\s*\)|payer|pav|avant|قبل|الدفع|المطلوب|pri[eèéê]?re|priere|plait|prier",
        lt,
        re.I,
    ):
        return True
    # OCR: « Montont & payer », « Montant a payer »
    if re.search(r"mont\w*", lt, re.I) and re.search(r"pay|pav", lt, re.I):
        return True
    return False


def extract_date_below_arabic_before_keyword(gray: np.ndarray) -> str | None:
    """
    Sur STEG, apres « الرجاء الدفع قبل » la date est souvent sur la ligne du dessous (gros chiffres).
    """
    rh, rw = gray.shape[:2]
    data = pytesseract.image_to_data(
        gray,
        lang="eng+ara",
        config="--oem 3 --psm 6",
        output_type=Output.DICT,
    )
    hits: list[tuple[int, int, int, int]] = []
    n = len(data["text"])
    for i in range(n):
        token = (data["text"][i] or "").strip()
        if not token:
            continue
        try:
            conf = float(data["conf"][i])
        except ValueError:
            conf = -1.0
        if conf < 0:
            continue
        if re.search(r"قبل|الدفع", token):
            x = int(data["left"][i])
            y = int(data["top"][i])
            ww = int(data["width"][i])
            hh = int(data["height"][i])
            hits.append((x, y, ww, hh))
    if not hits:
        return None
    found: list[str] = []
    for kx, ky, kw, kh in hits:
        y_line_bottom = ky + kh
        x_center = kx + kw // 2
        # Bande verticale elargie (date parfois 1–2 lignes sous l’arabe, ou bruit OCR)
        y_min = max(0, ky - int(0.10 * rh))
        y_max = min(rh, y_line_bottom + int(0.14 * rh))
        row_tokens: list[tuple[int, str]] = []
        for i in range(n):
            token = normalize_digits((data["text"][i] or "").strip())
            if not token:
                continue
            try:
                conf = float(data["conf"][i])
            except ValueError:
                conf = -1.0
            if conf < 5:
                continue
            x = int(data["left"][i])
            y = int(data["top"][i])
            ww = int(data["width"][i])
            hh = int(data["height"][i])
            yc = y + hh // 2
            if yc < y_min or yc > y_max:
                continue
            if abs((x + ww // 2) - x_center) > int(0.48 * rw):
                continue
            if re.search(r"\d", token):
                row_tokens.append((x, token))
        row_tokens.sort(key=lambda t: t[0])
        merged = " ".join(t[1] for t in row_tokens)
        d = _filter_plausible_deadline(try_parse_date_in_string(merged))
        if d:
            found.append(d)
        d = _filter_plausible_deadline(normalize_date_yyyy_mm_dd(re.sub(r"\s+", "", merged)))
        if d:
            found.append(d)
        # Chaine compacte (OCR coupe parfois 2022.08.29)
        compact = re.sub(r"[^\d]", "", merged)
        if len(compact) >= 8:
            m8 = re.match(r"^(20\d{2})(\d{2})(\d{2})", compact)
            if m8:
                d8 = _filter_plausible_deadline(
                    _validate_ymd(int(m8.group(1)), int(m8.group(2)), int(m8.group(3)))
                )
                if d8:
                    found.append(d8)
    if found:
        return Counter(found).most_common(1)[0][0]
    return None


def extract_date_limite_from_ocr_data(image: np.ndarray) -> str | None:
    """
    Boites de mots Tesseract: repere payer / avant / montant...payer et cherche
    la date sur la meme ligne, les lignes voisines (souvent au-dessus sur STEG).
    ROI a partir de ~22 % hauteur: la date limite est en bas; on evite image_to_data sur tout le haut vide.
    """
    roi = crop_relative(image, 0.02, 0.22, 0.98, 0.94)
    if roi.size == 0:
        return None
    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    rh = gray.shape[0]
    data = pytesseract.image_to_data(
        gray,
        lang="eng+ara",
        config="--oem 3 --psm 6",
        output_type=Output.DICT,
    )
    words: list[tuple[str, int, int, int, int]] = []
    n = len(data["text"])
    for i in range(n):
        token = normalize_digits((data["text"][i] or "").strip())
        if not token:
            continue
        try:
            conf = float(data["conf"][i])
        except ValueError:
            conf = -1.0
        if conf < 0:
            continue
        x = int(data["left"][i])
        y = int(data["top"][i])
        ww = int(data["width"][i])
        hh = int(data["height"][i])
        words.append((token, x, y, ww, hh))

    lines = _words_to_lines(words, rh)
    found: list[str] = []
    for li, line in enumerate(lines):
        line_text = " ".join(w[0] for w in line)
        if not _line_triggers_payment_deadline_context(line_text):
            continue
        window_parts: list[str] = []
        for dj in (-2, -1, 0, 1, 2):
            j = li + dj
            if 0 <= j < len(lines):
                window_parts.append(" ".join(w[0] for w in lines[j]))
        merged = " | ".join(window_parts)
        d = _filter_plausible_deadline(try_parse_date_in_string(merged))
        if d:
            found.append(d)
        d = parse_steg_payment_deadline_from_text(merged)
        if d:
            found.append(d)

        # Bande au-dessus de la ligne (souvent encadre « Priere de payer avant le » + date)
        yt = min(w[2] for w in line)
        hpad = max(100, int(0.14 * rh))
        y0 = max(0, yt - hpad)
        strip = gray[y0 : max(y0 + 1, yt + 20), :]
        if strip.shape[0] >= 15 and strip.shape[1] >= 60:
            wst = strip.shape[1]
            strip_right = strip[:, int(wst * 0.30) :]
            strip_big = cv2.resize(
                strip_right,
                (int(strip_right.shape[1] * 1.9), int(strip_right.shape[0] * 1.9)),
                interpolation=cv2.INTER_CUBIC,
            )
            tx = ocr_text(strip_big, config="--oem 3 --psm 6", lang="eng+ara")
            if re.search(r"avant|payer|pri|قبل|الدفع", tx, re.I):
                d2 = parse_steg_payment_deadline_from_text(tx)
                if d2:
                    found.append(d2)
                d3 = _filter_plausible_deadline(try_parse_date_in_string(tx))
                if d3:
                    found.append(d3)
    if found:
        plausible = [x for x in found if _filter_plausible_deadline(x)]
        if plausible:
            return Counter(plausible).most_common(1)[0][0]

    d_ar = extract_date_below_arabic_before_keyword(gray)
    if d_ar:
        return _filter_plausible_deadline(d_ar)
    return None


def extract_date_limite_footer_band(image: np.ndarray) -> str | None:
    """
    Encadre STEG en bas de facture (au-dessus du talon / ligne pointillee).
    Version legere: peu de passes OCR, sortie des qu'une date plausible est trouvee.
    """
    roi = crop_relative(image, 0.02, 0.38, 0.98, 0.82)
    if roi.size == 0:
        return None
    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)

    d_ar = extract_date_below_arabic_before_keyword(gray)
    if d_ar:
        fd = _filter_plausible_deadline(d_ar)
        if fd:
            return fd

    h, w = gray.shape[:2]
    scaled = cv2.resize(gray, (int(w * 2.0), int(h * 2.0)), interpolation=cv2.INTER_CUBIC)

    for img in (gray, scaled):
        txt = normalize_digits(ocr_text(img, config="--oem 3 --psm 6", lang="eng+ara"))
        d = parse_steg_payment_deadline_from_text(txt)
        if d:
            return d
        if re.search(
            r"avant|قبل|pri[eèéê]?re|الدفع|الرجاء|payer\s+avant",
            txt,
            re.IGNORECASE,
        ):
            d2 = _filter_plausible_deadline(try_parse_date_in_string(txt))
            if d2:
                return d2

    tw = normalize_digits(
        ocr_text(
            scaled,
            config="--oem 3 --psm 7 -c tessedit_char_whitelist=0123456789.-/ ",
            lang="eng",
        )
    )
    if re.search(r"20\d{2}", tw):
        d3 = _filter_plausible_deadline(
            normalize_date_yyyy_mm_dd(re.sub(r"\s+", "", tw))
        )
        if d3:
            return d3
        d3b = _filter_plausible_deadline(try_parse_date_in_string(tw))
        if d3b:
            return d3b

    bin_one = preprocess_roi(roi, upscale=2.0)
    txt_b = normalize_digits(ocr_text(bin_one, config="--oem 3 --psm 6", lang="eng+ara"))
    d4 = parse_steg_payment_deadline_from_text(txt_b)
    if d4:
        return d4
    return None


def extract_date_limite_sparse_multiline(
    image: np.ndarray, y1: float = 0.02, y2: float = 0.58
) -> str | None:
    """
    PSM 11 (sparse): parcourt des lignes voisines; garde une date seulement si
    le bloc contient aussi payer/avant/قبل (evite dates de periode de facturation).
    Utiliser y1,y2 ~ (0.40, 0.82) pour la bande bas de page.
    """
    roi = crop_relative(image, 0.02, y1, 0.98, y2)
    if roi.size == 0:
        return None
    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape
    scaled = cv2.resize(gray, (int(w * 1.5), int(h * 1.5)), interpolation=cv2.INTER_CUBIC)
    hits: list[str] = []
    for variant in (scaled,):  # une passe: image agrandie (meilleur compromis vitesse/qualite)
        txt = normalize_digits(ocr_text(variant, config="--oem 3 --psm 11", lang="eng+ara"))
        lines = [ln.strip() for ln in txt.splitlines() if ln.strip()]
        for i, _ in enumerate(lines):
            block = " ".join(lines[max(0, i - 1) : min(len(lines), i + 3)])
            if not re.search(
                r"payer|avant|قبل|الدفع|pri[eèéê]?re|plait|prier|الرجاء",
                block,
                re.IGNORECASE,
            ):
                continue
            d = parse_steg_payment_deadline_from_text(block)
            if d:
                hits.append(d)
            d2 = _filter_plausible_deadline(try_parse_date_in_string(block))
            if d2:
                hits.append(d2)
    if hits:
        return Counter(hits).most_common(1)[0][0]
    return None


def extract_date_limite_paiement(image: np.ndarray) -> str | None:
    """Date limite (Priere de payer avant le / الرجاء الدفع قبل), sortie YYYY-MM-DD."""
    d_foot = extract_date_limite_footer_band(image)
    if d_foot:
        return d_foot

    d0 = extract_date_limite_from_ocr_data(image)
    if d0:
        return d0

    found: list[str] = []
    rois_fast = [
        (0.02, 0.38, 0.98, 0.82),
        (0.45, 0.04, 0.99, 0.52),
        (0.02, 0.04, 0.55, 0.48),
    ]
    for x1, y1, x2, y2 in rois_fast:
        roi = crop_relative(image, x1, y1, x2, y2)
        if roi.size == 0:
            continue
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        h, w = gray.shape
        scaled = cv2.resize(gray, (int(w * 1.6), int(h * 1.6)), interpolation=cv2.INTER_CUBIC)
        for img_variant in (gray, scaled):
            txt = ocr_text(img_variant, config="--oem 3 --psm 6", lang="eng+ara")
            d = parse_steg_payment_deadline_from_text(txt)
            if d:
                found.append(d)
            d = _filter_plausible_deadline(try_parse_date_in_string(txt))
            if d and re.search(
                r"payer|avant|قبل|الدفع|pri[eèéê]?re", txt, re.IGNORECASE
            ):
                found.append(d)

    d_sparse_low = extract_date_limite_sparse_multiline(image, y1=0.35, y2=0.84)
    if d_sparse_low:
        found.append(d_sparse_low)

    if found:
        plausible = [x for x in found if _filter_plausible_deadline(x)]
        if plausible:
            return Counter(plausible).most_common(1)[0][0]
    for y_top, y_bot in ((0.38, 0.82), (0.03, 0.55)):
        roi = crop_relative(image, 0.02, y_top, 0.98, y_bot)
        if roi.size == 0:
            continue
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        d_last = parse_steg_payment_deadline_from_text(
            ocr_text(gray, config="--oem 3 --psm 6", lang="eng+ara")
        )
        if d_last:
            return d_last
    return None


def rotate_image(image: np.ndarray, angle: int) -> np.ndarray:
    if angle == 0:
        return image
    if angle == 90:
        return cv2.rotate(image, cv2.ROTATE_90_CLOCKWISE)
    if angle == 180:
        return cv2.rotate(image, cv2.ROTATE_180)
    if angle == 270:
        return cv2.rotate(image, cv2.ROTATE_90_COUNTERCLOCKWISE)
    raise ValueError(f"Angle non supporte: {angle}")


def _orientation_text_bonus(img: np.ndarray) -> int:
    """Favorise l’angle où le bandeau facture (FR/AR) et les dates sont lisibles."""
    h, w = img.shape[:2]
    if h < 30 or w < 30:
        return 0
    band = crop_relative(img, 0.02, 0.02, 0.98, min(0.45, 0.28 + 120 / max(h, 1)))
    if band.size == 0:
        return 0
    gray = cv2.cvtColor(band, cv2.COLOR_BGR2GRAY)
    scale = min(1.0, 1100.0 / max(w, 1))
    if scale < 1.0:
        gray = cv2.resize(
            gray,
            (max(1, int(gray.shape[1] * scale)), max(1, int(gray.shape[0] * scale))),
            interpolation=cv2.INTER_AREA,
        )
    try:
        txt = normalize_digits(
            pytesseract.image_to_string(gray, config="--oem 3 --psm 6", lang="eng+ara")
        )
    except Exception:
        return 0
    tl = txt.lower()
    score = 0
    for kw in (
        "steg",
        "montant",
        "reference",
        "référence",
        "facture",
        "electric",
        "élect",
        "gaz",
        "kwh",
        "consomm",
        "الرجاء",
        "الكهرباء",
        "الدفع",
        "المطلوب",
    ):
        if kw in tl or kw in txt:
            score += 1
    score += min(8, len(re.findall(r"20\d{2}", txt)))
    return score


def _coherent_steg_deadline(
    deadline: str | None,
    periode_du: str | None,
    periode_au: str | None,
) -> str | None:
    if not deadline or not periode_au:
        return deadline
    if deadline < periode_au:
        return None
    if periode_du and deadline < periode_du:
        return None
    return deadline


def _compute_steg_confidence(
    reference: str | None,
    montant: str | None,
    date_limite: str | None,
    periode_du: str | None,
    periode_au: str | None,
) -> str:
    strong_amount = is_strong_amount(montant)
    has_ref = bool(reference)
    has_period = bool(periode_du and periode_au)
    has_deadline = bool(date_limite)
    if has_ref and strong_amount and has_period and has_deadline:
        return "high"
    if has_ref and strong_amount and (has_period or has_deadline):
        return "medium"
    if has_ref and strong_amount:
        return "medium"
    if has_ref or strong_amount:
        return "low"
    return "low"


def extract_coupon_reference_and_amount(image: np.ndarray) -> tuple[str | None, str | None]:
    # Coupon de paiement en bas: colonnes "Montant" et "Reference"
    # Anciennes factures: bulletin plus haut (y ~0.55) ; ref "000006…" ou seulement "xxxxx xxx x"
    coupon_roi = crop_relative(image, 0.02, 0.55, 0.99, 1.00)
    no_space_ref: str | None = None
    coupon_raw_display: str | None = None
    amount_candidates: list[str] = []
    ref_long: list[str] = []
    spaced_nine: list[str] = []

    for variant in generate_preprocessed_variants(coupon_roi, upscale=2.8)[:_STEG_MAX_VARIANTS]:
        text = normalize_digits(ocr_text(variant, config="--oem 3 --psm 6", lang="eng+ara"))
        compact = re.sub(r"\s+", " ", text)
        amount_candidates.extend(parse_amount_candidates(compact))

        compact_digits = re.sub(r"\D", "", compact)
        ref_long.extend(re.findall(r"000006\d{8,10}", compact_digits))
        ref_long.extend(re.findall(r"000006\d{8,12}", compact_digits))
        for m in re.finditer(r"\d{5}\s+\d{3}\s+\d(?!\d)", compact):
            d9 = re.sub(r"\D", "", m.group(0))
            if len(d9) == 9:
                spaced_nine.append(d9)

    if ref_long:
        best_ref = Counter(ref_long).most_common(1)[0][0]
        if len(best_ref) > 18:
            best_ref = best_ref[:18]
        no_space_ref = best_ref
        coupon_raw_display = best_ref
    elif spaced_nine:
        d9 = Counter(spaced_nine).most_common(1)[0][0]
        no_space_ref = d9
        fr = format_reference_from_digits(d9)
        coupon_raw_display = fr if fr else d9

    amount = choose_payment_amount(amount_candidates)
    if not amount or not is_plausible_steg_line_amount(amount):
        amount = None

    if no_space_ref:
        # Aligné sur les motifs ref_long (8–10 chiffres après 000006)
        valid_long = bool(re.fullmatch(r"000006\d{8,11}", no_space_ref))
        valid_ccp = bool(re.fullmatch(r"\d{15,18}", no_space_ref))
        valid_nine = bool(re.fullmatch(r"\d{9}", no_space_ref))
        if not (valid_long or valid_ccp or valid_nine):
            no_space_ref = None
            coupon_raw_display = None

    return coupon_raw_display or no_space_ref, amount


def select_best_orientation(image: np.ndarray) -> np.ndarray:
    h0, w0 = image.shape[:2]
    ar = w0 / max(h0, 1)
    har = h0 / max(w0, 1)
    # Portrait, quasi-carré ou photo penchée : tester les 4 angles.
    if har >= 0.88 or (0.72 <= ar <= 1.35):
        candidates = [0, 90, 180, 270]
    else:
        candidates = [0, 180]
    best_score = -1
    best_img = image

    for angle in candidates:
        rot = rotate_image(image, angle)
        score = _orientation_text_bonus(rot)

        ref_top = extract_reference_from_top_keyword(rot)
        if ref_top:
            score += 6

        ref_roi = crop_relative(rot, 0.03, 0.08, 0.62, 0.38)
        ref_text = ocr_text(preprocess_roi(ref_roi, upscale=2.1), config="--oem 3 --psm 6", lang="eng+ara")
        ref = extract_reference(ref_text)
        if ref:
            score += 3

        amt_roi = crop_relative(rot, 0.02, 0.70, 0.64, 0.90)
        amt_bin = preprocess_roi(amt_roi, upscale=2.0)
        amt_text = ocr_text(amt_bin, config="--oem 3 --psm 6 -c tessedit_char_whitelist=0123456789,.", lang="eng")
        amt = clean_amount(amt_text)
        if amt and re.fullmatch(r"\d{1,6},\d{3}", amt):
            score += 2

        if score > best_score:
            best_score = score
            best_img = rot
        # Facture généralement droite : si 0° est déjà très lisible, éviter 3 rotations × OCR lourd
        if angle == 0 and best_score >= 11:
            return best_img

    return best_img


def extract_fields_from_invoice(image_path: Path, debug_dir: Path | None = None) -> ExtractionResult:
    raw_image = enhance_steg_scan(read_image(image_path))
    raw_image = downscale_if_too_large(raw_image)
    raw_image = upscale_if_too_small(raw_image, min_side=1050)
    image = select_best_orientation(raw_image)
    image = deskew_image(image)
    image = rectify_document_if_plausible(image)
    reference = None
    text_hints = _extract_steg_text_hints(image)

    # 1) Tentative reference par mot-cle dans la zone haute
    top_keyword_ref = extract_reference_from_top_keyword(image)
    ref_candidates_all: list[str] = []
    if top_keyword_ref:
        ref_candidates_all.extend([top_keyword_ref] * 4)

    # 2) Zone reference (haut-gauche a milieu) — élargie pour anciennes mises en page
    ref_roi = crop_relative(image, 0.02, 0.04, 0.88, 0.44)
    ref_bin = preprocess_roi(ref_roi, upscale=2.4)
    ref_variants = generate_preprocessed_variants(ref_roi, upscale=2.4)[:_STEG_MAX_VARIANTS]
    ref_candidates: list[str] = []
    for variant in ref_variants:
        txt = ocr_text(
            variant,
            config="--oem 3 --psm 6 -c tessedit_char_whitelist=0123456789 ",
            lang="eng",
        )
        ref_candidates.extend(extract_reference_candidates_from_text(txt))

    # ROI focalisee sur la valeur reference (zone haute centrale-gauche)
    ref_focus_roi = crop_relative(image, 0.10, 0.06, 0.62, 0.30)
    for variant in generate_preprocessed_variants(ref_focus_roi, upscale=3.0)[:_STEG_MAX_VARIANTS]:
        txt = ocr_text(
            variant,
            config="--oem 3 --psm 7 -c tessedit_char_whitelist=0123456789 ",
            lang="eng",
        )
        ref_candidates.extend(extract_reference_candidates_from_text(txt))
    voted_reference = vote_best_reference(ref_candidates)
    if voted_reference:
        ref_candidates_all.extend([voted_reference] * 3)

    # Fallback reference sur une zone plus large
    if not reference:
        ref_roi_2 = crop_relative(image, 0.02, 0.04, 0.92, 0.55)
        ref_candidates2: list[str] = []
        for variant in generate_preprocessed_variants(ref_roi_2, upscale=2.1)[:1]:
            txt = ocr_text(
                variant,
                config="--oem 3 --psm 11 -c tessedit_char_whitelist=0123456789 ",
                lang="eng",
            )
            ref_candidates2.extend(extract_reference_candidates_from_text(txt))
        v2 = vote_best_reference(ref_candidates2)
        if v2:
            ref_candidates_all.extend([v2] * 2)

    # Dernier fallback guide par mot-cle
    ref_kw = extract_reference_near_keywords(image)
    if ref_kw:
        ref_candidates_all.extend([ref_kw] * 3)
    ref_global = extract_reference_global_fallback(image)
    if ref_global:
        ref_candidates_all.append(ref_global)
    if text_hints:
        for c in extract_reference_candidates_from_text(text_hints):
            ref_candidates_all.extend([c] * 3)

    # Fallback important: reference dans coupon (sans espaces)
    coupon_reference, coupon_amount = extract_coupon_reference_and_amount(image)
    if coupon_reference:
        ref_coupon = derive_reference_from_footer_compact(coupon_reference)
        if ref_coupon:
            ref_candidates_all.extend([ref_coupon] * 2)

    if _steg_easyocr_enabled():
        for c in extract_reference_candidates_from_text(_easyocr_read_lines(ref_roi)):
            ref_candidates_all.extend([c] * 4)
        for c in extract_reference_candidates_from_text(_easyocr_read_lines(ref_focus_roi)):
            ref_candidates_all.extend([c] * 5)

    reference = vote_best_reference(ref_candidates_all)

    # Zone montant a payer (bas centre-gauche) — y plus haut pour anciennes factures
    amt_roi = crop_relative(image, 0.02, 0.56, 0.76, 0.94)
    amt_bin = preprocess_roi(amt_roi, upscale=2.2)
    amt_candidates: list[str] = []
    for variant in generate_preprocessed_variants(amt_roi, upscale=2.3)[:_STEG_MAX_VARIANTS]:
        txt = ocr_text(
            variant,
            config="--oem 3 --psm 6 -c tessedit_char_whitelist=0123456789,.",
            lang="eng",
        )
        amt_candidates.extend(parse_amount_candidates(txt))
    montant = choose_payment_amount(amt_candidates)
    roi_guided_amount = extract_amount_from_roi_with_keywords(amt_bin)
    if roi_guided_amount:
        montant = roi_guided_amount

    # Recherche guidee par mot-cle "Montant a payer" / "المبلغ المطلوب"
    guided_amount = extract_amount_near_keywords(image)
    if guided_amount:
        montant = guided_amount

    if is_strong_amount(coupon_amount):
        montant = coupon_amount
    elif not montant and coupon_amount:
        montant = coupon_amount

    if not is_strong_amount(montant):
        montant = None

    # Fallback montant sur zone plus haute
    if not montant:
        amt_roi_2 = crop_relative(image, 0.01, 0.52, 0.70, 0.92)
        amt_bin_2 = preprocess_roi(amt_roi_2, upscale=2.0)
        amt_text_2 = ocr_text(
            amt_bin_2, config="--oem 3 --psm 11 -c tessedit_char_whitelist=0123456789,.", lang="eng"
        )
        montant = clean_amount(amt_text_2)
        if not is_strong_amount(montant):
            montant = None

    # Encadré rouge « total à payer » puis récap / ligne stricte (photos pliées : tableau OCR souvent faux)
    red_montant = extract_montant_from_red_box(image)
    line_montant = extract_montant_a_payer_line_strict(image)
    summary_montant = extract_montant_from_summary_text(image)
    if red_montant and is_plausible_steg_line_amount(red_montant):
        montant = red_montant
    elif summary_montant:
        montant = summary_montant
    elif line_montant:
        montant = line_montant
    elif is_plausible_steg_line_amount(coupon_amount) and not is_plausible_steg_line_amount(montant or ""):
        montant = coupon_amount
    hint_amount = _extract_amount_from_text_hints(text_hints)
    if hint_amount and is_plausible_steg_line_amount(hint_amount):
        montant = hint_amount

    if debug_dir:
        debug_dir.mkdir(parents=True, exist_ok=True)
        # Image apres rotation + deskew (base pour tout l'OCR)
        cv2.imwrite(str(debug_dir / f"{image_path.stem}_aligned.png"), image)
        cv2.imwrite(str(debug_dir / f"{image_path.stem}_rectified.png"), image)
        cv2.imwrite(str(debug_dir / f"{image_path.stem}_ref_bin.png"), ref_bin)
        cv2.imwrite(str(debug_dir / f"{image_path.stem}_amt_bin.png"), amt_bin)

    date_limite = extract_date_limite_paiement(image)
    if not date_limite and text_hints:
        date_limite = parse_steg_payment_deadline_from_text(text_hints)
    excl: set[str] = set()
    if date_limite:
        excl.add(date_limite)
    periode_du, periode_au = extract_periode_du_au(image, exclude_iso_dates=excl)
    date_limite = _coherent_steg_deadline(date_limite, periode_du, periode_au)
    confidence_note = _compute_steg_confidence(
        reference, montant, date_limite, periode_du, periode_au
    )
    return ExtractionResult(
        file_name=image_path.name,
        reference=reference,
        montant_a_payer=montant,
        date_limite_paiement=date_limite,
        periode_du=periode_du,
        periode_au=periode_au,
        coupon_reference_raw=coupon_reference,
        coupon_montant=coupon_amount,
        confidence_note=confidence_note,
    )


def extract_amount_from_roi_with_keywords(amt_bin: np.ndarray) -> str | None:
    data = pytesseract.image_to_data(
        amt_bin,
        lang="eng+ara",
        config="--oem 3 --psm 6",
        output_type=Output.DICT,
    )
    words = []
    n = len(data["text"])
    for i in range(n):
        token = (data["text"][i] or "").strip()
        if not token:
            continue
        try:
            conf = float(data["conf"][i])
        except ValueError:
            conf = -1.0
        if conf < 10:
            continue
        x = int(data["left"][i])
        y = int(data["top"][i])
        ww = int(data["width"][i])
        hh = int(data["height"][i])
        words.append((token, x, y, ww, hh))

    if not words:
        return None

    primary_keyword_regex = re.compile(r"(payer|المطلوب)", re.IGNORECASE)
    secondary_keyword_regex = re.compile(r"(montant|المبلغ)", re.IGNORECASE)
    keyword_rows = [w for w in words if primary_keyword_regex.search(w[0])]
    if not keyword_rows:
        keyword_rows = [w for w in words if secondary_keyword_regex.search(w[0])]

    candidates: list[tuple[int, str]] = []
    for token, x, y, ww, hh in words:
        parsed = parse_amount_candidates(token)
        if not parsed:
            continue
        score = 1000
        for _, kx, ky, kw, kh in keyword_rows:
            dy = abs((y + hh // 2) - (ky + kh // 2))
            dx = abs((x + ww // 2) - (kx + kw // 2))
            score = min(score, dy + dx // 4)
        for p in parsed:
            if re.fullmatch(r"\d{1,6},\d{3}", p):
                score -= 150
            candidates.append((score, p))

    if not candidates:
        return None
    candidates.sort(key=lambda x: x[0])
    ranked = [c[1] for c in candidates]
    return choose_payment_amount(ranked)


def _normalize_steg_summary_amount_text(raw: str) -> str:
    """Espaces ou points type « 645 000 » / « 645.000 » -> virgule millimes."""
    t = normalize_digits(raw).replace("٫", ",")
    t = re.sub(r"(\d{1,4})\s+(\d{3})(?!\d)", r"\1,\2", t)
    t = re.sub(r"(\d{1,4})\.(\d{3})\b", r"\1,\2", t)
    return t.lower()


def extract_montant_from_summary_text(image: np.ndarray) -> str | None:
    """
    Zone recapitulatif STEG (totaux, arrieres, montant a payer). OCR texte libre + regex.
    """
    roi = crop_relative(image, 0.02, 0.45, 0.92, 0.90)
    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    # Pas de flou ici: il efface souvent les « | » et les chiffres du tableau recapitulatif.
    txt = normalize_digits(
        pytesseract.image_to_string(gray, lang="eng+ara", config="--oem 3 --psm 6")
    )
    txt_extra = normalize_digits(
        pytesseract.image_to_string(gray, lang="eng+ara", config="--oem 3 --psm 4")
    )
    txt = txt + "\n" + txt_extra
    txt_lower = _normalize_steg_summary_amount_text(txt)
    patterns = [
        r"montant\s*[àa]\s*payer[^\d]{0,120}(\d{1,4},\d{3})",
        r"\(\s*19\s*\)[^\d]{0,120}(\d{1,4},\d{3})",
        r"montant[^\d]{0,30}payer[^\d]{0,120}(\d{1,4},\d{3})",
        r"(?:montant|المبلغ)[^0-9\n]{0,50}(?:payer|المطلوب)[^\d]{0,100}(\d{1,4},\d{3})",
        r"المبلغ\s*المطلوب[^\d]{0,100}(\d{1,4},\d{3})",
    ]
    for pat in patterns:
        m = re.search(pat, txt_lower, re.IGNORECASE | re.DOTALL)
        if m and is_plausible_steg_line_amount(m.group(1)):
            return m.group(1)

    # Lignes contenant clairement le libellé de paiement : prendre le plus grand montant plausible.
    line_hits: list[str] = []
    pay_line_re = re.compile(
        r"montant\s*[àa]?\s*payer|\(\s*19\s*\)|المبلغ\s*المطلوب",
        re.IGNORECASE,
    )
    for line in txt_lower.split("\n"):
        if not pay_line_re.search(line):
            continue
        if re.search(r"pri[eèéê]?re\s+de\s+payer|الرجاء\s+الدفع", line) and not re.search(
            r"montant|المبلغ|\(\s*19\s*\)", line
        ):
            continue
        for m in re.finditer(r"(\d{1,4},\d{3})", line):
            if is_plausible_steg_line_amount(m.group(1)):
                line_hits.append(m.group(1))
    if line_hits:
        return max(line_hits, key=amount_to_millimes)

    # OCR sans virgule: « | 777000 | » ou 6 chiffres se terminant par 000
    pipe_amounts: list[str] = []
    for m in re.finditer(r"\|\s*(\d{6})\s*\|", txt):
        digits = m.group(1)
        if digits.endswith("000"):
            cand = f"{digits[:-3]},{digits[-3:]}"
            if is_plausible_steg_line_amount(cand):
                pipe_amounts.append(cand)
    if pipe_amounts:
        return max(pipe_amounts, key=amount_to_millimes)

    for m in re.finditer(r"(?<!\d)(\d{3,4})000(?!\d)", txt):
        cand = f"{m.group(1)},000"
        if is_plausible_steg_line_amount(cand):
            pipe_amounts.append(cand)
    if pipe_amounts:
        return max(pipe_amounts, key=amount_to_millimes)

    return None


def extract_montant_a_payer_line_strict(image: np.ndarray) -> str | None:
    """
    Ne prend un montant que sur une ligne ou figurent ensemble les libelles
    « Montant a payer » / « المبلغ المطلوب » (evite « Priere de payer » etc.).
    """
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (3, 3), 0)
    data = pytesseract.image_to_data(
        gray,
        lang="eng+ara",
        config="--oem 3 --psm 6",
        output_type=Output.DICT,
    )
    h, _w = gray.shape
    words: list[tuple[str, int, int, int, int]] = []
    n = len(data["text"])
    for i in range(n):
        token = normalize_digits((data["text"][i] or "").strip())
        if not token:
            continue
        try:
            conf = float(data["conf"][i])
        except ValueError:
            conf = -1.0
        if conf < 0:
            continue
        x = int(data["left"][i])
        y = int(data["top"][i])
        ww = int(data["width"][i])
        hh = int(data["height"][i])
        words.append((token, x, y, ww, hh))

    if len(words) < 2:
        return None

    y_tol = max(12, int(0.018 * h))
    candidates: list[str] = []

    for idx, (token, x, y, ww, hh) in enumerate(words):
        if not re.search(r"payer|المطلوب", token, re.IGNORECASE):
            continue
        yc = y + hh // 2
        line = [w for w in words if abs(w[2] + w[4] // 2 - yc) <= y_tol]
        line.sort(key=lambda w: w[1])
        line_text = " ".join(w[0] for w in line)
        if not re.search(r"montant|المبلغ|\(\s*19\s*\)", line_text, re.IGNORECASE):
            continue
        # « Prière de payer avant le » sans libellé montant : exclure (date limite, pas total).
        if re.search(r"pri[eèéê]?re\s+de\s+payer|الرجاء\s+الدفع", line_text, re.IGNORECASE) and not re.search(
            r"montant|المبلغ|\(\s*19\s*\)", line_text, re.IGNORECASE
        ):
            continue
        # STEG récent : montant souvent à droite du libellé dans un tableau, pas seulement à gauche.
        line_amounts: list[str] = []
        for w in line:
            for a in parse_amount_candidates(w[0]):
                if is_plausible_steg_line_amount(a):
                    line_amounts.append(a)
        if line_amounts:
            candidates.append(max(line_amounts, key=amount_to_millimes))

    if not candidates:
        return None
    return max(candidates, key=amount_to_millimes)


def extract_amount_near_keywords(image: np.ndarray) -> str | None:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (3, 3), 0)
    data = pytesseract.image_to_data(
        gray,
        lang="eng+ara",
        config="--oem 3 --psm 6",
        output_type=Output.DICT,
    )

    h, w = gray.shape
    words = []
    n = len(data["text"])
    for i in range(n):
        token = (data["text"][i] or "").strip()
        if not token:
            continue
        try:
            conf = float(data["conf"][i])
        except ValueError:
            conf = -1.0
        if conf < 0:
            continue
        x = int(data["left"][i])
        y = int(data["top"][i])
        ww = int(data["width"][i])
        hh = int(data["height"][i])
        words.append((token, x, y, ww, hh))

    if not words:
        return None

    primary_keyword_regex = re.compile(r"(payer|المطلوب)", re.IGNORECASE)
    secondary_keyword_regex = re.compile(r"(montant|المبلغ)", re.IGNORECASE)
    keywords = [wrd for wrd in words if primary_keyword_regex.search(wrd[0])]
    if not keywords:
        keywords = [wrd for wrd in words if secondary_keyword_regex.search(wrd[0])]
    if not keywords:
        return None

    amount_candidates: list[str] = []
    for _, kx, ky, kw, kh in keywords:
        ky_center = ky + kh // 2
        y_tol = int(0.06 * h)
        x_left = max(0, kx - int(0.45 * w))
        # Factures type tableau : le montant est souvent loin à droite sur la même ligne.
        x_right = min(w, kx + int(0.72 * w) + kw)
        for token, x, y, ww, hh in words:
            y_center = y + hh // 2
            if abs(y_center - ky_center) > y_tol:
                continue
            if not (x_left <= x <= x_right):
                continue
            amount_candidates.extend(parse_amount_candidates(token))

    return choose_payment_amount(amount_candidates)


def extract_reference_near_keywords(image: np.ndarray) -> str | None:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (3, 3), 0)
    data = pytesseract.image_to_data(
        gray,
        lang="eng+ara",
        config="--oem 3 --psm 6",
        output_type=Output.DICT,
    )

    h, w = gray.shape
    words = []
    n = len(data["text"])
    for i in range(n):
        token = (data["text"][i] or "").strip()
        if not token:
            continue
        try:
            conf = float(data["conf"][i])
        except ValueError:
            conf = -1.0
        if conf < 0:
            continue
        x = int(data["left"][i])
        y = int(data["top"][i])
        ww = int(data["width"][i])
        hh = int(data["height"][i])
        words.append((token, x, y, ww, hh))

    keyword_regex = re.compile(r"(ref|reference|référence|المرجع)", re.IGNORECASE)
    keywords = [wrd for wrd in words if keyword_regex.search(wrd[0])]
    if not keywords:
        return None

    for _, kx, ky, kw, kh in keywords:
        ky_center = ky + kh // 2
        y_tol = int(0.05 * h)
        x_left = max(0, kx - int(0.03 * w))
        x_right = min(w, kx + kw + int(0.5 * w))
        line_tokens: list[tuple[int, str]] = []
        for token, x, y, ww, hh in words:
            y_center = y + hh // 2
            if abs(y_center - ky_center) > y_tol:
                continue
            if not (x_left <= x <= x_right):
                continue
            digits = re.sub(r"\D", "", token)
            if digits:
                line_tokens.append((x, digits))
        if not line_tokens:
            continue
        line_tokens.sort(key=lambda t: t[0])
        compact = "".join(tok for _, tok in line_tokens)
        if len(compact) >= 9:
            return format_reference_from_digits(compact[:9])
    return None


def extract_reference_from_top_keyword(image: np.ndarray) -> str | None:
    top = crop_relative(image, 0.0, 0.0, 1.0, 0.38)
    gray = cv2.cvtColor(top, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (3, 3), 0)
    data = pytesseract.image_to_data(
        gray,
        lang="eng+ara",
        config="--oem 3 --psm 6",
        output_type=Output.DICT,
    )
    words = []
    n = len(data["text"])
    for i in range(n):
        token = normalize_digits((data["text"][i] or "").strip())
        if not token:
            continue
        try:
            conf = float(data["conf"][i])
        except ValueError:
            conf = -1.0
        if conf < 0:
            continue
        x = int(data["left"][i])
        y = int(data["top"][i])
        ww = int(data["width"][i])
        hh = int(data["height"][i])
        words.append((token, x, y, ww, hh))

    keyword_regex = re.compile(r"(ref|reference|référence|المرجع)", re.IGNORECASE)
    keys = [w for w in words if keyword_regex.search(w[0])]
    if not keys:
        return None

    candidates: list[str] = []
    h, w = gray.shape
    for _, kx, ky, kw, kh in keys:
        y_center = ky + kh // 2
        y_tol = int(0.06 * h)
        x_left = kx + kw
        x_right = min(w, kx + kw + int(0.45 * w))
        row_digits: list[tuple[int, str]] = []
        for token, x, y, ww, hh in words:
            yc = y + hh // 2
            if abs(yc - y_center) > y_tol:
                continue
            if not (x_left <= x <= x_right):
                continue
            ds = re.sub(r"\D", "", token)
            if ds:
                row_digits.append((x, ds))
        row_digits.sort(key=lambda t: t[0])
        compact = "".join(d for _, d in row_digits)
        if len(compact) >= 9:
            ref = compact_to_spaced_reference(compact)
            if ref:
                candidates.append(ref)

    return vote_best_reference(candidates)


def extract_reference_global_fallback(image: np.ndarray) -> str | None:
    """
    Fallback robuste: OCR sur grandes zones, puis extraction de toutes les
    references candidates (format 5-3-1), vote final.
    """
    rois = [
        (0.00, 0.00, 1.00, 0.45),
        (0.05, 0.05, 0.95, 0.35),
    ]
    cands: list[str] = []
    for x1, y1, x2, y2 in rois:
        roi = crop_relative(image, x1, y1, x2, y2)
        if roi.size == 0:
            continue
        for variant in generate_preprocessed_variants(roi, upscale=2.0)[:1]:
            txt = ocr_text(
                variant,
                config="--oem 3 --psm 6 -c tessedit_char_whitelist=0123456789 ",
                lang="eng",
            )
            cands.extend(extract_reference_candidates_from_text(txt))
    return vote_best_reference(cands)


def extract_batch(
    input_dir: Path,
    output_json: Path,
    output_csv: Path,
    debug_dir: Path | None = None,
    limit: int | None = None,
    progress_callback: Callable[[int, int, str], None] | None = None,
) -> list[ExtractionResult]:
    configure_tesseract()
    supported = {".jpg", ".jpeg", ".png", ".tif", ".tiff"}
    images = sorted([p for p in input_dir.iterdir() if p.is_file() and p.suffix.lower() in supported])
    if limit is not None and limit > 0:
        images = images[:limit]

    results: list[ExtractionResult] = []
    total = len(images)
    for idx, img_path in enumerate(images, start=1):
        if progress_callback:
            progress_callback(idx, total, img_path.name)
        result = extract_fields_from_invoice(img_path, debug_dir=debug_dir)
        results.append(result)

    output_json.parent.mkdir(parents=True, exist_ok=True)
    with output_json.open("w", encoding="utf-8") as f:
        json.dump(
            [
                {
                    "file_name": r.file_name,
                    "reference": r.reference,
                    "montant_a_payer": r.montant_a_payer,
                    "date_limite_paiement": r.date_limite_paiement,
                    "periode_du": r.periode_du,
                    "periode_au": r.periode_au,
                    "coupon_reference_raw": r.coupon_reference_raw,
                    "coupon_montant": r.coupon_montant,
                    "confidence_note": r.confidence_note,
                }
                for r in results
            ],
            f,
            ensure_ascii=False,
            indent=2,
        )

    with output_csv.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "file_name",
                "reference",
                "montant_a_payer",
                "date_limite_paiement",
                "periode_du",
                "periode_au",
                "coupon_reference_raw",
                "coupon_montant",
                "confidence_note",
            ]
        )
        for r in results:
            writer.writerow(
                [
                    r.file_name,
                    r.reference or "",
                    r.montant_a_payer or "",
                    r.date_limite_paiement or "",
                    r.periode_du or "",
                    r.periode_au or "",
                    r.coupon_reference_raw or "",
                    r.coupon_montant or "",
                    r.confidence_note,
                ]
            )

    return results
