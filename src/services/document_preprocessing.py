from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class PreprocessingError(RuntimeError):
    pass


@dataclass(frozen=True)
class PreprocessedDocument:
    path: Path
    metadata: dict[str, Any]


ALLOWED_EXTENSIONS = {
    ".pdf",
    ".jpg",
    ".jpeg",
    ".png",
    ".tif",
    ".tiff",
    ".webp",
    ".bmp",
}
MAX_DOCUMENT_BYTES = 20 * 1024 * 1024


def _safe_stem(name: str) -> str:
    stem = Path(name).stem
    stem = re.sub(r"[^\w\-]+", "_", stem, flags=re.UNICODE)
    return (stem.strip("._") or "document")[:80]


def _validate_file(file_path: Path, metadata: dict[str, Any]) -> str:
    suffix = file_path.suffix.lower()
    metadata["input_extension"] = suffix or "unknown"
    if suffix not in ALLOWED_EXTENSIONS:
        raise PreprocessingError(
            "Format non supporte. Utilise PDF, JPG, PNG, TIFF, WEBP ou BMP."
        )
    try:
        size = file_path.stat().st_size
    except OSError as exc:
        raise PreprocessingError(f"Fichier inaccessible: {exc}") from exc
    metadata["input_size_bytes"] = size
    if size <= 0:
        raise PreprocessingError("Fichier vide.")
    if size > MAX_DOCUMENT_BYTES:
        raise PreprocessingError("Fichier trop volumineux. Taille maximale: 20 Mo.")
    metadata["steps"].append("format_and_size_validation")
    return suffix


def _order_points(points: Any) -> Any:
    import numpy as np

    rect = np.zeros((4, 2), dtype="float32")
    sums = points.sum(axis=1)
    rect[0] = points[np.argmin(sums)]
    rect[2] = points[np.argmax(sums)]
    diffs = np.diff(points, axis=1)
    rect[1] = points[np.argmin(diffs)]
    rect[3] = points[np.argmax(diffs)]
    return rect


def _four_point_transform(image: Any, points: Any) -> Any:
    import cv2
    import numpy as np

    rect = _order_points(points.astype("float32"))
    top_left, top_right, bottom_right, bottom_left = rect
    width_a = np.linalg.norm(bottom_right - bottom_left)
    width_b = np.linalg.norm(top_right - top_left)
    max_width = max(1, int(max(width_a, width_b)))
    height_a = np.linalg.norm(top_right - bottom_right)
    height_b = np.linalg.norm(top_left - bottom_left)
    max_height = max(1, int(max(height_a, height_b)))
    dst = np.array(
        [
            [0, 0],
            [max_width - 1, 0],
            [max_width - 1, max_height - 1],
            [0, max_height - 1],
        ],
        dtype="float32",
    )
    matrix = cv2.getPerspectiveTransform(rect, dst)
    return cv2.warpPerspective(
        image,
        matrix,
        (max_width, max_height),
        flags=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_REPLICATE,
    )


def _quad_output_shape(points: Any) -> tuple[int, int]:
    import numpy as np

    rect = _order_points(points.astype("float32"))
    top_left, top_right, bottom_right, bottom_left = rect
    width = int(max(np.linalg.norm(bottom_right - bottom_left), np.linalg.norm(top_right - top_left)))
    height = int(max(np.linalg.norm(top_right - bottom_right), np.linalg.norm(top_left - bottom_left)))
    return max(1, width), max(1, height)


def _candidate_quad_from_contour(contour: Any) -> Any | None:
    import cv2

    peri = cv2.arcLength(contour, True)
    for factor in (0.015, 0.02, 0.03, 0.045, 0.065):
        approx = cv2.approxPolyDP(contour, factor * peri, True)
        if len(approx) == 4 and cv2.isContourConvex(approx):
            return approx.reshape(4, 2).astype("float32")

    rect = cv2.minAreaRect(contour)
    box = cv2.boxPoints(rect)
    rect_area = max(float(rect[1][0] * rect[1][1]), 1.0)
    if cv2.contourArea(contour) / rect_area >= 0.55:
        return box.astype("float32")
    return None


