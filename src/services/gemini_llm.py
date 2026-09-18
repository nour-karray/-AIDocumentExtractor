"""
Compréhension de documents médicaux via Google Gemini (texte + image).
Sortie alignée sur MedicalDocumentResult (JSON structuré).
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from google.genai import types

from src.gemini_vision import generate_vision_json, guess_image_mime_type
from src.models.schemas import (
    DocumentMetadata,
    LabInfo,
    LabTest,
    MedicalDocumentResult,
    PatientInfo,
    ProcessingWarning,
    ReferenceRange,
)

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """Tu es un assistant spécialisé dans l'extraction de données à partir de comptes rendus
d'analyses médicales (laboratoire) en français, parfois avec de l'arabe sur le document.

Tâche : à partir du texte OCR et/ou de l'image du document, extrais UNIQUEMENT des informations présentes
ou clairement déductibles. Ne invente rien.

Réponds par UN SEUL objet JSON (pas de markdown, pas de texte avant/après) avec cette structure exacte :
{
  "document_type": "medical_lab_report",
  "lab_name": string ou null,
  "doctor_name": string ou null,
  "patient_name": string ou null,
  "patient_id": string ou null,
  "date_of_birth": string ou null,
  "sex": string ou null,
  "dossier_number": string ou null,
  "exam_number": string ou null,
  "sample_date": string ou null,
  "report_date": string ou null,
  "page_number": string ou null,
  "tests": [
    {
      "raw_test_name": string,
      "value": number ou null,
      "value_text": string ou null,
      "unit": string ou null,
      "reference_range_text": string ou null,
      "status": "low" | "normal" | "high" | "unknown"
    }
  ]
}

Règles :
- Chaque élément de tests correspond à une ligne d'analyse (glycémie, TSH, hémoglobine, etc.).
- Si la valeur est un nombre, mets-la dans "value" (nombre JSON, point décimal).
- Si la valeur n'est pas un nombre (ex. "négatif", "<5"), mets null dans "value" et le texte dans "value_text".
- "reference_range_text" : texte brut des valeurs normales si visible (ex. "0.70 à 1.10").
- "status" : compare valeur numérique à l'intervalle si tu peux le parser ; sinon "unknown".
"""


def _parse_json_from_response(text: str) -> dict[str, Any]:
    text = text.strip()
    m = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.DOTALL)
    if m:
        return json.loads(m.group(1))
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        return json.loads(text[start : end + 1])
    raise ValueError("Aucun JSON valide dans la réponse Gemini")


def _to_float_safe(v: Any) -> float | None:
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace(",", ".").replace(" ", "")
    if not s or s in {"-", "—"}:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _gemini_dict_to_result(data: dict[str, Any], source_file: str) -> MedicalDocumentResult:
    tests_out: list[LabTest] = []
    for t in data.get("tests") or []:
        if not isinstance(t, dict):
            continue
        name = (t.get("raw_test_name") or t.get("name") or "").strip()
        if not name:
            continue
        val = _to_float_safe(t.get("value"))
        vtxt = t.get("value_text")
        if vtxt is not None:
            vtxt = str(vtxt).strip() or None
        ref_txt = t.get("reference_range_text")
        if ref_txt:
            ref_txt = str(ref_txt).strip()
        rr = ReferenceRange(raw_text=ref_txt) if ref_txt else None
        st = t.get("status") or "unknown"
        if st not in ("low", "normal", "high", "unknown"):
            st = "unknown"
        tests_out.append(
            LabTest(
                raw_test_name=name,
                normalized_name="unknown",
                category="other",
                value_text=vtxt,
                value=val,
                unit=(t.get("unit") and str(t.get("unit")).strip()) or None,
                reference_range=rr,
                status=st,
                raw_line=name,
                confidence=0.85,
            )
        )

    return MedicalDocumentResult(
        document_type=str(data.get("document_type") or "medical_lab_report"),
        lab_info=LabInfo(
            lab_name=data.get("lab_name"),
            doctor_name=data.get("doctor_name"),
        ),
        patient_info=PatientInfo(
            patient_name=data.get("patient_name"),
            patient_id=data.get("patient_id"),
            date_of_birth=data.get("date_of_birth"),
            sex=data.get("sex"),
        ),
        document_metadata=DocumentMetadata(
            dossier_number=data.get("dossier_number"),
            exam_number=data.get("exam_number"),
            sample_date=data.get("sample_date"),
            report_date=data.get("report_date"),
            page_number=data.get("page_number") and str(data.get("page_number")),
            source_file=source_file,
        ),
        tests=tests_out,
        warnings=[],
        extraction_source="gemini",
    )


def analyze_medical_document_gemini(
    api_key: str,
    model_name: str,
    ocr_text: str,
    image_path: Path | None = None,
    source_file: str = "",
) -> MedicalDocumentResult:
    """
    Appelle Gemini avec texte OCR (+ image si chemin fourni et fichier image).
    """
    user_parts: list[Any] = [
        SYSTEM_PROMPT,
        "\n\n--- TEXTE OCR (peut être bruité) ---\n",
        ocr_text[:120_000] if ocr_text else "(vide)",
    ]

    if image_path and image_path.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp", ".gif"}:
        try:
            user_parts.append("\n\n--- IMAGE DU DOCUMENT ---\n")
            user_parts.append(
                types.Part.from_bytes(
                    data=image_path.read_bytes(),
                    mime_type=guess_image_mime_type(image_path),
                )
            )
        except Exception as exc:
            logger.warning("Impossible de charger l'image pour Gemini: %s", exc)

    response_text = generate_vision_json(
        api_key=api_key,
        contents=user_parts,
        model_preference=model_name,
        retries=3,
        retry_delay_sec=2.0,
    )
    if not response_text:
        raise RuntimeError("Réponse Gemini vide")

    data = _parse_json_from_response(response_text)
    result = _gemini_dict_to_result(data, source_file=source_file)
    result.warnings.append(
        ProcessingWarning(code="GEMINI_OK", message=f"Modèle: {model_name}")
    )
    return result
