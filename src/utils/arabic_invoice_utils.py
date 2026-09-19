"""Normalisation de texte et chiffres pour factures multilingues (arabe / français / anglais)."""

from __future__ import annotations

import unicodedata

# Chiffres arabo-indiens (٠١٢...) et persans (۰۱۲...) → ASCII
_ARABIC_INDIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")
_PERSIAN_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789")

_TATWEEL = "\u0640"


def normalize_numeric_digits(text: str) -> str:
    """Convertit les chiffres arabes orientaux / persans en chiffres latins."""
    if not text:
        return ""
    return text.translate(_ARABIC_INDIC_DIGITS).translate(_PERSIAN_DIGITS)


def clean_arabic_ocr_text(text: str) -> str:
    """NFC, suppression tatwīl, espaces normalisés (OCR arabe)."""
    if not text:
        return ""
    s = unicodedata.normalize("NFC", text)
    s = s.replace(_TATWEEL, "")
    lines = []
    for line in s.splitlines():
        line = " ".join(line.split())
        if line:
            lines.append(line)
    return "\n".join(lines)


def rtl_script_ratio(text: str) -> float:
    """
    Part approximative de caractères « RTL dominants » (arabe principalement)
    parmi les lettres arabes + latines (ignore chiffres et ponctuation).
    """
    if not text:
        return 0.0
    arabic = 0
    latin = 0
    for c in text:
        if "\u0600" <= c <= "\u06FF" or "\u0750" <= c <= "\u077F" or "\u08A0" <= c <= "\u08FF":
            arabic += 1
        elif "a" <= c.lower() <= "z":
            latin += 1
    total = arabic + latin
    if total == 0:
        return 0.0
    return arabic / total
