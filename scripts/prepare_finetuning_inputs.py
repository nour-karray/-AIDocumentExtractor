from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FINE_ROOT = PROJECT_ROOT / "data" / "finetuning"
INPUTS_ROOT = FINE_ROOT / "processed" / "inputs"
GT_ROOT = FINE_ROOT / "processed" / "ground_truth"
MANIFESTS_ROOT = FINE_ROOT / "manifests"

TECHNICAL_KEYS = {
    "_meta",
    "local_pipeline",
    "raw_text",
    "warnings",
    "extraction_quality",
    "extraction_source",
    "source_file",
    "file_name",
}

KIND_TO_TYPE = {
    "receipt": "receipt",
    "receipt_local": "receipt",
    "steg_ocr": "steg",
    "steg_gemini": "steg",
    "steg_local": "steg",
    "medical_ocr": "medical",
    "medical_gemini": "medical",
    "medical_local": "medical",
    "supplier_invoice": "supplier",
    "supplier_invoice_local": "supplier",
}

TYPE_TO_DOCUMENT_TYPE = {
    "receipt": "receipt",
    "steg": "steg_invoice",
    "medical": "medical_lab_report",
    "supplier": "supplier_invoice",
}


def safe_name(raw: str) -> str:
    value = re.sub(r"[^\w\-]+", "_", raw, flags=re.UNICODE).strip("._")
    return value[:120] or "document"


def ensure_dirs() -> None:
    for doc_type in ("receipt", "steg", "medical", "supplier"):
        (INPUTS_ROOT / doc_type).mkdir(parents=True, exist_ok=True)
        (GT_ROOT / doc_type).mkdir(parents=True, exist_ok=True)
    MANIFESTS_ROOT.mkdir(parents=True, exist_ok=True)