def _find_document_quad(image: Any, metadata: dict[str, Any]) -> Any | None:
    import cv2
    import numpy as np

    h, w = image.shape[:2]
    if h < 140 or w < 140:
        return None

    detection_scale = min(1.0, 1500.0 / float(max(h, w)))
    work = image
    if detection_scale < 1.0:
        work = cv2.resize(
            image,
            (max(1, int(w * detection_scale)), max(1, int(h * detection_scale))),
            interpolation=cv2.INTER_AREA,
        )
    scale_back = 1.0 / detection_scale
    wh, ww = work.shape[:2]

    gray = cv2.cvtColor(work, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (5, 5), 0)
    hsv = cv2.cvtColor(work, cv2.COLOR_BGR2HSV)

    edge_mask = cv2.Canny(gray, 40, 140)
    edge_mask = cv2.dilate(edge_mask, cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5)), iterations=1)
    edge_mask = cv2.morphologyEx(
        edge_mask,
        cv2.MORPH_CLOSE,
        cv2.getStructuringElement(cv2.MORPH_RECT, (13, 13)),
        iterations=2,
    )

    bright_mask = cv2.inRange(hsv, np.array([0, 0, 105]), np.array([180, 120, 255]))
    bright_mask = cv2.morphologyEx(
        bright_mask,
        cv2.MORPH_CLOSE,
        cv2.getStructuringElement(cv2.MORPH_RECT, (19, 19)),
        iterations=2,
    )
    bright_mask = cv2.morphologyEx(
        bright_mask,
        cv2.MORPH_OPEN,
        cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5)),
        iterations=1,
    )

    candidates: list[tuple[float, Any, float, float]] = []
    for mask_name, mask in (("edge", edge_mask), ("bright", bright_mask)):
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for contour in sorted(contours, key=cv2.contourArea, reverse=True)[:12]:
            area = cv2.contourArea(contour)
            area_ratio = area / float(max(ww * wh, 1))
            if area_ratio < 0.055 or area_ratio > 0.985:
                continue
            quad = _candidate_quad_from_contour(contour)
            if quad is None:
                continue
            out_w, out_h = _quad_output_shape(quad)
            aspect = out_w / float(max(out_h, 1))
            if aspect < 0.18 or aspect > 5.5:
                continue
            if min(out_w, out_h) < 120:
                continue
            quad_area = cv2.contourArea(quad)
            fill_ratio = area / max(float(quad_area), 1.0)
            score = area_ratio + min(fill_ratio, 1.0) * 0.18
            if mask_name == "bright":
                score += 0.08
            candidates.append((score, quad * scale_back, area_ratio, aspect))

    if not candidates:
        metadata["perspective_correction"] = "not_detected"
        return None

    candidates.sort(key=lambda item: item[0], reverse=True)
    _score, quad, area_ratio, aspect = candidates[0]
    metadata["perspective_area_ratio"] = round(float(area_ratio), 4)
    metadata["perspective_aspect_ratio"] = round(float(aspect), 4)
    return quad.astype("float32")


def _rectify_document_bgr(image: Any, metadata: dict[str, Any]) -> Any:
    import cv2

    quad = _find_document_quad(image, metadata)
    if quad is None:
        return image

    h, w = image.shape[:2]
    warped = _four_point_transform(image, quad)
    wh, ww = warped.shape[:2]
    warped_area_ratio = (wh * ww) / float(max(h * w, 1))
    if warped_area_ratio < 0.045 or min(wh, ww) < 120:
        metadata["perspective_correction"] = "rejected"
        return image

    pad = max(8, min(28, int(min(wh, ww) * 0.025)))
    warped = cv2.copyMakeBorder(
        warped,
        pad,
        pad,
        pad,
        pad,
        cv2.BORDER_CONSTANT,
        value=(255, 255, 255),
    )
    metadata["perspective_correction"] = "applied"
    metadata["perspective_output_width"] = int(warped.shape[1])
    metadata["perspective_output_height"] = int(warped.shape[0])
    metadata["steps"].append("document_perspective_rectification")
    return warped


