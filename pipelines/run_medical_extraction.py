import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))

from src.extraction.medical_analysis_extractor import extract_batch_medical


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Extraction analyses medicales (reference, dates, labo, patient)."
    )
    p.add_argument(
        "--input-dir",
        type=Path,
        default=None,
        help="Dossier images (defaut: data/raw/medical).",
    )
    p.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Nombre max d'images (0 = toutes).",
    )
    p.add_argument(
        "--no-debug",
        action="store_true",
        help="Ne pas ecrire les images debug.",
    )
    return p.parse_args()


def _progress(idx: int, total: int, file_name: str) -> None:
    print(f"[{idx}/{total}] Traitement: {file_name}", flush=True)


def main() -> None:
    args = _parse_args()
    root = ROOT
    input_dir = args.input_dir or (root / "data" / "raw" / "medical")
    output_json = root / "outputs" / "extraction" / "medical_extraction_results.json"
    output_csv = root / "outputs" / "extraction" / "medical_extraction_results.csv"
    debug_dir = None if args.no_debug else (root / "outputs" / "extraction" / "debug_medical")

    print("[START] Extraction analyses medicales...", flush=True)
    print(f"[INFO] Dossier input: {input_dir}", flush=True)
    if args.limit and args.limit > 0:
        print(f"[INFO] Mode test: limit={args.limit}", flush=True)

    if not input_dir.is_dir():
        print(f"[ERREUR] Dossier introuvable: {input_dir}", flush=True)
        sys.exit(1)

    results = extract_batch_medical(
        input_dir=input_dir,
        output_json=output_json,
        output_csv=output_csv,
        debug_dir=debug_dir,
        limit=args.limit if args.limit > 0 else None,
        progress_callback=_progress,
    )

    print(f"[DONE] {len(results)} document(s).")
    for r in results:
        n_bio = len(r.resultats_analyses)
        line = (
            f"- {r.file_name}: {n_bio} ligne(s) bilan, ref={r.reference_dossier}, "
            f"prel={r.date_prelevement}, result={r.date_resultat}, labo={r.laboratoire}, "
            f"patient={r.patient_nom}, conf={r.confidence_note}"
        )
        try:
            print(line)
        except UnicodeEncodeError:
            print(line.encode("ascii", errors="replace").decode("ascii"))


if __name__ == "__main__":
    main()
