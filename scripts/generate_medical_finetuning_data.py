from __future__ import annotations

import argparse
import csv
import json
import random
import shutil
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFilter, ImageFont

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FINE_ROOT = PROJECT_ROOT / "data" / "finetuning"
RAW_ROOT = FINE_ROOT / "raw" / "synthetic" / "medical_lab_reports"
INPUT_ROOT = FINE_ROOT / "processed" / "inputs" / "medical"
GT_ROOT = FINE_ROOT / "processed" / "ground_truth" / "medical"
MANIFEST_PATH = FINE_ROOT / "manifests" / "medical_synthetic_manifest.csv"


LABS = [
    {
        "name": "Laboratoire Exemple Alpha",
        "doctor": "Dr. EXEMPLE ALPHA",
        "address": "10 rue Exemple, Tunis",
    },
    {
        "name": "Laboratoire Exemple Beta",
        "doctor": "Dr. EXEMPLE BETA",
        "address": "20 avenue Exemple, Sfax",
    },
    {
        "name": "Laboratoire Exemple Gamma",
        "doctor": "Dr. EXEMPLE GAMMA",
        "address": "30 route Exemple, Sousse",
    },
    {
        "name": "Laboratoire Exemple Delta",
        "doctor": "Dr. EXEMPLE DELTA",
        "address": "40 boulevard Exemple, Nabeul",
    },
]

PATIENTS = [
    ("PATIENT EXEMPLE ALPHA", "F", "SYN-001"),
    ("PATIENT EXEMPLE BETA", "M", "SYN-002"),
    ("PATIENT EXEMPLE GAMMA", "M", "SYN-003"),
    ("PATIENT EXEMPLE DELTA", "M", "SYN-004"),
    ("PATIENT EXEMPLE EPSILON", "F", "SYN-005"),
    ("PATIENT EXEMPLE ZETA", "F", "SYN-006"),
    ("PATIENT EXEMPLE ETA", "M", "SYN-007"),
    ("PATIENT EXEMPLE THETA", "F", "SYN-008"),
]

TEST_POOL = [
    ("Glycemie a jeun", "g/l", 0.98, 0.70, 1.10, "biochemistry"),
    ("Cholesterol total", "g/l", 1.80, 1.50, 2.50, "biochemistry"),
    ("Cholesterol HDL", "g/l", 0.61, 0.45, 0.65, "biochemistry"),
    ("Cholesterol LDL", "g/l", 1.00, 1.00, 1.88, "biochemistry"),
    ("Triglycerides", "g/l", 1.30, 0.60, 1.65, "biochemistry"),
    ("Uree", "g/l", 0.35, 0.10, 0.50, "biochemistry"),
    ("Creatinine", "mg/l", 11.00, 7.00, 16.00, "biochemistry"),
    ("ASAT / GOT", "UI/l", 28.00, 0.00, 40.00, "biochemistry"),
    ("ALAT / GPT", "UI/l", 28.00, 0.00, 40.00, "biochemistry"),
    ("25-Hydroxy Vitamine D", "ug/l", 48.90, 30.00, 100.00, "hormonology"),
    ("TSH", "mUI/l", 1.025, 0.25, 5.00, "hormonology"),
    ("Hemoglobine", "g/dl", 13.10, 12.00, 15.00, "hematology"),
    ("Globules rouges", "Millions/mm3", 4.60, 3.80, 5.40, "hematology"),
    ("Hematocrite", "%", 39.90, 37.00, 47.00, "hematology"),
    ("VGM", "fl", 87.00, 83.00, 100.00, "hematology"),
    ("Leucocytes", "/mm3", 4200.00, 4000.00, 10000.00, "hematology"),
    ("Plaquettes", "/mm3", 164000.00, 150000.00, 400000.00, "hematology"),
]


def ensure_dirs() -> None:
    for folder in (RAW_ROOT / "images", RAW_ROOT / "pdfs", INPUT_ROOT, GT_ROOT, MANIFEST_PATH.parent):
        folder.mkdir(parents=True, exist_ok=True)


def pick_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        "C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf",
        "C:/Windows/Fonts/calibrib.ttf" if bold else "C:/Windows/Fonts/calibri.ttf",
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size=size)
        except Exception:
            pass
    return ImageFont.load_default()


def jitter_value(rng: random.Random, base: float, min_v: float, max_v: float) -> float:
    span = max(max_v - min_v, 1.0)
    value = base + rng.uniform(-0.18 * span, 0.18 * span)
    if rng.random() < 0.12:
        value = rng.choice([min_v - 0.12 * span, max_v + 0.12 * span])
    return max(0.01, value)


def status_for(value: float, min_v: float, max_v: float) -> str:
    if value < min_v:
        return "low"
    if value > max_v:
        return "high"
    return "normal"


def fmt_number(value: float) -> str:
    if abs(value) >= 1000:
        return f"{value:.0f}"
    if abs(value) >= 10:
        return f"{value:.2f}"
    return f"{value:.2f}".rstrip("0").rstrip(".")


