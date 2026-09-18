"""
Noms de modèles pour le SDK google-genai (Gemini API).
Les anciens IDs (ex. gemini-1.5-flash) renvoient souvent 404 sur l'API récente.
"""
from __future__ import annotations

# Modèle par défaut recommandé pour generateContent + vision
DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"

# Alias obsolètes / non disponibles sur v1beta → ID actuel
_DEPRECATED_MODEL_ALIASES: dict[str, str] = {
    "gemini-1.5-flash": "gemini-2.5-flash",
    "gemini-1.5-flash-001": "gemini-2.5-flash",
    "gemini-1.5-flash-latest": "gemini-2.5-flash",
    "gemini-1.5-flash-8b": "gemini-2.5-flash",
    "gemini-1.5-pro": "gemini-2.5-pro",
    "gemini-1.5-pro-latest": "gemini-2.5-pro",
    "gemini-1.5-pro-001": "gemini-2.5-pro",
    "gemini-pro": "gemini-2.5-flash",
    "gemini-pro-vision": "gemini-2.5-flash",
}


def normalize_gemini_model_id(name: str | None) -> str:
    if not name or not str(name).strip():
        return DEFAULT_GEMINI_MODEL
    raw = str(name).strip()
    return _DEPRECATED_MODEL_ALIASES.get(raw.lower(), raw)


def gemini_model_fallback_chain(user_model: str | None) -> list[str]:
    """Liste unique : modèle demandé (normalisé), puis secours Flash uniquement (pas de Pro : quota / coût)."""
    primary = normalize_gemini_model_id(user_model)
    fallbacks = [
        primary,
        "gemini-2.5-flash",
        "gemini-2.0-flash",
    ]
    seen: set[str] = set()
    out: list[str] = []
    for m in fallbacks:
        if m and m not in seen:
            seen.add(m)
            out.append(m)
    return out


def is_model_not_found_error(exc: BaseException) -> bool:
    msg = str(exc).lower()
    return "404" in msg or "not found" in msg or "not_found" in msg
