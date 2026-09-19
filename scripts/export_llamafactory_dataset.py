from __future__ import annotations

import json
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SPLITS_ROOT = PROJECT_ROOT / "data" / "finetuning" / "splits"
OUTPUT_ROOT = PROJECT_ROOT / "data" / "finetuning" / "llamafactory"


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    if not path.exists():
        return records
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        payload = json.loads(line)
        if isinstance(payload, dict):
            records.append(payload)
    return records


def to_messages(example: dict[str, Any]) -> dict[str, Any]:
    output = example.get("output", {})
    output_text = json.dumps(output, ensure_ascii=False, separators=(",", ":"))
    instruction = str(example.get("instruction") or "").strip()
    document = str(example.get("input") or "").strip()
    user_content = f"{instruction}\n\nDocument:\n{document}".strip()
    return {
        "messages": [
            {"role": "user", "content": user_content},
            {"role": "assistant", "content": output_text},
        ]
    }


def write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def main() -> None:
    stats: dict[str, int] = {}
    for split in ("train", "validation", "test"):
        source_path = SPLITS_ROOT / f"{split}.jsonl"
        records = [to_messages(example) for example in read_jsonl(source_path)]
        target_name = "val.jsonl" if split == "validation" else f"{split}.jsonl"
        write_jsonl(OUTPUT_ROOT / target_name, records)
        stats[target_name] = len(records)

    dataset_info = {
        "docia_extraction": {
            "file_name": "train.jsonl",
            "formatting": "sharegpt",
            "columns": {"messages": "messages"},
        }
    }
    (OUTPUT_ROOT / "dataset_info.json").write_text(
        json.dumps(dataset_info, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (OUTPUT_ROOT / "stats.json").write_text(
        json.dumps(stats, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(stats, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
