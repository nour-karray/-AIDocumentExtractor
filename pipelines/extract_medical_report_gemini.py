from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any, Dict, Optional

from google.genai import types

from src.gemini_vision import extract_first_json_object, generate_vision_json, guess_image_mime_type
from src.services.gemini_payload_normalize import normalize_medical_gemini_page


PROMPT = """
Tu es un extracteur d'informations médicales.
Retourne UNIQUEMENT un JSON valide (sans markdown, sans texte supplémentaire) avec exactement cette structure:
{
  "patient_name": string | null,
  "doctor_name": string | null,
  "date": string | null,
  "analyses": [
    {
      "test_name": string | null,
      "value": string | null,
      "unit": string | null
    }
  ]
}

Règles strictes:
- ignorer logos, adresses, signatures, décorations, tampons et texte non utile
- extraire le nom du patient
- extraire le nom du médecin
- extraire la date principale du document
- extraire TOUTES les analyses détectées, sans limitation arbitraire
- chaque analyse = un objet distinct dans "analyses"
- ne jamais inventer une valeur
- si absent/illisible -> null
- conserver le nom original exact de l'analyse (tel qu'écrit sur le document)
- si la valeur est textuelle (ex: "Clair"), la mettre dans "value"
- séparer valeur et unité si possible
- chaque objet dans "analyses" ne contient que test_name, value, unit (aucun autre champ)
- si aucune analyse lisible, retourner "analyses": []
""".strip()


def _ensure_schema(data: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "patient_name": data.get("patient_name"),
        "doctor_name": data.get("doctor_name"),
        "date": data.get("date"),
        "analyses": [],
    }
    analyses = data.get("analyses")
    if not isinstance(analyses, list):
        analyses = []

    for row in analyses:
        if not isinstance(row, dict):
            continue
        out["analyses"].append(
            {
                "test_name": row.get("test_name"),
                "value": row.get("value"),
                "unit": row.get("unit"),
            }
        )
    return out


def extract_medical_report(
    image_path: str | Path,
    *,
    api_key: str | None = None,
    model: Optional[str] = None,
    retries: int = 3,
    retry_delay_sec: float = 2.0,
) -> Dict[str, Any]:
    """
    Extrait les informations importantes d'un document d'analyse médicale depuis une image.
    Utilise GEMINI_API_KEY depuis les variables d'environnement.
    """
    path = Path(image_path)
    if not path.exists():
        raise FileNotFoundError(f"Image introuvable: {path}")
    if not path.is_file():
        raise ValueError(f"Chemin invalide (pas un fichier): {path}")

    api_key = (api_key or os.getenv("GEMINI_API_KEY") or "").strip()
    if not api_key:
        raise EnvironmentError(
            "GEMINI_API_KEY introuvable. Définissez la variable d'environnement."
        )

    image_bytes = path.read_bytes()
    contents = [
        types.Part.from_text(text=PROMPT),
        types.Part.from_bytes(data=image_bytes, mime_type=guess_image_mime_type(path)),
    ]
    json_text = extract_first_json_object(
        generate_vision_json(
            api_key=api_key,
            contents=contents,
            model_preference=model or os.getenv("GEMINI_MODEL"),
            retries=retries,
            retry_delay_sec=retry_delay_sec,
        )
    )
    parsed = json.loads(json_text)
    if not isinstance(parsed, dict):
        raise ValueError("La réponse JSON n'est pas un objet.")
    coerced = _ensure_schema(parsed)
    return normalize_medical_gemini_page(coerced)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extraction générique d'analyses médicales via Gemini (image locale)."
    )
    parser.add_argument("image_path", type=Path, help="Chemin vers l'image locale.")
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Fichier JSON de sortie (défaut: <image_stem>_gemini.json).",
    )
    parser.add_argument(
        "--model",
        type=str,
        default=None,
        help="Modèle Gemini (défaut: GEMINI_MODEL ou gemini-2.5-flash).",
    )
    parser.add_argument(
        "--retries",
        type=int,
        default=3,
        help="Nombre de tentatives par modèle en cas d'erreur temporaire (503/429).",
    )
    parser.add_argument(
        "--retry-delay",
        type=float,
        default=2.0,
        help="Délai initial (secondes) entre tentatives, avec backoff linéaire.",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    try:
        result = extract_medical_report(
            args.image_path,
            model=args.model,
            retries=args.retries,
            retry_delay_sec=args.retry_delay,
        )
    except Exception as exc:
        error_payload = {
            "error": str(exc),
            "patient_name": None,
            "doctor_name": None,
            "date": None,
            "analyses": [],
        }
        print(json.dumps(error_payload, ensure_ascii=False, indent=2))
        raise SystemExit(1) from exc

    output_path = (
        args.output
        if args.output is not None
        else args.image_path.with_name(f"{args.image_path.stem}_gemini.json")
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"\nJSON sauvegardé: {output_path}")


if __name__ == "__main__":
    main()
