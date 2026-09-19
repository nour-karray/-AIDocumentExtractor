from __future__ import annotations

import argparse
import csv
import json
import math
import re
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    from dateutil import parser as date_parser
except Exception:  # pragma: no cover - optional at runtime
    date_parser = None


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SPLIT_PATH = PROJECT_ROOT / "data" / "finetuning" / "splits" / "test.jsonl"
DEFAULT_OUTPUT_ROOT = PROJECT_ROOT / "outputs" / "evaluation_metrics"

SCALAR_FIELDS: dict[str, tuple[str, ...]] = {
    "receipt": (
        "document_type",
        "store_name",
        "date",
        "time",
        "ticket_number",
        "currency",
        "total",
        "payment_method",
        "address",
    ),
    "medical": (
        "document_type",
        "lab_info.lab_name",
        "lab_info.doctor_name",
        "patient_info.patient_name",
        "patient_info.patient_id",
        "patient_info.sex",
        "document_metadata.exam_number",
        "document_metadata.dossier_number",
        "document_metadata.sample_date",
        "document_metadata.report_date",
    ),
    "steg": (
        "document_type",
        "reference",
        "montant_a_payer",
        "date_limite_paiement",
        "periode_du",
        "periode_au",
        "coupon_reference_raw",
        "coupon_montant",
    ),
    "supplier": (
        "document_type",
        "invoice_number",
        "invoice_date",
        "due_date",
        "currency",
        "seller.name",
        "seller.tax_id",
        "client.name",
        "client.tax_id",
        "summary.total_amount",
        "summary.amount_due",
    ),
}


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _nested(payload: dict[str, Any], path: str) -> Any:
    current: Any = payload
    for part in path.split("."):
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


def _meaningful(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, bool):
        return True
    if isinstance(value, (int, float)):
        return not (isinstance(value, float) and math.isnan(value))
    if isinstance(value, str):
        return value.strip().casefold() not in {"", "null", "none", "n/a", "na", "non detecte", "inconnu"}
    if isinstance(value, list):
        return bool(value)
    if isinstance(value, dict):
        return any(_meaningful(item) for item in value.values())
    return True


