from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass(frozen=True)
class AppConfig:
    project_root: Path
    data_raw_dir: Path
    data_preprocessed_dir: Path
    data_extracted_text_dir: Path
    data_output_dir: Path
    tesseract_cmd: Optional[str]
    default_ocr_lang: str
    enable_easyocr_fallback: bool
    log_level: str
    save_intermediate_files: bool
    # Google Gemini (compréhension document / analyses)
    gemini_api_key: Optional[str]
    gemini_model: str
    # Historique des extractions (JSON par type, interface dédiée)
    extraction_history_dir: Path
    extraction_history_db_path: Path
    # Authentification API optionnelle.
    auth_enabled: bool
    auth_username: str
    auth_password_hash: Optional[str]
    auth_password: Optional[str]
    auth_token_secret: Optional[str]
    auth_token_ttl_minutes: int


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _default_project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def load_config(project_root: Optional[Path] = None) -> AppConfig:
    root = project_root or _default_project_root()
    data_dir = root / "data"

    # Windows-friendly default path; can be overridden by env.
    tesseract_default = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
    tesseract_cmd = os.getenv("TESSERACT_CMD", tesseract_default)

    # Charger .env : racine du projet puis répertoire courant (lancement Streamlit)
    try:
        from dotenv import load_dotenv

        load_dotenv(root / ".env", override=False)
        load_dotenv(Path.cwd() / ".env", override=False)
    except Exception:
        pass

    gemini_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    gemini_model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
    history_dir = Path(
        os.getenv("EXTRACTION_HISTORY_DIR", str(data_dir / "history" / "extractions"))
    )
    if not history_dir.is_absolute():
        history_dir = root / history_dir

    history_db_path = Path(
        os.getenv("EXTRACTION_HISTORY_DB_PATH", str(data_dir / "history" / "extractions.db"))
    )
    if not history_db_path.is_absolute():
        history_db_path = root / history_db_path

    return AppConfig(
        project_root=root,
        data_raw_dir=Path(os.getenv("DATA_RAW_DIR", str(data_dir / "raw"))),
        data_preprocessed_dir=Path(
            os.getenv("DATA_PREPROCESSED_DIR", str(data_dir / "preprocessed"))
        ),
        data_extracted_text_dir=Path(
            os.getenv("DATA_EXTRACTED_TEXT_DIR", str(data_dir / "extracted_text"))
        ),
        data_output_dir=Path(os.getenv("DATA_OUTPUT_DIR", str(data_dir / "output"))),
        tesseract_cmd=tesseract_cmd,
        default_ocr_lang=os.getenv("DEFAULT_OCR_LANG", "fra+eng"),
        enable_easyocr_fallback=_env_bool("ENABLE_EASYOCR_FALLBACK", True),
        log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
        save_intermediate_files=_env_bool("SAVE_INTERMEDIATE_FILES", True),
        gemini_api_key=gemini_key,
        gemini_model=gemini_model,
        extraction_history_dir=history_dir,
        extraction_history_db_path=history_db_path,
        auth_enabled=_env_bool("DOCUAI_AUTH_ENABLED", False),
        auth_username=os.getenv("DOCUAI_AUTH_USERNAME", "admin"),
        auth_password_hash=os.getenv("DOCUAI_AUTH_PASSWORD_HASH"),
        auth_password=os.getenv("DOCUAI_AUTH_PASSWORD"),
        auth_token_secret=os.getenv("DOCUAI_AUTH_TOKEN_SECRET"),
        auth_token_ttl_minutes=max(5, _env_int("DOCUAI_AUTH_TOKEN_TTL_MINUTES", 480)),
    )

