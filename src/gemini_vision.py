"""Appels Gemini Vision + JSON partagés par les pipelines d'extraction."""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

from google import genai
from google.genai import types

from src.gemini_models import gemini_model_fallback_chain, is_model_not_found_error


def format_gemini_quota_user_message(exc: BaseException) -> str:
    """Message court en français pour les erreurs 429 / quota (UI et logs)."""
    raw = str(exc)
    lower = raw.lower()
    if "free_tier" in lower or "freetier" in lower.replace("_", "") or "perdayperproject" in lower.replace(
        "_", ""
    ):
        return (
            "Quota gratuit de l’API Gemini atteint pour ce projet / ce modèle "
            "(souvent ~20 requêtes par jour en gratuit pour un modèle donné). "
            "Solutions : activer la facturation sur Google AI Studio / Google Cloud pour ce projet, "
            "attendre la réinitialisation du quota (minuit fuseau Google), ou réduire les essais pendant le développement. "
            "Documentation : https://ai.google.dev/gemini-api/docs/rate-limits"
        )
    if "429" in raw or "resource_exhausted" in lower:
        return (
            "Limite temporaire d’appels Gemini (429) : réessayez après l’indication « retry », "
            "ou vérifiez quotas et facturation. "
            "https://ai.google.dev/gemini-api/docs/rate-limits"
        )
    return raw


def guess_image_mime_type(path: Path) -> str:
    ext = path.suffix.lower()
    if ext in {".jpg", ".jpeg"}:
        return "image/jpeg"
    if ext == ".png":
        return "image/png"
    if ext in {".tif", ".tiff"}:
        return "image/tiff"
    if ext == ".webp":
        return "image/webp"
    return "image/jpeg"


def guess_document_mime_type(path: Path) -> str:
    """MIME pour pièces jointes Gemini : image ou PDF."""
    if path.suffix.lower() == ".pdf":
        return "application/pdf"
    return guess_image_mime_type(path)


def extract_first_json_object(raw: str) -> str:
    """
    Isole le premier objet JSON `{ ... }` dans la réponse (évite le markdown cassé par strip()).
    """
    raw = (raw or "").strip()
    if not raw:
        raise ValueError("Réponse Gemini vide.")
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw, re.IGNORECASE)
    if fence:
        raw = fence.group(1).strip()
    elif raw.startswith("```"):
        raw = raw[3:].lstrip()
        if raw.lower().startswith("json"):
            raw = raw[4:].lstrip()
        if raw.rstrip().endswith("```"):
            raw = raw.rstrip()[:-3].rstrip()
    if raw.startswith("\ufeff"):
        raw = raw[1:]
    start = raw.find("{")
    end = raw.rfind("}")
    if start < 0 or end < 0 or end <= start:
        raise ValueError("JSON introuvable dans la réponse Gemini.")
    return raw[start : end + 1]


def repair_json_common_issues(blob: str) -> str:
    """Corrige des erreurs fréquentes dans du pseudo-JSON renvoyé par les LLM."""
    s = blob.strip()
    prev = None
    while prev != s:
        prev = s
        s = re.sub(r",(\s*[}\]])", r"\1", s)
    return s


def loads_json_from_gemini_response(raw: str) -> Any:
    """
    Parse la réponse texte Gemini en JSON : extraction du premier objet puis corrections légères.
    """
    blob = extract_first_json_object(raw)
    variants = (blob, repair_json_common_issues(blob))
    last_exc: Exception | None = None
    for candidate in variants:
        try:
            return json.loads(candidate)
        except json.JSONDecodeError as exc:
            last_exc = exc
            continue
    raise ValueError(f"JSON Gemini invalide : {last_exc}") from last_exc


def generate_vision_json(
    *,
    api_key: str,
    contents: list[Any],
    model_preference: str | None,
    retries: int,
    retry_delay_sec: float,
    response_json_schema: dict[str, Any] | None = None,
    max_output_tokens: int | None = None,
) -> str:
    client = genai.Client(api_key=api_key)
    models = gemini_model_fallback_chain(model_preference)
    last_exc: BaseException | None = None
    response = None
    for mdl in models:
        for attempt in range(1, max(1, retries) + 1):
            try:
                cfg_kw: dict[str, Any] = {
                    "temperature": 0.0,
                    "response_mime_type": "application/json",
                }
                if response_json_schema is not None:
                    cfg_kw["response_json_schema"] = response_json_schema
                if max_output_tokens is not None:
                    cfg_kw["max_output_tokens"] = max_output_tokens
                response = client.models.generate_content(
                    model=mdl,
                    contents=contents,
                    config=types.GenerateContentConfig(**cfg_kw),
                )
                break
            except Exception as exc:
                last_exc = exc
                if is_model_not_found_error(exc):
                    break
                msg = str(exc).lower()
                is_quota = "429" in msg or "resource_exhausted" in msg
                transient = any(
                    t in msg
                    for t in ("503", "unavailable", "deadline")
                ) or is_quota
                if transient and attempt < max(1, retries):
                    time.sleep(retry_delay_sec * attempt)
                    continue
                # Quota : ne pas enchaîner sur d'autres modèles (souvent même plafond / message trompeur type 1.5-pro).
                if is_quota:
                    raise RuntimeError(format_gemini_quota_user_message(exc)) from exc
                break
        if response is not None:
            break
    if response is None:
        if last_exc is not None:
            raise last_exc
        raise RuntimeError("Échec appel Gemini sans détail.")
    return response.text or ""
