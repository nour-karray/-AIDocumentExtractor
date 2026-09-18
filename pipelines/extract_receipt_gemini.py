"""
Extraction générique de tickets de caisse (Zara, Carrefour, Costco, etc.) via Gemini.
Ne codifie aucun nom de magasin : le modèle déduit la structure depuis l'image.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from google.genai import types

from src.gemini_vision import extract_first_json_object, generate_vision_json, guess_image_mime_type
from src.services.gemini_payload_normalize import normalize_receipt_gemini

PROMPT = """
Tu es un extracteur d'informations pour tickets de caisse (receipts).
Le ticket peut provenir de n'importe quel magasin ou format (ex. chaînes internationales, locales).
Retourne UNIQUEMENT un JSON valide (sans markdown, sans texte supplémentaire) avec exactement cette structure:
{
  "store_name": string | null,
  "date": string | null,
  "time": string | null,
  "ticket_number": string | null,
  "currency": string | null,
  "items": [
    {
      "description": string | null,
      "quantity": string | null,
      "unit_price": string | null,
      "line_total": string | null
    }
  ],
  "total": string | null,
  "payment_method": string | null
}

Règles strictes:
- ignorer slogans, publicités, QR codes, adresses si non nécessaires au ticket, téléphone, politique de retour, texte décoratif
- extraire le nom du magasin / enseigne si visible
- extraire la date et l'heure du ticket si visibles (format tel qu'affiché ou ISO si clair)
- extraire le numéro de ticket / transaction si visible
- extraire la devise si identifiable (code ou symbole tel qu'affiché)
- extraire TOUS les articles / lignes produits détectés, sans limite arbitraire
- chaque ligne article = un objet distinct dans "items"
- ne jamais inventer une valeur
- si absent ou illisible -> null
- conserver les montants et libellés tels qu'ils apparaissent sur le ticket (pas de conversion inventée)
- si aucun article lisible, retourner "items": []
""".strip()


def _ensure_receipt_schema(data: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {
        "store_name": data.get("store_name"),
        "date": data.get("date"),
        "time": data.get("time"),
        "ticket_number": data.get("ticket_number"),
        "currency": data.get("currency"),
        "items": [],
        "total": data.get("total"),
        "payment_method": data.get("payment_method"),
    }
    items = data.get("items")
    if not isinstance(items, list):
        items = []

    for row in items:
        if not isinstance(row, dict):
            continue
        out["items"].append(
            {
                "description": row.get("description"),
                "quantity": row.get("quantity"),
                "unit_price": row.get("unit_price"),
                "line_total": row.get("line_total"),
            }
        )
    return out


def extract_receipt(
    image_path: str | Path,
    *,
    api_key: str | None = None,
    model: str | None = None,
    retries: int = 3,
    retry_delay_sec: float = 2.0,
) -> dict[str, Any]:
    """
    Extrait les champs importants d'un ticket de caisse depuis une image locale.
    Utilise GEMINI_API_KEY depuis les variables d'environnement.
    """
    path = Path(image_path)
    if not path.exists():
        raise FileNotFoundError(f"Image introuvable: {path}")
    if not path.is_file():
        raise ValueError(f"Chemin invalide (pas un fichier): {path}")

    api_key = (api_key or os.getenv("GEMINI_API_KEY") or "").strip()
    if not api_key:
        raise OSError(
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
    return normalize_receipt_gemini(_ensure_receipt_schema(parsed))


def _empty_error_payload(msg: str) -> dict[str, Any]:
    return {
        "error": msg,
        "store_name": None,
        "date": None,
        "time": None,
        "ticket_number": None,
        "currency": None,
        "items": [],
        "total": None,
        "payment_method": None,
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extraction générique de ticket de caisse via Gemini (image locale)."
    )
    parser.add_argument("image_path", type=Path, help="Chemin vers l'image du ticket.")
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Fichier JSON de sortie (défaut: <image_stem>_receipt_gemini.json).",
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
        result = extract_receipt(
            args.image_path,
            model=args.model,
            retries=args.retries,
            retry_delay_sec=args.retry_delay,
        )
    except Exception as exc:
        print(json.dumps(_empty_error_payload(str(exc)), ensure_ascii=False, indent=2))
        raise SystemExit(1) from exc

    output_path = (
        args.output
        if args.output is not None
        else args.image_path.with_name(f"{args.image_path.stem}_receipt_gemini.json")
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
