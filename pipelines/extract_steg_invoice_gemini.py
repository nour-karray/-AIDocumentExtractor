"""
Extraction des champs principaux d'une facture STEG (électricité / gaz) via Gemini Vision.
Complète l'OCR local lorsque les montants ou dates sont mal lus.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from google.genai import types

from src.gemini_vision import extract_first_json_object, generate_vision_json, guess_image_mime_type
from src.services.gemini_payload_normalize import normalize_steg_gemini_core

PROMPT = """
Tu es un extracteur expert pour les factures de la STEG (Société Tunisienne de l'Électricité et du Gaz), en français et/ou arabe.

Retourne UNIQUEMENT un JSON valide (sans markdown, sans texte hors JSON) avec exactement cette structure:
{
  "reference": string | null,
  "montant_a_payer": string | null,
  "date_limite_paiement": string | null,
  "periode_du": string | null,
  "periode_au": string | null,
  "coupon_reference_raw": string | null,
  "coupon_montant": string | null,
  "confidence_note": string | null
}

Règles strictes:
- "reference" : référence client au format affiché (souvent 5 chiffres + espace + 3 + espace + 1), ex. "74726 880 0". Ne pas inventer.
- "montant_a_payer" : le montant TOTAL à payer (TND), incluant arrérés si c'est le montant global exigé (souvent libellé « Montant à payer », « (19) », ou équivalent arabe). Format comme sur la facture, ex. "645,000" ou "645.000".
- "date_limite_paiement" : date limite de paiement (« Prière de payer avant le » / الرجاء الدفع قبل), en ISO YYYY-MM-DD si tu peux l'inférer sans ambiguïté, sinon tel qu'affiché (ex. 2024.08.28).
- "periode_du" et "periode_au" : période de facturation / consommation (Du … Au …), en ISO si possible.
- "coupon_reference_raw" : référence longue du bulletin CCP en bas (souvent commence par 000006…) OU la référence courte du coupon si visible ; null sinon.
- "coupon_montant" : montant répété sur le coupon de versement en bas si distinct et lisible ; sinon null.
- "confidence_note" : court texte "high" / "medium" / "low" selon ta certitude globale.
- ignorer le bruit décoratif ; ne pas inventer de chiffres ou de dates.
- si un champ est absent ou illisible : null.
""".strip()


def _ensure_steg_schema(data: dict[str, Any]) -> dict[str, Any]:
    return {
        "reference": data.get("reference"),
        "montant_a_payer": data.get("montant_a_payer"),
        "date_limite_paiement": data.get("date_limite_paiement"),
        "periode_du": data.get("periode_du"),
        "periode_au": data.get("periode_au"),
        "coupon_reference_raw": data.get("coupon_reference_raw"),
        "coupon_montant": data.get("coupon_montant"),
        "confidence_note": data.get("confidence_note"),
        "extraction_source": "gemini",
    }


def extract_steg_invoice(
    image_path: str | Path,
    *,
    api_key: str | None = None,
    model: str | None = None,
    retries: int = 3,
    retry_delay_sec: float = 2.0,
) -> dict[str, Any]:
    """
    Extrait les champs STEG depuis une image locale via Gemini.
    Utilise GEMINI_API_KEY dans l'environnement.
    """
    path = Path(image_path)
    if not path.exists():
        raise FileNotFoundError(f"Image introuvable: {path}")
    if not path.is_file():
        raise ValueError(f"Chemin invalide (pas un fichier): {path}")
    if path.suffix.lower() == ".pdf":
        raise ValueError("Utilisez une image (JPG, PNG, …), pas un PDF.")

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
    base = _ensure_steg_schema(parsed)
    return normalize_steg_gemini_core(base)


def _empty_error_payload(msg: str) -> dict[str, Any]:
    return {
        "error": msg,
        "reference": None,
        "montant_a_payer": None,
        "date_limite_paiement": None,
        "periode_du": None,
        "periode_au": None,
        "coupon_reference_raw": None,
        "coupon_montant": None,
        "confidence_note": None,
        "extraction_source": None,
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extraction facture STEG via Gemini (image locale)."
    )
    parser.add_argument("image_path", type=Path, help="Chemin vers l'image de la facture.")
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Fichier JSON de sortie (défaut: <stem>_steg_gemini.json).",
    )
    parser.add_argument("--model", type=str, default=None, help="Modèle Gemini.")
    parser.add_argument("--retries", type=int, default=3, help="Tentatives par modèle.")
    parser.add_argument(
        "--retry-delay",
        type=float,
        default=2.0,
        help="Délai initial (s) entre tentatives.",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    try:
        result = extract_steg_invoice(
            args.image_path,
            model=args.model,
            retries=args.retries,
            retry_delay_sec=args.retry_delay,
        )
    except Exception as exc:
        print(json.dumps(_empty_error_payload(str(exc)), ensure_ascii=False, indent=2))
        raise SystemExit(1) from exc

    out = (
        args.output
        if args.output is not None
        else args.image_path.with_name(f"{args.image_path.stem}_steg_gemini.json")
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"\nJSON sauvegardé: {out}")


if __name__ == "__main__":
    main()
