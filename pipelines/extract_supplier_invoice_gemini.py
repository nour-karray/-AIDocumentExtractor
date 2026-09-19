"""
Extraction générique de factures fournisseur (PDF ou image) via Gemini Vision.
Sortie JSON avec clés anglais ; support multilingue (FR/EN/AR) et indices OCR Tesseract.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from google.genai import types

from src.gemini_vision import (
    extract_first_json_object,
    generate_vision_json,
    guess_document_mime_type,
    loads_json_from_gemini_response,
)
from src.services.gemini_payload_normalize import normalize_supplier_invoice_gemini
from src.services.supplier_invoice_ocr import build_gemini_ocr_hint

_SUPPLIER_LINE_ITEM_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "description": {"type": "string"},
        "quantity": {"type": "string"},
        "unit": {"type": "string"},
        "unit_price": {"type": "string"},
        "net_amount": {"type": "string"},
        "tax_rate": {"type": "string"},
        "tax_amount": {"type": "string"},
        "gross_amount": {"type": "string"},
    },
}

_SUPPLIER_SELLER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "address": {"type": "string"},
        "tax_id": {"type": "string"},
        "iban": {"type": "string"},
        "email": {"type": "string"},
        "phone": {"type": "string"},
    },
}

_SUPPLIER_CLIENT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "address": {"type": "string"},
        "tax_id": {"type": "string"},
        "email": {"type": "string"},
        "phone": {"type": "string"},
    },
}

_SUPPLIER_SUMMARY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "subtotal": {"type": "string"},
        "tax_total": {"type": "string"},
        "discount": {"type": "string"},
        "shipping": {"type": "string"},
        "total_amount": {"type": "string"},
        "amount_due": {"type": "string"},
    },
}

# Schéma Gemini (structured output) pour réduire les réponses JSON syntaxiquement invalides.
SUPPLIER_INVOICE_RESPONSE_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "document_type": {"type": "string"},
        "invoice_number": {"type": "string"},
        "invoice_date": {"type": "string"},
        "due_date": {"type": "string"},
        "currency": {"type": "string"},
        "seller": _SUPPLIER_SELLER_SCHEMA,
        "client": _SUPPLIER_CLIENT_SCHEMA,
        "items": {"type": "array", "items": _SUPPLIER_LINE_ITEM_SCHEMA},
        "summary": _SUPPLIER_SUMMARY_SCHEMA,
        "confidence": {"type": "string"},
        "missing_fields": {"type": "array", "items": {"type": "string"}},
        "raw_notes": {"type": "string"},
    },
}

_REPAIR_JSON_PROMPT = """
Tu corriges un texte qui devait être un objet JSON mais peut être invalide.
Réponds avec UN SEUL objet JSON valide (RFC 8259) : guillemets doubles pour les clés et les chaînes,
pas de virgule finale avant ] ou }, pas de commentaires ni markdown.
Échappe correctement les guillemets et les antislashs à l'intérieur des chaînes.
Conserve la structure et le sens des champs facture fournisseur (seller, client, items, summary, etc.).
""".strip()


PROMPT = """
Tu extrais une facture fournisseur au format B2B/B2C (vente, achat, services, international).
Le document peut être en français, anglais, arabe, bilingue ou mixte ; la mise en page et les logos varient.

Tu reçois l'image ou le PDF ET un bloc texte OCR optionnel (bruit possible). Utilise surtout la vision ;
emploie l'OCR uniquement comme aide si une zone est floue.

Retourne UNIQUEMENT un JSON valide (sans markdown, sans texte hors JSON) avec EXACTEMENT cette structure :
{
  "document_type": "supplier_invoice",
  "invoice_number": "",
  "invoice_date": "",
  "due_date": "",
  "currency": "",
  "seller": {
    "name": "",
    "address": "",
    "tax_id": "",
    "iban": "",
    "email": "",
    "phone": ""
  },
  "client": {
    "name": "",
    "address": "",
    "tax_id": "",
    "email": "",
    "phone": ""
  },
  "items": [
    {
      "description": "",
      "quantity": "",
      "unit": "",
      "unit_price": "",
      "net_amount": "",
      "tax_rate": "",
      "tax_amount": "",
      "gross_amount": ""
    }
  ],
  "summary": {
    "subtotal": "",
    "tax_total": "",
    "discount": "",
    "shipping": "",
    "total_amount": "",
    "amount_due": ""
  },
  "confidence": "",
  "missing_fields": [],
  "raw_notes": ""
}

