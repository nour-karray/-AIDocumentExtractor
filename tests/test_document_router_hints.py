from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.config import AppConfig
from src.services import document_router


def _test_config(tmp_path: Path) -> AppConfig:
    history_dir = tmp_path / "history" / "extractions"
    return AppConfig(
        project_root=tmp_path,
        data_raw_dir=tmp_path / "data" / "raw",
        data_preprocessed_dir=tmp_path / "data" / "preprocessed",
        data_extracted_text_dir=tmp_path / "data" / "extracted_text",
        data_output_dir=tmp_path / "data" / "output",
        tesseract_cmd=None,
        default_ocr_lang="eng",
        enable_easyocr_fallback=False,
        log_level="INFO",
        save_intermediate_files=False,
        gemini_api_key=None,
        gemini_model="gemini-2.5-flash",
        extraction_history_dir=history_dir,
        extraction_history_db_path=tmp_path / "history" / "extractions.db",
        auth_enabled=False,
        auth_username="admin",
        auth_password_hash=None,
        auth_password=None,
        auth_token_secret=None,
        auth_token_ttl_minutes=480,
    )


def test_detect_document_type_uses_original_filename_hint_for_temp_file(tmp_path, monkeypatch):
    temp_image = tmp_path / "tmp_random_upload_name.jpg"
    temp_image.write_bytes(b"not a real image")

    def fail_if_ocr_runs(_path: Path) -> str:
        raise AssertionError("filename hint should classify STEG before OCR")

    monkeypatch.setattr(document_router, "build_document_router_text", fail_if_ocr_runs)

    detected = document_router.detect_document_type(
        temp_image,
        filename_hint="20260428T104423Z_steg3.jpg",
    )

    assert detected == "steg_invoice"

    detected_from_path = document_router.detect_document_type(
        temp_image,
        filename_hint="document.jpg",
        path_hint="Data/history/extractions/steg_gemini",
    )

    assert detected_from_path == "steg_invoice"


def test_auto_gemini_falls_back_to_steg_ocr_with_original_filename(tmp_path, monkeypatch):
    from backend.app.core import process_single_document

    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)

    result = process_single_document(
        _test_config(tmp_path),
        filename="20260428T104423Z_steg3.jpg",
        file_bytes=b"not a real image",
        origin="upload",
        mode="auto",
        extraction_method="gemini",
        gemini_api_key=None,
        gemini_model=None,
        ollama_host=None,
        local_model=None,
        retries=1,
        retry_delay=0.0,
    )

    assert result["status"] == "ok"
    assert result["detectedType"] == "steg_invoice"
    assert result["kind"] == "steg_ocr"
    assert result["payload"]["document_type"] == "steg_invoice"
