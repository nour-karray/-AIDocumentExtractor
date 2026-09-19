from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AppConfig:
    project_root: Path
    data_raw_dir: Path
    data_preprocessed_dir: Path
    data_extracted_text_dir: Path
    data_output_dir: Path
    tesseract_cmd: str | None
    default_ocr_lang: str
    enable_easyocr_fallback: bool
    log_level: str
    save_intermediate_files: bool
    # Google Gemini (compréhension document / analyses)
    gemini_api_key: str | None
    gemini_model: str
    # Historique des extractions (JSON par type, interface dédiée)
    extraction_history_dir: Path
    extraction_history_db_path: Path
    # Authentification API optionnelle.
    auth_enabled: bool
    auth_username: str
    auth_password_hash: str | None
    auth_password: str | None
    auth_token_secret: str | None
    auth_token_ttl_minutes: int
    ollama_host: str = "http://127.0.0.1:11434"
    ollama_model: str = "qwen2.5:7b-instruct"
    extraction_timeout_seconds: float = 120.0
    max_document_bytes: int = 20 * 1024 * 1024
    max_batch_files: int = 10
    max_batch_bytes: int = 50 * 1024 * 1024
    store_source_files: bool = False
    store_raw_text: bool = False
    cors_origins: tuple[str, ...] = ("http://localhost:3000", "http://127.0.0.1:3000")


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


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env_origins(name: str) -> tuple[str, ...]:
    raw = os.getenv(name, "http://localhost:3000,http://127.0.0.1:3000")
    return tuple(origin.strip().rstrip("/") for origin in raw.split(",") if origin.strip())


def _default_project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def load_config(project_root: Path | None = None) -> AppConfig:
    root = project_root or _default_project_root()
    data_dir = root / "data"

    # Windows-friendly default path; can be overridden by env.
    tesseract_default = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
    tesseract_cmd = os.getenv("TESSERACT_CMD", tesseract_default)

    # Load local development configuration without overriding process values.
    try:
        from dotenv import load_dotenv

        load_dotenv(root / ".env", override=False)
        load_dotenv(Path.cwd() / ".env", override=False)
    except ImportError:
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
        auth_enabled=_env_bool("DOCIA_AUTH_ENABLED", False),
        auth_username=os.getenv("DOCIA_AUTH_USERNAME", "admin"),
        auth_password_hash=os.getenv("DOCIA_AUTH_PASSWORD_HASH"),
        auth_password=os.getenv("DOCIA_AUTH_PASSWORD"),
        auth_token_secret=os.getenv("DOCIA_AUTH_TOKEN_SECRET"),
        auth_token_ttl_minutes=max(5, _env_int("DOCIA_AUTH_TOKEN_TTL_MINUTES", 480)),
        ollama_host=os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/"),
        ollama_model=os.getenv("OLLAMA_MODEL", "qwen2.5:7b-instruct").strip(),
        extraction_timeout_seconds=max(5.0, _env_float("DOCIA_EXTRACTION_TIMEOUT_SECONDS", 120.0)),
        max_document_bytes=max(1, _env_int("DOCIA_MAX_DOCUMENT_BYTES", 20 * 1024 * 1024)),
        max_batch_files=max(1, _env_int("DOCIA_MAX_BATCH_FILES", 10)),
        max_batch_bytes=max(1, _env_int("DOCIA_MAX_BATCH_BYTES", 50 * 1024 * 1024)),
        store_source_files=_env_bool("DOCIA_STORE_SOURCE_FILES", False),
        store_raw_text=_env_bool("DOCIA_STORE_RAW_TEXT", False),
        cors_origins=_env_origins("DOCIA_CORS_ORIGINS"),
    )
