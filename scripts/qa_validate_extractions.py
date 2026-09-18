from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_ROOT = PROJECT_ROOT / "outputs" / "qa_validation"
PYTHON_EXE = Path(sys.executable)


def _default_env() -> dict[str, str]:
    env = os.environ.copy()
    env.setdefault("DOCIA_EXTRACTION_TIMEOUT_SECONDS", "180")
    env.setdefault("LOCAL_PIPELINE_PADDLEOCR_TIMEOUT_SECONDS", "8")
    env.setdefault("LOCAL_PIPELINE_FAST_OCR_TIMEOUT_SECONDS", "12")
    env.setdefault("LOCAL_PIPELINE_CONTENT_CHARS", "12000")
    env.setdefault("OLLAMA_GENERATE_TIMEOUT_SECONDS", "90")
    env.setdefault("OLLAMA_NUM_PREDICT", "768")
    env.setdefault("PYTHONPATH", str(PROJECT_ROOT))
    if str(PROJECT_ROOT) not in env["PYTHONPATH"].split(os.pathsep):
        env["PYTHONPATH"] = str(PROJECT_ROOT) + os.pathsep + env["PYTHONPATH"]
    return env


CASES: dict[str, dict[str, Any]] = {
    "detect_steg4": {
        "kind": "detect",
        "family": "steg",
        "path": "Data/raw_Data/electricite/STEG4.jpg",
        "expected_detected": "steg_invoice",
        "timeout": 45,
    },
    "detect_medical_analyse4": {
        "kind": "detect",
        "family": "medical",
        "path": "Data/raw_Data/medical/analyse4.jpg",
        "expected_detected": "medical_lab_report",
        "timeout": 45,
    },
    "detect_receipt_zara": {
        "kind": "detect",
        "family": "receipt",
        "path": "Data/raw_Data/ticketsCasse/653973815_807492965211716_7703161301681833911_n.jpg",
        "expected_detected": "receipt",
        "timeout": 45,
    },
    "detect_supplier_ar": {
        "kind": "detect",
        "family": "supplier",
        "path": "Data/history/extractions/supplier_invoice/20260510T194207Z_facture2.png",
        "expected_detected": "supplier_invoice",
        "timeout": 45,
    },
    "steg4_local": {
        "family": "steg",
        "method": "local",
        "mode": "steg",
        "path": "Data/raw_Data/electricite/STEG4.jpg",
        "timeout": 150,
    },
    "steg4_ocr": {
        "family": "steg",
        "method": "ocr",
        "mode": "steg",
        "path": "Data/raw_Data/electricite/STEG4.jpg",
        "timeout": 150,
    },
    "medical_analyse4_local": {
        "family": "medical",
        "method": "local",
        "mode": "medical",
        "path": "Data/raw_Data/medical/analyse4.jpg",
        "timeout": 120,
    },
    "medical_analyse4_ocr": {
        "family": "medical",
        "method": "ocr",
        "mode": "medical",
        "path": "Data/raw_Data/medical/analyse4.jpg",
        "timeout": 120,
    },
    "receipt_zara_local": {
        "family": "receipt",
        "method": "local",
        "mode": "receipt",
        "path": "Data/raw_Data/ticketsCasse/653973815_807492965211716_7703161301681833911_n.jpg",
        "timeout": 180,
    },
    "receipt_zara_ocr_expected_error": {
        "family": "receipt",
        "method": "ocr",
        "mode": "receipt",
        "path": "Data/raw_Data/ticketsCasse/653973815_807492965211716_7703161301681833911_n.jpg",
        "timeout": 45,
    },
    "supplier_ar_local": {
        "family": "supplier",
        "method": "local",
        "mode": "supplier",
        "path": "Data/history/extractions/supplier_invoice/20260510T194207Z_facture2.png",
        "timeout": 180,
    },
    "supplier_ar_ocr_expected_error": {
        "family": "supplier",
        "method": "ocr",
        "mode": "supplier",
        "path": "Data/history/extractions/supplier_invoice/20260510T194207Z_facture2.png",
        "timeout": 45,
    },
    "steg4_gemini": {
        "family": "steg",
        "method": "gemini",
        "mode": "steg",
        "path": "Data/raw_Data/electricite/STEG4.jpg",
        "gemini": True,
        "timeout": 180,
    },
    "medical_analyse4_gemini": {
        "family": "medical",
        "method": "gemini",
        "mode": "medical",
        "path": "Data/raw_Data/medical/analyse4.jpg",
        "gemini": True,
        "timeout": 180,
    },
    "receipt_zara_gemini": {
        "family": "receipt",
        "method": "gemini",
        "mode": "receipt",
        "path": "Data/raw_Data/ticketsCasse/653973815_807492965211716_7703161301681833911_n.jpg",
        "gemini": True,
        "timeout": 180,
    },
    "supplier_ar_gemini": {
        "family": "supplier",
        "method": "gemini",
        "mode": "supplier",
        "path": "Data/history/extractions/supplier_invoice/20260510T194207Z_facture2.png",
        "gemini": True,
        "timeout": 180,
    },
}


