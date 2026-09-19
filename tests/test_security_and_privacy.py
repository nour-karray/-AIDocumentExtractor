import sqlite3
from dataclasses import replace

import pytest

from backend.app.auth import (
    create_access_token,
    decode_access_token,
    hash_password,
    validate_auth_config,
    verify_password,
)
from src.config import load_config
from src.services.extraction_history import save_extraction


def test_auth_requires_explicit_secret_and_round_trips_token(tmp_path):
    base = load_config(tmp_path)
    insecure = replace(base, auth_enabled=True, auth_password="secret", auth_token_secret=None)
    with pytest.raises(RuntimeError):
        validate_auth_config(insecure)

    cfg = replace(insecure, auth_password=None, auth_password_hash=hash_password("secret"), auth_token_secret="test-secret-not-for-production")
    assert verify_password("secret", cfg)
    token, _ = create_access_token(cfg, "admin")
    assert decode_access_token(token, cfg)["sub"] == "admin"


def test_history_does_not_store_source_or_raw_text_by_default(tmp_path):
    cfg = load_config(tmp_path)
    save_extraction(
        cfg,
        "medical_ocr",
        "synthetic.png",
        {"patient": "synthetic", "raw_text": "sensitive raw value"},
        source_bytes=b"private bytes",
    )
    assert not list(cfg.extraction_history_dir.rglob("*.png"))
    with sqlite3.connect(cfg.extraction_history_db_path) as conn:
        payload_json = conn.execute("SELECT payload_json FROM extraction_history").fetchone()[0]
    assert "sensitive raw value" not in payload_json
    assert "synthetic" in payload_json
