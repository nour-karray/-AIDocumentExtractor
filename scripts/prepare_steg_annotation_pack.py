from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
FINE_ROOT = PROJECT_ROOT / "Data" / "finetuning"
INPUTS_ROOT = FINE_ROOT / "processed" / "inputs" / "steg"
GT_ROOT = FINE_ROOT / "processed" / "ground_truth" / "steg"
DRAFTS_ROOT = FINE_ROOT / "annotation_drafts" / "steg"
MANIFESTS_ROOT = FINE_ROOT / "manifests"

SUPPORTED_SUFFIXES = {".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".webp", ".bmp"}

STEG_EMPTY_GROUND_TRUTH = {
    "document_type": "steg_invoice",
    "reference": "",
    "numero_compteur": "",
    "date_facture": "",
    "montant_a_payer": "",
    "date_limite_paiement": "",
    "periode_du": "",
    "periode_au": "",
    "coupon_reference_raw": "",
    "coupon_montant": "",
    "confidence_note": "high",
}

REQUIRED_FOR_STEG = ("reference", "numero_compteur", "date_facture", "montant_a_payer")


def safe_name(raw: str) -> str:
    value = re.sub(r"[^\w\-]+", "_", raw, flags=re.UNICODE).strip("._")
    return value[:120] or "steg_document"


def rel(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(PROJECT_ROOT.resolve()))
    except ValueError:
        return str(path.resolve())


def read_json(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def normalize_draft(value: Any) -> dict[str, Any]:
    if hasattr(value, "__dataclass_fields__"):
        raw = asdict(value)
    elif isinstance(value, dict):
        raw = dict(value)
    else:
        raw = {}
    out = dict(STEG_EMPTY_GROUND_TRUTH)
    for key in out:
        if key == "document_type":
            continue
        item = raw.get(key)
        out[key] = "" if item is None else str(item).strip()
    out["document_type"] = "steg_invoice"
    return out


def extract_initial_steg_guess(path: Path) -> tuple[dict[str, Any], list[str]]:
    warnings: list[str] = []
    try:
        from src.extraction.steg_invoice_extractor import extract_fields_from_invoice

        return normalize_draft(extract_fields_from_invoice(path)), warnings
    except Exception as exc:
        warnings.append(f"steg_rule_extractor_failed: {type(exc).__name__}: {exc}")
        return dict(STEG_EMPTY_GROUND_TRUTH), warnings


def extract_training_input(path: Path) -> tuple[str, dict[str, Any], list[str]]:
    warnings: list[str] = []
    meta: dict[str, Any] = {}
    try:
        from src.services.local_docling_qwen import _content_for_extraction

        content = _content_for_extraction(path, mode="steg")
        meta = {
            "content_source": content.source,
            "docling_quality": content.docling_quality,
            "fallback_used": content.fallback_used,
            "fallback_quality": content.fallback_quality,
            "docling_error": content.docling_error,
            "fallback_error": content.fallback_error,
        }
        text = content.text.strip()
    except Exception as exc:
        warnings.append(f"content_extraction_failed: {type(exc).__name__}: {exc}")
        text = ""
        meta = {"content_source": "unavailable"}

    header = [
        "[DOCUMENT_TYPE=steg_invoice]",
        f"[SOURCE_FILE={rel(path)}]",
        f"[METHOD_USED={meta.get('content_source') or 'unknown'}]",
    ]
    return "\n".join(header) + "\n\n" + text, meta, warnings


def iter_sources(source_dirs: list[Path]) -> list[Path]:
    files: list[Path] = []
    for source_dir in source_dirs:
        if not source_dir.exists():
            continue
        if source_dir.is_file() and source_dir.suffix.lower() in SUPPORTED_SUFFIXES:
            files.append(source_dir)
            continue
        for path in sorted(source_dir.rglob("*")):
            if path.is_file() and path.suffix.lower() in SUPPORTED_SUFFIXES:
                files.append(path)
    return sorted(dict.fromkeys(files))


def make_example_id(path: Path, used: set[str]) -> str:
    base = safe_name(f"steg_{path.stem}")
    candidate = base
    index = 2
    while candidate in used:
        candidate = f"{base}_{index}"
        index += 1
    used.add(candidate)
    return candidate


def create_drafts(
    source_dirs: list[Path],
    *,
    limit: int | None,
    overwrite: bool,
    with_rule_draft: bool,
) -> dict[str, Any]:
    INPUTS_ROOT.mkdir(parents=True, exist_ok=True)
    DRAFTS_ROOT.mkdir(parents=True, exist_ok=True)
    MANIFESTS_ROOT.mkdir(parents=True, exist_ok=True)

    stats = {"created": 0, "skipped_existing": 0, "sources_missing": 0, "warnings": 0}
    queue_rows: list[dict[str, Any]] = []
    used: set[str] = set()
    files = iter_sources(source_dirs)
    if limit is not None:
        files = files[:limit]
    if not files:
        stats["sources_missing"] = len(source_dirs)

    for path in files:
        example_id = make_example_id(path, used)
        input_path = INPUTS_ROOT / f"{example_id}.txt"
        draft_path = DRAFTS_ROOT / f"{example_id}.json"
        gt_path = GT_ROOT / f"{example_id}.json"
        if draft_path.exists() and not overwrite:
            stats["skipped_existing"] += 1
            continue

        input_text, content_meta, input_warnings = extract_training_input(path)
        if with_rule_draft:
            draft, draft_warnings = extract_initial_steg_guess(path)
        else:
            draft, draft_warnings = dict(STEG_EMPTY_GROUND_TRUTH), []
        warnings = input_warnings + draft_warnings
        if warnings:
            stats["warnings"] += 1

        input_path.write_text(input_text.strip() + "\n", encoding="utf-8")
        payload = {
            "verified": False,
            "example_id": example_id,
            "source_path": rel(path),
            "input_path": rel(input_path),
            "ground_truth_path": rel(gt_path),
            "content_meta": content_meta,
            "warnings": warnings,
            "draft": draft,
            "ground_truth": draft,
            "review_instructions": [
                "Open the source image and correct ground_truth.",
                "Set verified to true only after manual validation.",
                "Run this script again with --promote-verified.",
            ],
        }
        write_json(draft_path, payload)
        queue_rows.append(
            {
                "example_id": example_id,
                "source_path": rel(path),
                "draft_path": rel(draft_path),
                "input_path": rel(input_path),
                "ground_truth_path": rel(gt_path),
                "verified": False,
            }
        )
        stats["created"] += 1

    queue_path = MANIFESTS_ROOT / "steg_annotation_review_queue.jsonl"
    with queue_path.open("w", encoding="utf-8") as handle:
        for row in queue_rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    stats["review_queue"] = rel(queue_path)
    return stats


def promote_verified() -> dict[str, Any]:
    GT_ROOT.mkdir(parents=True, exist_ok=True)
    stats = {"promoted": 0, "skipped_unverified": 0, "missing_required": 0}
    for draft_path in sorted(DRAFTS_ROOT.glob("*.json")):
        draft = read_json(draft_path)
        if not draft:
            continue
        if draft.get("verified") is not True:
            stats["skipped_unverified"] += 1
            continue
        ground_truth = draft.get("ground_truth")
        if not isinstance(ground_truth, dict):
            stats["missing_required"] += 1
            continue
        normalized = dict(STEG_EMPTY_GROUND_TRUTH)
        for key in normalized:
            if key == "document_type":
                continue
            value = ground_truth.get(key)
            normalized[key] = "" if value is None else str(value).strip()
        normalized["document_type"] = "steg_invoice"

        missing = [key for key in REQUIRED_FOR_STEG if not normalized.get(key)]
        if missing:
            draft["promotion_warning"] = f"Missing required fields: {', '.join(missing)}"
            write_json(draft_path, draft)
            stats["missing_required"] += 1
            continue

        example_id = str(draft.get("example_id") or draft_path.stem)
        write_json(GT_ROOT / f"{safe_name(example_id)}.json", normalized)
        stats["promoted"] += 1
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Prepare STEG annotation drafts for DocIA fine-tuning."
    )
    parser.add_argument(
        "--source",
        action="append",
        default=[],
        help="Folder or file containing STEG invoices. Can be repeated.",
    )
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--promote-verified", action="store_true")
    parser.add_argument(
        "--with-rule-draft",
        action="store_true",
        help="Also run the heavy STEG rule extractor to prefill draft fields.",
    )
    args = parser.parse_args()

    source_dirs = [Path(item) for item in args.source]
    if not source_dirs:
        source_dirs = [
            PROJECT_ROOT / "data" / "raw" / "electricite",
            PROJECT_ROOT / "data" / "raw" / "electricite_copy",
            FINE_ROOT / "raw" / "custom" / "steg",
            FINE_ROOT / "raw" / "generated" / "steg",
        ]

    stats = {
        "drafts": create_drafts(
            source_dirs,
            limit=args.limit,
            overwrite=args.overwrite,
            with_rule_draft=args.with_rule_draft,
        ),
    }
    if args.promote_verified:
        stats["promotion"] = promote_verified()
    print(json.dumps(stats, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