def _rotate_bound_bgr(image: Any, angle: int) -> Any:
    import cv2

    normalized = angle % 360
    if normalized == 90:
        return cv2.rotate(image, cv2.ROTATE_90_CLOCKWISE)
    if normalized == 180:
        return cv2.rotate(image, cv2.ROTATE_180)
    if normalized == 270:
        return cv2.rotate(image, cv2.ROTATE_90_COUNTERCLOCKWISE)
    return image


def _rotate_arbitrary_bgr(image: Any, angle: float) -> Any:
    import cv2

    if image is None or image.size == 0:
        return image
    h, w = image.shape[:2]
    center = (w / 2.0, h / 2.0)
    matrix = cv2.getRotationMatrix2D(center, angle, 1.0)
    cos = abs(matrix[0, 0])
    sin = abs(matrix[0, 1])
    new_w = int(h * sin + w * cos)
    new_h = int(h * cos + w * sin)
    matrix[0, 2] += new_w / 2 - center[0]
    matrix[1, 2] += new_h / 2 - center[1]
    return cv2.warpAffine(
        image,
        matrix,
        (new_w, new_h),
        flags=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_REPLICATE,
    )


def _hough_deskew_bgr(image: Any, metadata: dict[str, Any]) -> Any:
    import cv2
    import numpy as np

    if image is None or image.size == 0:
        return image
    h, w = image.shape[:2]
    if h < 180 or w < 180:
        return image

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (3, 3), 0)
    edges = cv2.Canny(gray, 50, 150, apertureSize=3)
    min_len = max(90, int(min(h, w) * 0.18))
    lines = cv2.HoughLinesP(
        edges,
        rho=1,
        theta=np.pi / 180,
        threshold=max(70, int(min(h, w) * 0.05)),
        minLineLength=min_len,
        maxLineGap=max(12, int(min(h, w) * 0.025)),
    )
    if lines is None:
        metadata["hough_deskew_angle"] = 0.0
        return image

    weighted_angles: list[float] = []
    for line in lines[:, 0]:
        x1, y1, x2, y2 = [int(v) for v in line]
        dx = x2 - x1
        dy = y2 - y1
        length = float((dx * dx + dy * dy) ** 0.5)
        if length < min_len:
            continue
        angle = float(np.degrees(np.arctan2(dy, dx)))
        while angle <= -90:
            angle += 180
        while angle > 90:
            angle -= 180
        if abs(angle) > 32:
            continue
        repeats = max(1, min(8, int(length / max(min_len, 1))))
        weighted_angles.extend([angle] * repeats)

    if len(weighted_angles) < 3:
        metadata["hough_deskew_angle"] = 0.0
        return image

    median_angle = float(np.median(weighted_angles))
    if abs(median_angle) < 0.5 or abs(median_angle) > 32:
        metadata["hough_deskew_angle"] = 0.0
        return image

    metadata["hough_deskew_angle"] = round(median_angle, 3)
    metadata["steps"].append("hough_line_deskew")
    return _rotate_arbitrary_bgr(image, -median_angle)


def _ocr_orientation_score(text: str) -> float:
    letters = len(re.findall(r"[A-Za-z\u0600-\u06FF]", text or ""))
    digits = len(re.findall(r"\d", text or ""))
    keywords = len(
        re.findall(
            r"facture|invoice|steg|reference|total|montant|payer|ticket|receipt|"
            r"laboratoire|analyse|patient|compteur|tva|ttc|date",
            text or "",
            flags=re.IGNORECASE,
        )
    )
    return letters + digits * 1.25 + keywords * 18.0


