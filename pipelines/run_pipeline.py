import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.extraction.medical_analysis_extractor import extract_batch_medical
from src.extraction.steg_invoice_extractor import extract_batch

RAW_DIR = ROOT / "data" / "raw"
EXTRACT_OUT_DIR = ROOT / "outputs" / "extraction"
STEG_INPUT_DIR = RAW_DIR / "electricite"
MEDICAL_INPUT_DIR = RAW_DIR / "medical"


def main() -> None:
    EXTRACT_OUT_DIR.mkdir(parents=True, exist_ok=True)

    if STEG_INPUT_DIR.is_dir():
        out_json = EXTRACT_OUT_DIR / "pipeline_steg_results.json"
        out_csv = EXTRACT_OUT_DIR / "pipeline_steg_results.csv"
        print(f"[INFO] Extraction STEG depuis {STEG_INPUT_DIR}", flush=True)
        results = extract_batch(
            input_dir=STEG_INPUT_DIR,
            output_json=out_json,
            output_csv=out_csv,
            debug_dir=None,
            limit=None,
            progress_callback=lambda i, t, n: print(f"[{i}/{t}] {n}", flush=True),
        )
        print(f"[OK] STEG: {len(results)} facture(s) -> {out_json.name}, {out_csv.name}")
        for r in results:
            line = (
                f"  - {r.file_name}: ref={r.reference}, montant={r.montant_a_payer}, "
                f"date_limite={r.date_limite_paiement}"
            )
            try:
                print(line)
            except UnicodeEncodeError:
                print(line.encode("ascii", errors="replace").decode("ascii"))
    else:
        print(f"[WARN] Dossier STEG absent: {STEG_INPUT_DIR}")

    if MEDICAL_INPUT_DIR.is_dir():
        out_json_m = EXTRACT_OUT_DIR / "pipeline_medical_results.json"
        out_csv_m = EXTRACT_OUT_DIR / "pipeline_medical_results.csv"
        print(f"[INFO] Extraction medical depuis {MEDICAL_INPUT_DIR}", flush=True)
        med_results = extract_batch_medical(
            input_dir=MEDICAL_INPUT_DIR,
            output_json=out_json_m,
            output_csv=out_csv_m,
            debug_dir=None,
            limit=None,
            progress_callback=lambda i, t, n: print(f"[med {i}/{t}] {n}", flush=True),
        )
        print(
            f"[OK] Medical: {len(med_results)} document(s) -> {out_json_m.name}, {out_csv_m.name}"
        )
        for r in med_results:
            line = (
                f"  - {r.file_name}: {len(r.resultats_analyses)} ligne(s) bilan, "
                f"ref={r.reference_dossier}, prel={r.date_prelevement}, labo={r.laboratoire}"
            )
            try:
                print(line)
            except UnicodeEncodeError:
                print(line.encode("ascii", errors="replace").decode("ascii"))
    else:
        print(f"[WARN] Dossier medical absent: {MEDICAL_INPUT_DIR}")

    print("[DONE] Pipeline termine.")


if __name__ == "__main__":
    main()