def _nested(payload: dict[str, Any], path: str) -> Any:
    current: Any = payload
    for part in path.split("."):
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


def _compact(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").casefold())


def _digits(value: Any) -> str:
    return re.sub(r"\D+", "", str(value or ""))


def _amount_digits(value: Any) -> str:
    return re.sub(r"\D+", "", str(value or ""))


def _contains(actual: Any, expected: str) -> bool:
    actual_norm = _compact(actual)
    expected_norm = _compact(expected)
    return bool(expected_norm and expected_norm in actual_norm)


def _amount_matches(actual: Any, expected: str) -> bool:
    def parse(value: Any) -> float | None:
        text = str(value or "").strip().replace(" ", "")
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

    actual_value = parse(actual)
    expected_value = parse(expected)
    if actual_value is None or expected_value is None:
        return False
    return abs(actual_value - expected_value) <= 0.01


def _list_len(payload: dict[str, Any], path: str) -> int:
    value = _nested(payload, path)
    return len(value) if isinstance(value, list) else 0


def _test_names(payload: dict[str, Any]) -> str:
    rows = payload.get("tests") or payload.get("analyses") or []
    if not isinstance(rows, list):
        return ""
    names: list[str] = []
    for row in rows:
        if isinstance(row, dict):
            names.append(
                str(row.get("raw_test_name") or row.get("test_name") or row.get("normalized_name") or "")
            )
    return "\n".join(names).casefold()


def _checks_for(case_id: str) -> list[tuple[str, str, Callable[[dict[str, Any]], bool], Callable[[dict[str, Any]], Any]]]:
    return {
        "steg4_local": [
            ("reference", "reference 74726 880 0", lambda p: _digits(p.get("reference")) == "747268800", lambda p: p.get("reference")),
            ("montant_a_payer", "montant 645,000", lambda p: _amount_matches(p.get("montant_a_payer"), "645,000"), lambda p: p.get("montant_a_payer")),
            ("date_limite_paiement", "date limite 2024-08-28", lambda p: "2024-08-28" in str(p.get("date_limite_paiement") or ""), lambda p: p.get("date_limite_paiement")),
        ],
        "steg4_ocr": [
            ("reference", "reference 74726 880 0", lambda p: _digits(p.get("reference")) == "747268800", lambda p: p.get("reference")),
            ("montant_a_payer", "montant 645,000", lambda p: _amount_matches(p.get("montant_a_payer"), "645,000"), lambda p: p.get("montant_a_payer")),
        ],
        "medical_analyse4_local": [
            ("patient_id", "ID patient CP994", lambda p: _contains(_nested(p, "patient_info.patient_id"), "CP994"), lambda p: _nested(p, "patient_info.patient_id")),
            ("patient_name", "nom patient IMTINENE GADDOUR", lambda p: _contains(_nested(p, "patient_info.patient_name"), "IMTINENE GADDOUR"), lambda p: _nested(p, "patient_info.patient_name")),
            ("dossier_number", "dossier 240819/9129", lambda p: _contains(_nested(p, "document_metadata.dossier_number"), "240819/9129"), lambda p: _nested(p, "document_metadata.dossier_number")),
            ("tests_count", "au moins 6 lignes d'analyses", lambda p: _list_len(p, "tests") >= 6, lambda p: _list_len(p, "tests")),
            ("vitamine_d", "Vitamine D detectee", lambda p: "vitamine" in _test_names(p) or "vitamin" in _test_names(p), lambda p: _test_names(p)),
            ("tsh", "TSH detectee", lambda p: "tsh" in _test_names(p) or "thyreo" in _test_names(p), lambda p: _test_names(p)),
        ],
        "medical_analyse4_ocr": [
            ("patient_id", "ID patient CP994", lambda p: _contains(_nested(p, "patient_info.patient_id"), "CP994"), lambda p: _nested(p, "patient_info.patient_id")),
            ("patient_name", "nom patient IMTINENE GADDOUR", lambda p: _contains(_nested(p, "patient_info.patient_name"), "IMTINENE GADDOUR"), lambda p: _nested(p, "patient_info.patient_name")),
            ("tests_count", "au moins 6 lignes d'analyses", lambda p: _list_len(p, "tests") >= 6, lambda p: _list_len(p, "tests")),
        ],
        "receipt_zara_local": [
            ("store_name", "magasin ZARA", lambda p: _contains(p.get("store_name"), "ZARA"), lambda p: p.get("store_name")),
            ("ticket_number", "ticket 59447", lambda p: _contains(p.get("ticket_number"), "59447"), lambda p: p.get("ticket_number")),
            ("total", "total 308,700", lambda p: _amount_matches(p.get("total"), "308,700"), lambda p: p.get("total")),
            ("items_count", "au moins 5 articles", lambda p: _list_len(p, "items") >= 5, lambda p: _list_len(p, "items")),
        ],
        "supplier_ar_local": [
            ("invoice_number", "numero facture 36584", lambda p: _contains(p.get("invoice_number"), "36584"), lambda p: p.get("invoice_number")),
            ("seller.name", "vendeur Matajer", lambda p: _contains(_nested(p, "seller.name"), "Matajer"), lambda p: _nested(p, "seller.name")),
            ("seller.tax_id", "tax id vendeur 300910063800003", lambda p: _contains(_nested(p, "seller.tax_id"), "300910063800003"), lambda p: _nested(p, "seller.tax_id")),
            ("summary.total_amount", "total 17967.42", lambda p: _amount_matches(_nested(p, "summary.total_amount") or _nested(p, "summary.amount_due"), "17967.42"), lambda p: _nested(p, "summary")),
            ("items_count", "au moins 5 lignes", lambda p: _list_len(p, "items") >= 5, lambda p: _list_len(p, "items")),
        ],
    }.get(case_id, [])


def _payload_excerpt(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "reference": payload.get("reference"),
        "montant_a_payer": payload.get("montant_a_payer"),
        "date_limite_paiement": payload.get("date_limite_paiement"),
        "patient_info": payload.get("patient_info"),
        "document_metadata": payload.get("document_metadata"),
        "tests_count": _list_len(payload, "tests"),
        "store_name": payload.get("store_name"),
        "ticket_number": payload.get("ticket_number"),
        "total": payload.get("total"),
        "items_count": _list_len(payload, "items"),
        "invoice_number": payload.get("invoice_number"),
        "seller": payload.get("seller"),
        "summary": payload.get("summary"),
        "local_pipeline": payload.get("local_pipeline"),
    }


def _gemini_configured() -> bool:
    return bool(os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"))


def _run_child(case_id: str, output_root: Path) -> dict[str, Any]:
    from backend.app.core import process_single_document, quality_score
    from src.config import load_config
    from src.services.document_router import detect_document_type

    case = CASES[case_id]
    path = PROJECT_ROOT / case["path"]
    case_output_dir = output_root / "cases"
    case_output_dir.mkdir(parents=True, exist_ok=True)
    case_output = case_output_dir / f"{case_id}.json"

    started = time.perf_counter()
    if case.get("kind") == "detect":
        try:
            detected = detect_document_type(path)
            result = {
                "id": case_id,
                "family": case["family"],
                "kind": "detect",
                "path": str(path),
                "status": "ok",
                "detectedType": detected,
                "elapsed_sec": round(time.perf_counter() - started, 2),
            }
        except Exception as exc:
            result = {
                "id": case_id,
                "family": case["family"],
                "kind": "detect",
                "path": str(path),
                "status": "exception",
                "error": f"{type(exc).__name__}: {exc}",
                "elapsed_sec": round(time.perf_counter() - started, 2),
            }
        case_output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        return result

    cfg0 = load_config(PROJECT_ROOT)
    cfg = replace(
        cfg0,
        extraction_history_dir=output_root / "history" / "extractions",
        extraction_history_db_path=output_root / "history" / "extractions.db",
    )
    try:
        result = process_single_document(
            cfg,
            filename=path.name,
            file_bytes=path.read_bytes(),
            origin="upload",
            mode=case["mode"],
            extraction_method=case["method"],
            gemini_api_key=None,
            gemini_model=None,
            ollama_host=os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434"),
            local_model=os.getenv("OLLAMA_MODEL", "qwen2.5:7b-instruct"),
            retries=1,
            retry_delay=1.0,
        )
    except Exception as exc:
        result = {
            "filename": path.name,
            "status": "exception",
            "error": f"{type(exc).__name__}: {exc}",
            "payload": {},
        }

    payload = result.get("payload") if isinstance(result.get("payload"), dict) else {}
    quality = None
    if isinstance(payload, dict):
        try:
            quality = quality_score(payload, str(result.get("kind") or ""))
        except Exception:
            quality = None

    out = {
        "id": case_id,
        "family": case["family"],
        "method": case["method"],
        "mode": case["mode"],
        "path": str(path),
        "elapsed_sec": round(time.perf_counter() - started, 2),
        "status": result.get("status"),
        "kind": result.get("kind"),
        "detectedType": result.get("detectedType"),
        "qualityScore": quality,
        "error": result.get("error"),
        "summary": result.get("summary"),
        "warnings": result.get("warnings"),
        "payload": payload,
        "payload_excerpt": _payload_excerpt(payload),
    }
    case_output.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


def _evaluate(case_id: str, result: dict[str, Any], *, gemini_configured: bool) -> dict[str, Any]:
    case = CASES[case_id]
    expected_error = bool(case.get("expected_error"))

    failures: list[dict[str, Any]] = []
    if case.get("kind") == "detect":
        expected = case.get("expected_detected")
        if result.get("detectedType") != expected:
            failures.append(
                {
                    "field": "detectedType",
                    "expected": expected,
                    "actual": result.get("detectedType") or result.get("error"),
                }
            )
    elif not expected_error:
        payload = result.get("payload") if isinstance(result.get("payload"), dict) else {}
        for field, label, predicate, actual_getter in _checks_for(case_id):
            try:
                ok = bool(predicate(payload))
                actual = actual_getter(payload)
            except Exception as exc:
                ok = False
                actual = f"{type(exc).__name__}: {exc}"
            if not ok:
                failures.append({"field": field, "expected": label, "actual": actual})

    status = result.get("status")
    if expected_error:
        passed = status == "error" and bool(result.get("error"))
    else:
        passed = status == "ok" and not failures

    out = dict(result)
    out.pop("payload", None)
    out["expected_error"] = expected_error
    out["passed"] = passed
    out["failures"] = failures
    return out


def run_all(selected_cases: list[str] | None = None) -> dict[str, Any]:
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_root = DEFAULT_OUTPUT_ROOT / run_id
    output_root.mkdir(parents=True, exist_ok=True)
    env = _default_env()
    case_ids = selected_cases or list(CASES)
    gemini_configured = _gemini_configured()
    results: list[dict[str, Any]] = []

    for case_id in case_ids:
        case = CASES[case_id]
        timeout = int(case.get("timeout") or 120)
        child_cmd = [
            str(PYTHON_EXE),
            str(Path(__file__).resolve()),
            "--case",
            case_id,
            "--output-root",
            str(output_root),
        ]
        started = time.perf_counter()
        try:
            completed = subprocess.run(
                child_cmd,
                cwd=str(PROJECT_ROOT),
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=timeout,
            )
            case_file = output_root / "cases" / f"{case_id}.json"
            if case_file.is_file():
                raw_result = json.loads(case_file.read_text(encoding="utf-8"))
            else:
                raw_result = {
                    "id": case_id,
                    "family": case.get("family"),
                    "method": case.get("method"),
                    "mode": case.get("mode"),
                    "status": "exception",
                    "error": f"Le sous-test s'est termine avec code {completed.returncode}, sans fichier resultat.",
                    "elapsed_sec": round(time.perf_counter() - started, 2),
                }
        except subprocess.TimeoutExpired:
            raw_result = {
                "id": case_id,
                "family": case.get("family"),
                "method": case.get("method"),
                "mode": case.get("mode"),
                "status": "timeout",
                "error": f"Timeout apres {timeout}s",
                "elapsed_sec": round(time.perf_counter() - started, 2),
            }
        results.append(_evaluate(case_id, raw_result, gemini_configured=gemini_configured))

    summary = {
        "run_id": run_id,
        "output_root": str(output_root),
        "gemini_configured": gemini_configured,
        "total": len(results),
        "passed": sum(1 for item in results if item.get("passed")),
        "failed": sum(1 for item in results if not item.get("passed")),
        "results": results,
    }
    (output_root / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Validation QA des methodes d'extraction DocIA.")
    parser.add_argument("--case", choices=sorted(CASES))
    parser.add_argument("--cases", nargs="*", choices=sorted(CASES))
    parser.add_argument("--output-root", type=Path)
    args = parser.parse_args()

    if args.case:
        root = args.output_root or (DEFAULT_OUTPUT_ROOT / datetime.now().strftime("%Y%m%d_%H%M%S"))
        root.mkdir(parents=True, exist_ok=True)
        result = _run_child(args.case, root)
        print(json.dumps({"case": args.case, "status": result.get("status")}, ensure_ascii=False))
        return

    summary = run_all(args.cases)
    print(f"QA extraction: {summary['passed']}/{summary['total']} cas OK")
    print(summary["output_root"])
    for item in summary["results"]:
        state = "OK" if item.get("passed") else "FAIL"
        print(f"{state} {item['id']} status={item.get('status')} quality={item.get('qualityScore')} error={item.get('error') or ''}")


if __name__ == "__main__":
    main()