def read_json(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def clean_payload(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: clean_payload(item)
            for key, item in value.items()
            if key not in TECHNICAL_KEYS
        }
    if isinstance(value, list):
        return [clean_payload(item) for item in value]
    return value


def is_verified_for_finetuning(payload: dict[str, Any]) -> bool:
    meta = payload.get("_meta")
    if payload.get("finetuning_verified") is True:
        return True
    if isinstance(meta, dict) and meta.get("finetuning_verified") is True:
        return True
    return False


def write_pair(doc_family: str, example_id: str, input_text: str, output_json: dict[str, Any]) -> None:
    input_path = INPUTS_ROOT / doc_family / f"{example_id}.txt"
    gt_path = GT_ROOT / doc_family / f"{example_id}.json"
    input_path.write_text(input_text.strip() + "\n", encoding="utf-8")
    gt_path.write_text(json.dumps(output_json, ensure_ascii=False, indent=2), encoding="utf-8")


def sroie_box_to_text(path: Path) -> str:
    lines: list[str] = []
    for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        raw_line = raw_line.strip()
        if not raw_line:
            continue
        parts = raw_line.split(",", 8)
        lines.append(parts[8].strip() if len(parts) >= 9 else raw_line)
    return "\n".join(lines)


def convert_sroie_entities(raw: dict[str, Any]) -> dict[str, Any]:
    return {
        "document_type": "receipt",
        "store_name": str(raw.get("company") or "").strip(),
        "date": str(raw.get("date") or "").strip(),
        "time": "",
        "ticket_number": "",
        "currency": "",
        "items": [],
        "total": str(raw.get("total") or "").strip(),
        "payment_method": "",
        "address": str(raw.get("address") or "").strip(),
        "source_dataset": "sroie2019",
    }


def prepare_sroie(limit: int | None = None) -> dict[str, int]:
    stats = {"receipt": 0, "missing": 0}
    sroie_root = FINE_ROOT / "raw" / "kaggle" / "receipt_sroie"
    for split in ("train", "test"):
        box_dir = sroie_root / split / "box"
        entities_dir = sroie_root / split / "entities"
        if not box_dir.is_dir() or not entities_dir.is_dir():
            continue
        processed = 0
        for box_path in sorted(box_dir.glob("*.txt")):
            if limit is not None and processed >= limit:
                break
            entity_path = entities_dir / box_path.name
            entities = read_json(entity_path)
            if entities is None:
                stats["missing"] += 1
                continue
            input_text = "[METHOD_USED=sroie_box_ocr]\n\n" + sroie_box_to_text(box_path)
            output_json = convert_sroie_entities(entities)
            example_id = safe_name(f"sroie_{split}_{box_path.stem}")
            write_pair("receipt", example_id, input_text, output_json)
            stats["receipt"] += 1
            processed += 1
    return stats


def prepare_history_examples(
    limit: int | None = None,
    *,
    include_unverified: bool = False,
) -> dict[str, int]:
    stats: dict[str, int] = {"used": 0, "skipped": 0}
    history_root = PROJECT_ROOT / "data" / "history" / "extractions"
    if not history_root.is_dir():
        return stats
    processed = 0
    for json_path in sorted(history_root.rglob("*.json")):
        if limit is not None and processed >= limit:
            break
        payload = read_json(json_path)
        if not payload or payload.get("error"):
            stats["skipped"] += 1
            continue
        if not include_unverified and not is_verified_for_finetuning(payload):
            stats["skipped"] += 1
            continue
        kind = json_path.parent.name
        doc_family = KIND_TO_TYPE.get(kind)
        if not doc_family:
            stats["skipped"] += 1
            continue
        raw_text = payload.get("raw_text")
        if not isinstance(raw_text, str) or len(raw_text.strip()) < 80:
            stats["skipped"] += 1
            continue
        output_json = clean_payload(payload)
        output_json.setdefault("document_type", TYPE_TO_DOCUMENT_TYPE[doc_family])
        example_id = safe_name(f"history_{kind}_{json_path.stem}")
        input_text = "[METHOD_USED=history_raw_text]\n\n" + raw_text
        write_pair(doc_family, example_id, input_text, output_json)
        stats["used"] += 1
        stats[doc_family] = stats.get(doc_family, 0) + 1
        processed += 1
    return stats


def infer_doc_type(path: Path) -> str:
    parts = {part.casefold() for part in path.parts}
    text = str(path).casefold()
    if "steg" in parts or "electricite" in text or "facture steg" in text:
        return "steg_invoice"
    if "receipt" in parts or "tickets" in text or "ticket" in text or "caisse" in text:
        return "receipt"
    if "medical" in parts or "analyse" in text or "lbmaske" in text:
        return "medical_lab_report"
    if "supplier" in parts or "fournisseur" in text:
        return "supplier_invoice"
    return "unknown"


def write_unlabeled_manifest() -> int:
    raw_root = FINE_ROOT / "raw"
    manifest_path = MANIFESTS_ROOT / "unlabeled_documents.jsonl"
    supported = {".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".webp", ".bmp"}
    count = 0
    with manifest_path.open("w", encoding="utf-8") as handle:
        for path in sorted(raw_root.rglob("*")):
            if not path.is_file() or path.suffix.lower() not in supported:
                continue
            if "receipt_sroie" in [part.casefold() for part in path.parts]:
                continue
            row = {
                "path": str(path.relative_to(PROJECT_ROOT)),
                "document_type": infer_doc_type(path),
                "needs_ground_truth": True,
            }
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
            count += 1
    return count


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit-sroie", type=int, default=None)
    parser.add_argument("--limit-history", type=int, default=None)
    parser.add_argument(
        "--include-unverified-history",
        action="store_true",
        help="Use historical model outputs as training ground truth even if not manually verified.",
    )
    args = parser.parse_args()

    ensure_dirs()
    stats = {
        "sroie": prepare_sroie(args.limit_sroie),
        "history": prepare_history_examples(
            args.limit_history,
            include_unverified=args.include_unverified_history,
        ),
        "unlabeled_documents": write_unlabeled_manifest(),
    }
    stats_path = MANIFESTS_ROOT / "prepare_inputs_stats.json"
    stats_path.write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(stats, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