def _auto_orient_bgr(image: Any, metadata: dict[str, Any]) -> Any:
    import cv2

    try:
        import pytesseract

        from src.extraction.steg_invoice_extractor import configure_tesseract
    except Exception:
        metadata["auto_orientation"] = "unavailable"
        return image

    try:
        configure_tesseract()
    except Exception:
        metadata["auto_orientation"] = "tesseract_unavailable"
        return image

    h, w = image.shape[:2]
    longest = max(h, w)
    scale = min(1.0, 950.0 / float(max(longest, 1)))
    probe = image
    if scale < 1.0:
        probe = cv2.resize(
            image,
            (max(1, int(w * scale)), max(1, int(h * scale))),
            interpolation=cv2.INTER_AREA,
        )

    best_angle = 0
    best_score = -1.0
    scores: dict[int, float] = {}
    for angle in (0, 90, 180, 270):
        candidate = _rotate_bound_bgr(probe, angle)
        gray = cv2.cvtColor(candidate, cv2.COLOR_BGR2GRAY)
        try:
            text = pytesseract.image_to_string(
                gray,
                lang="eng",
                config="--oem 3 --psm 11",
                timeout=2.0,
            )
        except Exception:
            text = ""
        score = _ocr_orientation_score(text)
        scores[angle] = round(score, 2)
        if score > best_score:
            best_score = score
            best_angle = angle

    metadata["auto_orientation_scores"] = scores
    if best_angle and best_score > scores.get(0, 0.0) + 12.0:
        metadata["auto_orientation_degrees"] = best_angle
        metadata["steps"].append("ocr_based_orientation_correction")
        return _rotate_bound_bgr(image, best_angle)

    metadata["auto_orientation_degrees"] = 0
    return image