def make_case(rng: random.Random, index: int) -> dict[str, Any]:
    lab = rng.choice(LABS)
    patient_name, sex, patient_id = rng.choice(PATIENTS)
    report_date = date(2025, 1, 1) + timedelta(days=rng.randint(0, 420))
    received_date = report_date - timedelta(days=rng.randint(0, 2))
    exam_number = f"{report_date.strftime('%d%m%y')}/{rng.randint(100, 9999):04d}"
    dossier_number = f"{report_date.strftime('%d%m%y')}-{rng.randint(1, 999):03d}"

    tests = []
    for name, unit, base, min_v, max_v, category in rng.sample(TEST_POOL, rng.randint(7, 12)):
        value = jitter_value(rng, base, min_v, max_v)
        tests.append(
            {
                "raw_test_name": name,
                "normalized_name": name.lower().replace(" ", "_").replace("/", "_"),
                "category": category,
                "value_text": None,
                "value": round(value, 3),
                "secondary_value": None,
                "previous_value": None,
                "unit": unit,
                "reference_range": {
                    "min": min_v,
                    "max": max_v,
                    "raw_text": f"{fmt_number(min_v)} - {fmt_number(max_v)}",
                },
                "status": status_for(value, min_v, max_v),
                "raw_line": f"{name} {fmt_number(value)} {unit} VN: {fmt_number(min_v)} - {fmt_number(max_v)}",
                "confidence": 1.0,
                "notes": None,
            }
        )

    payload = {
        "document_type": "medical_lab_report",
        "lab_info": {
            "lab_name": lab["name"],
            "doctor_name": lab["doctor"],
        },
        "patient_info": {
            "patient_name": patient_name.title(),
            "patient_id": patient_id,
            "date_of_birth": None,
            "sex": sex,
        },
        "document_metadata": {
            "exam_number": exam_number,
            "dossier_number": dossier_number,
            "received_date": received_date.isoformat(),
            "edited_date": report_date.isoformat(),
            "request_date": received_date.isoformat(),
            "sample_date": received_date.isoformat(),
            "report_date": report_date.isoformat(),
            "page_number": "1",
            "organization": "CNAM" if rng.random() < 0.45 else None,
            "document_type": "medical_lab_report",
        },
        "tests": tests,
        "warnings": [],
        "extraction_source": "synthetic_ground_truth",
    }
    return {
        "id": f"medical_synth_{index:04d}",
        "lab": lab,
        "payload": payload,
    }


def case_to_markdown(case: dict[str, Any]) -> str:
    p = case["payload"]
    lines = [
        f"# {p['lab_info']['lab_name']}",
        f"Medecin demandeur: {p['lab_info']['doctor_name']}",
        "",
        f"Dossier N: {p['document_metadata']['dossier_number']}",
        f"Examen N: {p['document_metadata']['exam_number']}",
        f"Recu le: {p['document_metadata']['received_date']}",
        f"Edite le: {p['document_metadata']['edited_date']}",
        f"Patient: {p['patient_info']['patient_name']}",
        f"Code patient: {p['patient_info']['patient_id']}",
        f"Sexe: {p['patient_info']['sex']}",
        "",
        "## Resultats des examens",
        "| Analyse | Valeur | Unite | Valeurs de reference |",
        "|---|---:|---|---|",
    ]
    for test in p["tests"]:
        rr = test["reference_range"]["raw_text"]
        lines.append(f"| {test['raw_test_name']} | {fmt_number(float(test['value']))} | {test['unit']} | {rr} |")
    return "\n".join(lines) + "\n"


