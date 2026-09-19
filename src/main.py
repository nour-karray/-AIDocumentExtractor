from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.config import load_config
from src.services.medical_pipeline import process_medical_file
from src.utils.logger import setup_logger


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Extraction medicale (image/PDF) -> JSON structure.")
    parser.add_argument("--input", type=Path, required=True, help="Chemin du document medical.")
    parser.add_argument("--output", type=Path, default=None, help="Fichier JSON de sortie.")
    parser.add_argument(
        "--gemini",
        action="store_true",
        help="Utiliser l'API Google Gemini (cle GEMINI_API_KEY ou GOOGLE_API_KEY).",
    )
    parser.add_argument(
        "--gemini-model",
        type=str,
        default=None,
        help="Ex: gemini-2.5-flash (defaut: config / env GEMINI_MODEL).",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    cfg = load_config()
    logger = setup_logger(level=cfg.log_level)

    if not args.input.exists():
        raise FileNotFoundError(f"Document introuvable: {args.input}")

    logger.info("Traitement du document: %s", args.input)
    result = process_medical_file(
        args.input,
        use_gemini=args.gemini,
        gemini_model=args.gemini_model,
    )

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(result.model_dump_json(indent=2, ensure_ascii=False), encoding="utf-8")
        logger.info("JSON ecrit: %s", args.output)
    else:
        print(json.dumps(result.model_dump(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