def _deskew_bgr(image: Any, metadata: dict[str, Any]) -> Any:
    import cv2
    import numpy as np

    if image is None or image.size == 0:
        return image
    h, w = image.shape[:2]
    if h < 80 or w < 80:
        return image
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (3, 3), 0)
    inv = cv2.bitwise_not(gray)
    _, thresh = cv2.threshold(inv, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (max(15, w // 45), 3))
    dilated = cv2.dilate(thresh, kernel, iterations=2)
    coords = np.column_stack(np.where(dilated > 0))
    if len(coords) < max(500, (h * w) // 250):
        metadata["deskew_angle"] = 0.0
        return image

    rect = cv2.minAreaRect(coords)
    angle = rect[-1]
    skew = 90 + angle if angle < -45 else -angle
    if abs(skew) < 0.35 or abs(skew) > 28.0:
        metadata["deskew_angle"] = 0.0
        return image

    center = (w / 2.0, h / 2.0)
    matrix = cv2.getRotationMatrix2D(center, skew, 1.0)
    cos = abs(matrix[0, 0])
    sin = abs(matrix[0, 1])
    new_w = int(h * sin + w * cos)
    new_h = int(h * cos + w * sin)
    matrix[0, 2] += new_w / 2 - center[0]
    matrix[1, 2] += new_h / 2 - center[1]
    metadata["deskew_angle"] = round(float(skew), 3)
    metadata["steps"].append("deskew")
    return cv2.warpAffine(
        image,
        matrix,
        (new_w, new_h),
        flags=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_REPLICATE,
    )


def _resize_bgr(image: Any, metadata: dict[str, Any]) -> Any:
    import cv2

    h, w = image.shape[:2]
    longest = max(h, w)
    shortest = min(h, w)
    scale = 1.0
    if longest > 2600:
        scale = 2600 / float(longest)
    elif shortest < 900:
        scale = min(2.0, 900 / float(max(shortest, 1)))
    if abs(scale - 1.0) < 0.01:
        return image
    new_w = max(1, int(w * scale))
    new_h = max(1, int(h * scale))
    interpolation = cv2.INTER_AREA if scale < 1 else cv2.INTER_CUBIC
    metadata["resize_scale"] = round(scale, 3)
    metadata["steps"].append("resize")
    return cv2.resize(image, (new_w, new_h), interpolation=interpolation)


def _enhance_bgr(image: Any, metadata: dict[str, Any]) -> Any:
    import cv2
    import numpy as np

    try:
        lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)
        l_ch, a_ch, b_ch = cv2.split(lab)
        clahe = cv2.createCLAHE(clipLimit=2.1, tileGridSize=(8, 8))
        l2 = clahe.apply(l_ch)
        enhanced = cv2.cvtColor(cv2.merge([l2, a_ch, b_ch]), cv2.COLOR_LAB2BGR)
        blur = cv2.GaussianBlur(enhanced, (0, 0), 0.9)
        enhanced = cv2.addWeighted(enhanced, 1.18, blur, -0.18, 0)
        metadata["steps"].append("contrast_and_sharpness_enhancement")
        return np.clip(enhanced, 0, 255).astype(np.uint8)
    except Exception:
        return image


def _preprocess_image(file_path: Path, work_dir: Path, metadata: dict[str, Any]) -> PreprocessedDocument:
    try:
        import cv2
        import numpy as np
        from PIL import Image, ImageOps
    except ImportError as exc:
        raise PreprocessingError(
            "Le pretraitement image requiert Pillow, numpy et opencv-python."
        ) from exc

    try:
        with Image.open(file_path) as image:
            image = ImageOps.exif_transpose(image)
            image = image.convert("RGB")
            metadata["original_width"], metadata["original_height"] = image.size
            rgb = np.array(image)
    except Exception as exc:
        raise PreprocessingError(f"Image invalide ou illisible: {exc}") from exc

    bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    metadata["steps"].append("exif_orientation_correction")
    bgr = _resize_bgr(bgr, metadata)
    bgr = _rectify_document_bgr(bgr, metadata)
    bgr = _resize_bgr(bgr, metadata)
    bgr = _auto_orient_bgr(bgr, metadata)
    bgr = _hough_deskew_bgr(bgr, metadata)
    bgr = _deskew_bgr(bgr, metadata)
    bgr = _enhance_bgr(bgr, metadata)

    out_path = work_dir / f"{_safe_stem(file_path.name)}_preprocessed.png"
    if not cv2.imwrite(str(out_path), bgr):
        raise PreprocessingError("Impossible d'enregistrer l'image pretraitee.")
    h, w = bgr.shape[:2]
    metadata["output_width"] = int(w)
    metadata["output_height"] = int(h)
    metadata["output_format"] = "png"
    metadata["output_size_bytes"] = out_path.stat().st_size
    return PreprocessedDocument(path=out_path, metadata=metadata)


def _validate_pdf(file_path: Path, work_dir: Path, metadata: dict[str, Any]) -> PreprocessedDocument:
    try:
        import fitz
    except ImportError as exc:
        raise PreprocessingError("PyMuPDF est requis pour valider et preparer les PDF.") from exc
    try:
        with fitz.open(str(file_path)) as doc:
            if doc.is_encrypted:
                raise PreprocessingError("PDF chiffre ou protege par mot de passe.")
            if len(doc) <= 0:
                raise PreprocessingError("PDF sans page exploitable.")
            metadata["page_count"] = int(len(doc))
    except PreprocessingError:
        raise
    except Exception as exc:
        raise PreprocessingError(f"PDF invalide ou illisible: {exc}") from exc

    out_path = work_dir / f"{_safe_stem(file_path.name)}.pdf"
    shutil.copyfile(file_path, out_path)
    metadata["steps"].append("pdf_validation")
    metadata["steps"].append("pdf_pages_ready")
    metadata["output_format"] = "pdf"
    metadata["output_size_bytes"] = out_path.stat().st_size
    return PreprocessedDocument(path=out_path, metadata=metadata)


def preprocess_document(file_path: Path, work_dir: Path) -> PreprocessedDocument:
    work_dir.mkdir(parents=True, exist_ok=True)
    metadata: dict[str, Any] = {
        "enabled": True,
        "steps": [],
        "input_name": file_path.name,
    }
    suffix = _validate_file(file_path, metadata)
    if suffix == ".pdf":
        return _validate_pdf(file_path, work_dir, metadata)
    return _preprocess_image(file_path, work_dir, metadata)
