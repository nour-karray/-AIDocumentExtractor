from __future__ import annotations

import argparse
import json
import random
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FINE_ROOT = PROJECT_ROOT / "data" / "finetuning"
INPUTS_ROOT = FINE_ROOT / "processed" / "inputs"
GT_ROOT = FINE_ROOT / "processed" / "ground_truth"
SPLITS_ROOT = FINE_ROOT / "splits"

DEFAULT_INSTRUCTION = (
    "Extrais les informations importantes du document et retourne uniquement "
    "un JSON valide conforme au type du document."
)


def read_json(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def iter_examples() -> list[dict[str, Any]]:
    examples: list[dict[str, Any]] = []
    if not INPUTS_ROOT.is_dir():
        return examples

    for input_path in sorted(INPUTS_ROOT.rglob("*.txt")):
        doc_family = input_path.parent.name
        gt_path = GT_ROOT / doc_family / f"{input_path.stem}.json"
        output_json = read_json(gt_path)
        if output_json is None:
            continue

        input_text = input_path.read_text(encoding="utf-8", errors="replace").strip()
        if not input_text:
            continue

        examples.append(
            {
                "instruction": DEFAULT_INSTRUCTION,
                "input": input_text,
                "output": output_json,
                "metadata": {
                    "id": input_path.stem,
                    "document_family": doc_family,
                    "input_path": str(input_path.relative_to(PROJECT_ROOT)),
                    "ground_truth_path": str(gt_path.relative_to(PROJECT_ROOT)),
                },
            }
        )
    return examples


def split_examples(
    examples: list[dict[str, Any]],
    train_ratio: float,
    validation_ratio: float,
    seed: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for example in examples:
        family = str(example.get("metadata", {}).get("document_family") or "unknown")
        grouped[family].append(example)

    train: list[dict[str, Any]] = []
    validation: list[dict[str, Any]] = []
    test: list[dict[str, Any]] = []

    rng = random.Random(seed)
    for family in sorted(grouped):
        shuffled = list(grouped[family])
        rng.shuffle(shuffled)
        total = len(shuffled)
        if total == 0:
            continue
        if total == 1:
            train.extend(shuffled)
            continue
        if total == 2:
            train.extend(shuffled[:1])
            validation.extend(shuffled[1:])
            continue

        train_count = max(1, int(total * train_ratio))
        validation_count = max(1, int(total * validation_ratio))

        if train_count + validation_count >= total:
            train_count = total - 2
            validation_count = 1

        train.extend(shuffled[:train_count])
        validation.extend(shuffled[train_count : train_count + validation_count])
        test.extend(shuffled[train_count + validation_count :])

    rng.shuffle(train)
    rng.shuffle(validation)
    rng.shuffle(test)

    total = len(examples)
    if total == 0:
        return [], [], []
    return train, validation, test


def save_jsonl(path: Path, examples: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for example in examples:
            handle.write(json.dumps(example, ensure_ascii=False) + "\n")


def family_counts(examples: list[dict[str, Any]]) -> dict[str, int]:
    counts = Counter(
        str(example.get("metadata", {}).get("document_family", "unknown"))
        for example in examples
    )
    return dict(sorted(counts.items()))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--train-ratio", type=float, default=0.70)
    parser.add_argument("--validation-ratio", type=float, default=0.15)
    args = parser.parse_args()

    if args.train_ratio <= 0 or args.validation_ratio < 0:
        raise SystemExit("Les ratios doivent etre positifs.")
    if args.train_ratio + args.validation_ratio >= 1:
        raise SystemExit("train-ratio + validation-ratio doit etre < 1.")

    SPLITS_ROOT.mkdir(parents=True, exist_ok=True)
    examples = iter_examples()
    train, validation, test = split_examples(
        examples,
        train_ratio=args.train_ratio,
        validation_ratio=args.validation_ratio,
        seed=args.seed,
    )

    save_jsonl(SPLITS_ROOT / "train.jsonl", train)
    save_jsonl(SPLITS_ROOT / "validation.jsonl", validation)
    save_jsonl(SPLITS_ROOT / "test.jsonl", test)

    stats = {
        "total": len(examples),
        "train": len(train),
        "validation": len(validation),
        "test": len(test),
        "by_family": family_counts(examples),
        "splits_by_family": {
            "train": family_counts(train),
            "validation": family_counts(validation),
            "test": family_counts(test),
        },
        "seed": args.seed,
    }
    (SPLITS_ROOT / "stats.json").write_text(
        json.dumps(stats, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(stats, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