def _strip_accents(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def _norm_text(value: Any) -> str:
    text = _strip_accents(str(value or "").casefold())
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def _compact(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", _norm_text(value))


def _number(value: Any) -> float | None:
    text = str(value or "").strip().replace("\u00a0", " ").replace(" ", "")
    if not text:
        return None
    matches = re.findall(r"\d+(?:[,.]\d+)?", text)
    if not matches:
        return None
    token = matches[-1]
    if "," in token and "." in token:
        token = token.replace(",", "")
    elif "," in token:
        token = token.replace(",", ".")
    try:
        return float(token)
    except ValueError:
        return None


def _date_key(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    if date_parser is not None:
        try:
            parsed = date_parser.parse(text, dayfirst=True, fuzzy=True)
            return parsed.date().isoformat()
        except Exception:
            pass
    digits = re.sub(r"\D+", "", text)
    return digits or None


def _similarity(a: Any, b: Any) -> float:
    aa = _norm_text(a)
    bb = _norm_text(b)
    if not aa or not bb:
        return 0.0
    if aa == bb:
        return 1.0
    try:
        from rapidfuzz import fuzz

        return float(fuzz.token_set_ratio(aa, bb)) / 100.0
    except Exception:
        from difflib import SequenceMatcher

        return SequenceMatcher(None, aa, bb).ratio()


def _values_match(field: str, expected: Any, actual: Any) -> bool:
    if not _meaningful(expected):
        return not _meaningful(actual)
    if not _meaningful(actual):
        return False

    field_l = field.casefold()
    if any(key in field_l for key in ("amount", "montant", "total", "value", "prix")):
        exp_num = _number(expected)
        act_num = _number(actual)
        if exp_num is not None and act_num is not None:
            return abs(exp_num - act_num) <= 0.01

    if "date" in field_l:
        exp_date = _date_key(expected)
        act_date = _date_key(actual)
        if exp_date and act_date:
            return exp_date == act_date

    exp = _compact(expected)
    act = _compact(actual)
    if exp and act and exp == act:
        return True
    if len(exp) >= 6 and len(act) >= 6 and (exp in act or act in exp):
        return True
    return _similarity(expected, actual) >= 0.92


def _family_from_record(record: dict[str, Any], gt: dict[str, Any]) -> str:
    meta = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
    family = str(meta.get("document_family") or "").strip().casefold()
    if family:
        return family
    dtype = str(gt.get("document_type") or "").casefold()
    if "medical" in dtype:
        return "medical"
    if "receipt" in dtype:
        return "receipt"
    if "steg" in dtype:
        return "steg"
    if "supplier" in dtype or "invoice" in dtype:
        return "supplier"
    return "unknown"


def _record_id(record: dict[str, Any]) -> str:
    meta = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
    if meta.get("id"):
        return str(meta["id"])
    gt_path = Path(str(meta.get("ground_truth_path") or ""))
    return gt_path.stem


def _prediction_index(predictions_dir: Path) -> dict[str, Path]:
    index: dict[str, Path] = {}
    if not predictions_dir.is_dir():
        return index
    for path in predictions_dir.rglob("*.json"):
        stem = path.stem
        index.setdefault(stem, path)
        # Also support files exported with timestamps before the real stem.
        parts = stem.split("_")
        for i in range(len(parts)):
            candidate = "_".join(parts[i:])
            if candidate:
                index.setdefault(candidate, path)
    return index


def _find_prediction(index: dict[str, Path], record: dict[str, Any]) -> Path | None:
    meta = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
    rid = _record_id(record)
    gt_stem = Path(str(meta.get("ground_truth_path") or "")).stem
    input_stem = Path(str(meta.get("input_path") or "")).stem
    for key in (rid, gt_stem, input_stem):
        if key and key in index:
            return index[key]
    return None


def _unwrap_prediction(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return {}
    if isinstance(raw.get("payload"), dict):
        return raw["payload"]
    if isinstance(raw.get("result"), dict):
        return raw["result"]
    return raw


def _medical_test_key(row: dict[str, Any]) -> str:
    return _compact(row.get("normalized_name") or row.get("raw_test_name") or row.get("test_name"))


def _evaluate_medical_tests(gt: dict[str, Any], pred: dict[str, Any]) -> dict[str, int]:
    counts = {"tp": 0, "fp": 0, "fn": 0, "expected": 0, "correct": 0}
    gt_rows = gt.get("tests")
    pred_rows = pred.get("tests") or pred.get("analyses")
    if not isinstance(gt_rows, list):
        gt_rows = []
    if not isinstance(pred_rows, list):
        pred_rows = []

    pred_by_key: dict[str, dict[str, Any]] = {}
    for row in pred_rows:
        if isinstance(row, dict):
            key = _medical_test_key(row)
            if key:
                pred_by_key.setdefault(key, row)

    matched_pred_keys: set[str] = set()
    for gt_row in gt_rows:
        if not isinstance(gt_row, dict):
            continue
        key = _medical_test_key(gt_row)
        if not key:
            continue
        counts["expected"] += 1
        pred_row = pred_by_key.get(key)
        if pred_row is None:
            # Fuzzy fallback by test name.
            best_key = ""
            best_score = 0.0
            for pred_key, candidate in pred_by_key.items():
                score = _similarity(
                    gt_row.get("raw_test_name") or gt_row.get("normalized_name"),
                    candidate.get("raw_test_name") or candidate.get("test_name") or candidate.get("normalized_name"),
                )
                if score > best_score:
                    best_key, best_score = pred_key, score
            if best_score >= 0.90:
                pred_row = pred_by_key[best_key]
                key = best_key
        if pred_row is None:
            counts["fn"] += 1
            continue
        matched_pred_keys.add(key)
        value_ok = _values_match("tests.value", gt_row.get("value"), pred_row.get("value") or pred_row.get("value_text"))
        unit_expected = gt_row.get("unit")
        unit_actual = pred_row.get("unit")
        unit_ok = True if not _meaningful(unit_expected) else _values_match("tests.unit", unit_expected, unit_actual)
        if value_ok and unit_ok:
            counts["tp"] += 1
            counts["correct"] += 1
        else:
            counts["fp"] += 1
            counts["fn"] += 1

    for row in pred_rows:
        if isinstance(row, dict):
            key = _medical_test_key(row)
            if key and key not in matched_pred_keys:
                counts["fp"] += 1
    return counts


def _empty_counts() -> dict[str, int]:
    return {
        "documents": 0,
        "predicted_documents": 0,
        "valid_json": 0,
        "classification_expected": 0,
        "classification_correct": 0,
        "tp": 0,
        "fp": 0,
        "fn": 0,
        "field_expected": 0,
        "field_correct": 0,
    }


def _merge_counts(target: dict[str, int], source: dict[str, int]) -> None:
    for key, value in source.items():
        target[key] = int(target.get(key, 0)) + int(value)


def _rates(counts: dict[str, int]) -> dict[str, float | int]:
    tp = counts.get("tp", 0)
    fp = counts.get("fp", 0)
    fn = counts.get("fn", 0)
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if precision + recall else 0.0
    docs = counts.get("documents", 0)
    predicted_docs = counts.get("predicted_documents", 0)
    field_expected = counts.get("field_expected", 0)
    class_expected = counts.get("classification_expected", 0)
    return {
        **counts,
        "coverage": round(predicted_docs / docs, 4) if docs else 0.0,
        "valid_json_rate": round(counts.get("valid_json", 0) / predicted_docs, 4) if predicted_docs else 0.0,
        "classification_accuracy": round(counts.get("classification_correct", 0) / class_expected, 4) if class_expected else 0.0,
        "field_accuracy": round(counts.get("field_correct", 0) / field_expected, 4) if field_expected else 0.0,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
    }


def _evaluate_record(record: dict[str, Any], gt: dict[str, Any], pred: dict[str, Any] | None, *, valid_json: bool) -> dict[str, int]:
    family = _family_from_record(record, gt)
    counts = _empty_counts()
    counts["documents"] = 1
    if pred is None:
        return counts
    counts["predicted_documents"] = 1
    if valid_json:
        counts["valid_json"] = 1

    pred = pred or {}
    gt_type = gt.get("document_type")
    pred_type = pred.get("document_type")
    if _meaningful(gt_type):
        counts["classification_expected"] = 1
        if _values_match("document_type", gt_type, pred_type):
            counts["classification_correct"] = 1

    for field in SCALAR_FIELDS.get(family, ()):
        expected = _nested(gt, field)
        actual = _nested(pred, field)
        if _meaningful(expected):
            counts["field_expected"] += 1
            if _values_match(field, expected, actual):
                counts["tp"] += 1
                counts["field_correct"] += 1
            elif _meaningful(actual):
                counts["fp"] += 1
                counts["fn"] += 1
            else:
                counts["fn"] += 1
        elif _meaningful(actual):
            counts["fp"] += 1

    if family == "medical":
        test_counts = _evaluate_medical_tests(gt, pred)
        counts["tp"] += test_counts["tp"]
        counts["fp"] += test_counts["fp"]
        counts["fn"] += test_counts["fn"]
        counts["field_expected"] += test_counts["expected"]
        counts["field_correct"] += test_counts["correct"]
    return counts


def _pipeline_dirs(predictions_root: Path) -> list[tuple[str, Path]]:
    if not predictions_root.is_dir():
        return []
    children = [p for p in predictions_root.iterdir() if p.is_dir()]
    if children:
        return [(p.name, p) for p in sorted(children)]
    return [(predictions_root.name, predictions_root)]


def _dataset_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    by_family: Counter[str] = Counter()
    for record in records:
        meta = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
        gt_path = PROJECT_ROOT / str(meta.get("ground_truth_path") or "")
        gt = _read_json(gt_path) if gt_path.is_file() else {}
        by_family[_family_from_record(record, gt)] += 1
    return {
        "total": len(records),
        "by_family": dict(sorted(by_family.items())),
    }


def _write_report(output_dir: Path, summary: dict[str, Any]) -> None:
    lines: list[str] = []
    lines.append("# Evaluation quantitative des pipelines DocIA")
    lines.append("")
    lines.append(f"Run: `{summary['run_id']}`")
    lines.append("")
    lines.append("## Dataset")
    lines.append("")
    lines.append(f"- Split: `{summary['split_path']}`")
    lines.append(f"- Documents: **{summary['dataset']['total']}**")
    for family, count in summary["dataset"]["by_family"].items():
        lines.append(f"- {family}: {count}")
    lines.append("")
    lines.append("## Lecture correcte des metriques")
    lines.append("")
    lines.append("- `coverage`: part des documents qui ont une prediction disponible.")
    lines.append("- `valid_json_rate`: part des predictions qui sont des JSON lisibles.")
    lines.append("- `classification_accuracy`: exactitude du type de document.")
    lines.append("- `field_accuracy`: champs attendus correctement extraits.")
    lines.append("- `precision`, `recall`, `f1`: calcules champ par champ sur les valeurs JSON.")
    lines.append("")
    if not summary["pipelines"]:
        lines.append("Aucune prediction n'a ete trouvee. Ce rapport decrit le dataset et la methode; lance les pipelines puis place les JSON dans `outputs/evaluation_metrics/predictions/<pipeline>/`.")
    else:
        lines.append("## Resultats par pipeline")
        lines.append("")
        lines.append("| Pipeline | Coverage | JSON valide | Type acc. | Field acc. | Precision | Recall | F1 |")
        lines.append("| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |")
        for name, data in summary["pipelines"].items():
            overall = data["overall"]
            lines.append(
                "| {name} | {coverage:.1%} | {valid:.1%} | {cls:.1%} | {field:.1%} | {precision:.3f} | {recall:.3f} | {f1:.3f} |".format(
                    name=name,
                    coverage=float(overall["coverage"]),
                    valid=float(overall["valid_json_rate"]),
                    cls=float(overall["classification_accuracy"]),
                    field=float(overall["field_accuracy"]),
                    precision=float(overall["precision"]),
                    recall=float(overall["recall"]),
                    f1=float(overall["f1"]),
                )
            )
        lines.append("")
        lines.append("## Resultats par famille")
        lines.append("")
        for name, data in summary["pipelines"].items():
            lines.append(f"### {name}")
            lines.append("")
            lines.append("| Famille | Docs | Coverage | Field acc. | Precision | Recall | F1 |")
            lines.append("| --- | ---: | ---: | ---: | ---: | ---: | ---: |")
            for family, rates in data["by_family"].items():
                lines.append(
                    "| {family} | {docs} | {coverage:.1%} | {field:.1%} | {precision:.3f} | {recall:.3f} | {f1:.3f} |".format(
                        family=family,
                        docs=int(rates["documents"]),
                        coverage=float(rates["coverage"]),
                        field=float(rates["field_accuracy"]),
                        precision=float(rates["precision"]),
                        recall=float(rates["recall"]),
                        f1=float(rates["f1"]),
                    )
                )
            lines.append("")
    (output_dir / "report.md").write_text("\n".join(lines), encoding="utf-8")


def evaluate(split_path: Path, predictions_root: Path | None, output_root: Path) -> dict[str, Any]:
    records = _load_jsonl(split_path)
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = output_root / run_id
    output_dir.mkdir(parents=True, exist_ok=True)

    summary: dict[str, Any] = {
        "run_id": run_id,
        "split_path": str(split_path.relative_to(PROJECT_ROOT) if split_path.is_relative_to(PROJECT_ROOT) else split_path),
        "dataset": _dataset_summary(records),
        "pipelines": {},
        "output_dir": str(output_dir),
    }

    pipeline_dirs = _pipeline_dirs(predictions_root) if predictions_root else []
    rows_for_csv: list[dict[str, Any]] = []
    for pipeline_name, pred_dir in pipeline_dirs:
        index = _prediction_index(pred_dir)
        overall_counts = _empty_counts()
        family_counts: dict[str, dict[str, int]] = defaultdict(_empty_counts)

        for record in records:
            meta = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
            gt_path = PROJECT_ROOT / str(meta.get("ground_truth_path") or "")
            if not gt_path.is_file():
                continue
            gt = _read_json(gt_path)
            family = _family_from_record(record, gt)
            pred_path = _find_prediction(index, record)
            valid_json = False
            pred_payload: dict[str, Any] | None = None
            error = ""
            if pred_path is not None:
                try:
                    pred_payload = _unwrap_prediction(_read_json(pred_path))
                    valid_json = isinstance(pred_payload, dict)
                except Exception as exc:
                    pred_payload = {}
                    error = f"{type(exc).__name__}: {exc}"
            counts = _evaluate_record(record, gt, pred_payload, valid_json=valid_json)
            _merge_counts(overall_counts, counts)
            _merge_counts(family_counts[family], counts)
            rows_for_csv.append(
                {
                    "pipeline": pipeline_name,
                    "id": _record_id(record),
                    "family": family,
                    "prediction_found": pred_path is not None,
                    "prediction_path": str(pred_path) if pred_path else "",
                    "valid_json": valid_json,
                    "tp": counts["tp"],
                    "fp": counts["fp"],
                    "fn": counts["fn"],
                    "field_expected": counts["field_expected"],
                    "field_correct": counts["field_correct"],
                    "error": error,
                }
            )

        summary["pipelines"][pipeline_name] = {
            "predictions_dir": str(pred_dir),
            "overall": _rates(overall_counts),
            "by_family": {family: _rates(counts) for family, counts in sorted(family_counts.items())},
        }

    (output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    with (output_dir / "per_document.csv").open("w", encoding="utf-8", newline="") as handle:
        fieldnames = [
            "pipeline",
            "id",
            "family",
            "prediction_found",
            "prediction_path",
            "valid_json",
            "tp",
            "fp",
            "fn",
            "field_expected",
            "field_correct",
            "error",
        ]
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows_for_csv)
    _write_report(output_dir, summary)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Calcule accuracy, precision, recall et F1 pour les sorties JSON des pipelines DocIA."
    )
    parser.add_argument("--split", type=Path, default=DEFAULT_SPLIT_PATH)
    parser.add_argument(
        "--predictions-root",
        type=Path,
        default=None,
        help="Dossier contenant un sous-dossier par pipeline avec les JSON predits.",
    )
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    args = parser.parse_args()

    split_path = args.split if args.split.is_absolute() else PROJECT_ROOT / args.split
    predictions_root = None
    if args.predictions_root is not None:
        predictions_root = args.predictions_root if args.predictions_root.is_absolute() else PROJECT_ROOT / args.predictions_root
    output_root = args.output_root if args.output_root.is_absolute() else PROJECT_ROOT / args.output_root

    summary = evaluate(split_path, predictions_root, output_root)
    print(f"Evaluation creee: {summary['output_dir']}")
    print(f"Dataset: {summary['dataset']['total']} documents")
    if not summary["pipelines"]:
        print("Aucune prediction evaluee. Ajoute --predictions-root pour calculer les metriques par pipeline.")
    for name, data in summary["pipelines"].items():
        overall = data["overall"]
        print(
            f"{name}: F1={overall['f1']:.3f} precision={overall['precision']:.3f} "
            f"recall={overall['recall']:.3f} coverage={overall['coverage']:.1%}"
        )


if __name__ == "__main__":
    main()