def render_image(case: dict[str, Any], image_path: Path, pdf_path: Path, rng: random.Random) -> None:
    p = case["payload"]
    width, height = 1120, 1580
    paper = Image.new("RGB", (width, height), (236, 246, 252))
    draw = ImageDraw.Draw(paper)
    font_title = pick_font(34, bold=True)
    font_header = pick_font(24, bold=True)
    font = pick_font(22)
    font_small = pick_font(18)

    draw.rounded_rectangle([45, 45, width - 45, 205], radius=18, outline=(40, 105, 170), width=3, fill=(218, 238, 250))
    draw.text((75, 70), p["lab_info"]["lab_name"], fill=(15, 65, 125), font=font_title)
    draw.text((75, 118), "Medecin Biologiste", fill=(15, 65, 125), font=font_small)
    draw.text((75, 150), case["lab"]["address"], fill=(50, 90, 130), font=font_small)
    draw.text((width - 190, 170), "Page: 1", fill=(45, 70, 100), font=font_small)

    y = 245
    left = 75
    right = 610
    draw.text((left, y), f"Recu le : {p['document_metadata']['received_date']}", fill=(20, 35, 55), font=font)
    draw.text((right, y), f"Dossier N : {p['document_metadata']['dossier_number']}", fill=(20, 35, 55), font=font)
    y += 36
    draw.text((left, y), f"Edite le : {p['document_metadata']['edited_date']}", fill=(20, 35, 55), font=font)
    draw.text((right, y), f"Examen N : {p['document_metadata']['exam_number']}", fill=(20, 35, 55), font=font)
    y += 42
    draw.text((left, y), f"Demande par Dr : {p['lab_info']['doctor_name']}", fill=(20, 35, 55), font=font)
    draw.text((right, y), f"Patient : {p['patient_info']['patient_name']}", fill=(20, 35, 55), font=font_header)
    y += 36
    draw.text((right, y), f"Code patient : {p['patient_info']['patient_id']}    Sexe : {p['patient_info']['sex']}", fill=(20, 35, 55), font=font)

    y += 95
    draw.text((width // 2 - 190, y), "EXAMENS BIOLOGIQUES", fill=(10, 30, 65), font=font_title)
    y += 70
    draw.text((75, y), "Analyse", fill=(10, 30, 65), font=font_header)
    draw.text((600, y), "Resultat", fill=(10, 30, 65), font=font_header)
    draw.text((760, y), "Unite", fill=(10, 30, 65), font=font_header)
    draw.text((900, y), "V.N.", fill=(10, 30, 65), font=font_header)
    y += 35
    draw.line([70, y, width - 70, y], fill=(80, 125, 170), width=2)
    y += 25

    for test in p["tests"][:12]:
        if y > 1360:
            break
        draw.text((75, y), test["raw_test_name"], fill=(15, 25, 45), font=font)
        draw.line([315, y + 21, 590, y + 21], fill=(120, 150, 180), width=1)
        draw.text((610, y), fmt_number(float(test["value"])), fill=(15, 25, 45), font=font)
        draw.text((760, y), test["unit"], fill=(15, 25, 45), font=font)
        draw.text((900, y), test["reference_range"]["raw_text"], fill=(15, 25, 45), font=font_small)
        y += 46

    draw.text((75, height - 110), "Document synthetique annote pour fine-tuning DocIA", fill=(60, 95, 130), font=font_small)
    draw.text((width - 260, height - 115), "Signature", fill=(40, 80, 160), font=font)
    draw.line([width - 285, height - 85, width - 95, height - 130], fill=(20, 70, 170), width=4)

    if rng.random() < 0.7:
        paper = paper.rotate(rng.uniform(-1.2, 1.2), expand=False, fillcolor=(245, 248, 250))
    if rng.random() < 0.5:
        paper = paper.filter(ImageFilter.GaussianBlur(radius=rng.uniform(0.15, 0.45)))
    paper.save(image_path, quality=92)
    paper.save(pdf_path, "PDF", resolution=150.0)


def write_example(case: dict[str, Any], rng: random.Random) -> dict[str, str]:
    sample_id = case["id"]
    md = case_to_markdown(case)
    input_path = INPUT_ROOT / f"{sample_id}.txt"
    gt_path = GT_ROOT / f"{sample_id}.json"
    image_path = RAW_ROOT / "images" / f"{sample_id}.jpg"
    pdf_path = RAW_ROOT / "pdfs" / f"{sample_id}.pdf"

    input_path.write_text(md, encoding="utf-8")
    gt_path.write_text(json.dumps(case["payload"], ensure_ascii=False, indent=2), encoding="utf-8")
    render_image(case, image_path, pdf_path, rng)
    return {
        "id": sample_id,
        "input": str(input_path.relative_to(PROJECT_ROOT)),
        "ground_truth": str(gt_path.relative_to(PROJECT_ROOT)),
        "image": str(image_path.relative_to(PROJECT_ROOT)),
        "pdf": str(pdf_path.relative_to(PROJECT_ROOT)),
    }


def copy_real_reference_images() -> None:
    target = RAW_ROOT / "real_references"
    target.mkdir(parents=True, exist_ok=True)
    source = PROJECT_ROOT / "data" / "raw" / "analyse_medical"
    if not source.exists():
        return
    for path in sorted(source.glob("*")):
        if path.suffix.lower() in {".jpg", ".jpeg", ".png", ".pdf"}:
            shutil.copy2(path, target / path.name)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=220)
    parser.add_argument("--seed", type=int, default=20260607)
    args = parser.parse_args()
    if args.count < 30:
        raise SystemExit("--count doit etre >= 30 pour avoir train/validation/test utiles.")

    ensure_dirs()
    rng = random.Random(args.seed)
    records: list[dict[str, str]] = []
    for index in range(1, args.count + 1):
        records.append(write_example(make_case(rng, index), rng))
    copy_real_reference_images()

    with MANIFEST_PATH.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["id", "input", "ground_truth", "image", "pdf"])
        writer.writeheader()
        writer.writerows(records)

    stats = {
        "generated": len(records),
        "inputs_dir": str(INPUT_ROOT.relative_to(PROJECT_ROOT)),
        "ground_truth_dir": str(GT_ROOT.relative_to(PROJECT_ROOT)),
        "raw_images_dir": str((RAW_ROOT / "images").relative_to(PROJECT_ROOT)),
        "raw_pdfs_dir": str((RAW_ROOT / "pdfs").relative_to(PROJECT_ROOT)),
        "manifest": str(MANIFEST_PATH.relative_to(PROJECT_ROOT)),
    }
    print(json.dumps(stats, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