Règles strictes :
- Syntaxe JSON stricte : uniquement des guillemets doubles " pour les clés et les chaînes ; pas de virgule après le dernier champ d'un objet ou tableau.
- Ne jamais inventer une valeur absente ou illisible : utilise une chaîne vide "".
- Les libellés peuvent être en arabe (RTL), français ou anglais : mappe vers les champs équivalents (vendeur/البائع/Seller, client/العميل/Buyer, TVA/VAT/الضريبة, etc.).
- Toutes les clés JSON ci-dessus restent en anglais ; les valeurs extraites reflètent le document (noms, libellés produits peuvent rester dans la langue d'origine).
- Pour les montants et identifiants numériques dans les valeurs : utilise des chiffres latins 0-9 (convertis les chiffres arabes ٣٤٥ si présents sur la facture).
- "items" : une entrée par ligne de produit/service lisible ; si aucune ligne claire, tableau vide [].
- "missing_fields" : liste des chemins des champs importants absents (ex: "invoice_number", "summary.total_amount").
- "confidence" : courte indication subjective ("high", "medium", "low") ou "" si tu préfères ne pas te prononcer.
- "raw_notes" : note très courte sur ambiguïtés visibles (sin "").
- Pas de champs supplémentaires en dehors de ce schéma.
""".strip()


def _generate_supplier_raw_json(
    *,
    api_key: str,
    contents: list[Any],
    model: str | None,
    retries: int,
    retry_delay_sec: float,
) -> str:
    """
    Appel Gemini avec schéma JSON si supporté ; sinon nouvel essai sans schéma (erreurs d'API liées au schéma).
    """
    try:
        return generate_vision_json(
            api_key=api_key,
            contents=contents,
            model_preference=model or os.getenv("GEMINI_MODEL"),
            retries=retries,
            retry_delay_sec=retry_delay_sec,
            response_json_schema=SUPPLIER_INVOICE_RESPONSE_JSON_SCHEMA,
            max_output_tokens=8192,
        )
    except Exception as exc:
        msg = str(exc).lower()
        if any(
            x in msg
            for x in (
                "schema",
                "json_schema",
                "response_schema",
                "invalid_argument",
                "unsupported",
                "unknown name",
            )
        ):
            return generate_vision_json(
                api_key=api_key,
                contents=contents,
                model_preference=model or os.getenv("GEMINI_MODEL"),
                retries=retries,
                retry_delay_sec=retry_delay_sec,
                response_json_schema=None,
                max_output_tokens=8192,
            )
        raise


def _repair_json_via_gemini_text(
    *,
    api_key: str,
    broken_response: str,
    model: str | None,
    retries: int,
    retry_delay_sec: float,
) -> str:
    """Deuxième passe texte-only pour récupérer un JSON parseable."""
    try:
        snippet = extract_first_json_object(broken_response)
    except ValueError:
        snippet = broken_response[:28000]
    fix_contents = [
        types.Part.from_text(text=_REPAIR_JSON_PROMPT + "\n\n---\n\n" + snippet),
    ]
    try:
        return generate_vision_json(
            api_key=api_key,
            contents=fix_contents,
            model_preference=model or os.getenv("GEMINI_MODEL"),
            retries=max(1, min(retries, 2)),
            retry_delay_sec=retry_delay_sec,
            response_json_schema=SUPPLIER_INVOICE_RESPONSE_JSON_SCHEMA,
            max_output_tokens=8192,
        )
    except Exception:
        return generate_vision_json(
            api_key=api_key,
            contents=fix_contents,
            model_preference=model or os.getenv("GEMINI_MODEL"),
            retries=max(1, min(retries, 2)),
            retry_delay_sec=retry_delay_sec,
            response_json_schema=None,
            max_output_tokens=8192,
        )


def extract_supplier_invoice(
    file_path: str | Path,
    *,
    gemini_api_key: str | None = None,
    model: str | None = None,
    retries: int = 3,
    retry_delay_sec: float = 2.0,
    include_ocr_hint: bool = True,
) -> dict[str, Any]:
    """
    Extraction facture fournisseur depuis fichier local (image ou PDF).
    Utilise GEMINI_API_KEY ou GOOGLE_API_KEY.
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Fichier introuvable: {path}")
    if not path.is_file():
        raise ValueError(f"Chemin invalide (pas un fichier): {path}")

    resolved_key = (
        (gemini_api_key.strip() if isinstance(gemini_api_key, str) else None)
        or os.getenv("GEMINI_API_KEY")
        or os.getenv("GOOGLE_API_KEY")
    )
    if not resolved_key:
        raise OSError(
            "GEMINI_API_KEY (ou GOOGLE_API_KEY) introuvable pour l'extraction facture fournisseur."
        )

    ocr_meta: dict[str, Any] = {}
    prompt_text = PROMPT
    if include_ocr_hint:
        hint, ocr_meta = build_gemini_ocr_hint(path)
        if hint.strip():
            prompt_text = (
                PROMPT
                + "\n\n--- OCR hint (may be noisy; digits normalized) ---\n"
                + hint[:7000]
            )

    file_bytes = path.read_bytes()
    mime = guess_document_mime_type(path)
    contents = [
        types.Part.from_text(text=prompt_text),
        types.Part.from_bytes(data=file_bytes, mime_type=mime),
    ]
    raw_text = _generate_supplier_raw_json(
        api_key=resolved_key,
        contents=contents,
        model=model,
        retries=retries,
        retry_delay_sec=retry_delay_sec,
    )
    try:
        parsed = loads_json_from_gemini_response(raw_text)
    except ValueError:
        repaired = _repair_json_via_gemini_text(
            api_key=resolved_key,
            broken_response=raw_text,
            model=model,
            retries=retries,
            retry_delay_sec=retry_delay_sec,
        )
        parsed = loads_json_from_gemini_response(repaired)
    if not isinstance(parsed, dict):
        raise ValueError("La réponse JSON n'est pas un objet.")
    return normalize_supplier_invoice_gemini(parsed, ocr_meta=ocr_meta)


def _empty_error_payload(msg: str) -> dict[str, Any]:
    return normalize_supplier_invoice_gemini(
        {"document_type": "supplier_invoice", "raw_notes": msg, "missing_fields": ["extraction_failed"]},
        ocr_meta={},
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extraction facture fournisseur générique via Gemini (image ou PDF)."
    )
    parser.add_argument("file_path", type=Path, help="Chemin vers l'image ou le PDF.")
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Fichier JSON de sortie (défaut: <stem>_supplier_invoice_gemini.json).",
    )
    parser.add_argument("--model", type=str, default=None, help="Modèle Gemini.")
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--retry-delay", type=float, default=2.0)
    parser.add_argument(
        "--no-ocr-hint",
        action="store_true",
        help="Ne pas joindre le texte OCR Tesseract au prompt.",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    try:
        result = extract_supplier_invoice(
            args.file_path,
            model=args.model,
            retries=args.retries,
            retry_delay_sec=args.retry_delay,
            include_ocr_hint=not args.no_ocr_hint,
        )
    except Exception as exc:
        print(json.dumps(_empty_error_payload(str(exc)), ensure_ascii=False, indent=2))
        raise SystemExit(1) from exc

    output_path = (
        args.output
        if args.output is not None
        else args.file_path.with_name(f"{args.file_path.stem}_supplier_invoice_gemini.json")
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"\nJSON sauvegardé: {output_path}")


if __name__ == "__main__":
    main()
