import sys
import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))

from src.extraction.steg_invoice_extractor import extract_batch


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Extraction STEG (reference + montant).")
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Nombre max d'images a traiter (0 = toutes).",
    )
    parser.add_argument(
        "--no-debug",
        action="store_true",
        help="Desactive l'ecriture des images debug pour accelerer.",
    )
    return parser.parse_args()


def _progress(idx: int, total: int, file_name: str) -> None:
    print(f"[{idx}/{total}] Traitement: {file_name}", flush=True)


def main() -> None:
    args = _parse_args()
    root = ROOT
    input_dir = root / "data" / "raw" / "electricite"
    output_json = root / "outputs" / "extraction" / "steg_extraction_results.json"
    output_csv = root / "outputs" / "extraction" / "steg_extraction_results.csv"
    debug_dir = None if args.no_debug else (root / "outputs" / "extraction" / "debug_rois")

    print("[START] Extraction STEG...", flush=True)
    print(f"[INFO] Dossier input: {input_dir}", flush=True)
    if args.limit and args.limit > 0:
        print(f"[INFO] Mode test rapide: limit={args.limit}", flush=True)

    results = extract_batch(
        input_dir=input_dir,
        output_json=output_json,
        output_csv=output_csv,
        debug_dir=debug_dir,
        limit=args.limit if args.limit > 0 else None,
        progress_callback=_progress,
    )

    print(f"[DONE] {len(results)} factures traitees.")
    for r in results:
        line = (
            f"- {r.file_name}: reference={r.reference}, montant={r.montant_a_payer}, periode={r.periode_du}->{r.periode_au}, "
            f"date_limite={r.date_limite_paiement}, confidence={r.confidence_note}"
        )
        try:
            print(line)
        except UnicodeEncodeError:
            print(line.encode("ascii", errors="replace").decode("ascii"))


if __name__ == "__main__":
    main()
