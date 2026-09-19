import inspect
import time
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import backend.app.core as core
import backend.app.main as main_module
from backend.app.auth import require_auth, validate_auth_config
from src.config import load_config
from src.services.extraction_history import list_history_entries, save_extraction


def _slow_marker_worker(connection, marker: str) -> None:
    time.sleep(0.5)
    Path(marker).write_text("late", encoding="utf-8")
    connection.send(("ok", "late"))


def _client(monkeypatch, cfg):
    monkeypatch.setattr(main_module, "get_config", lambda: cfg)
    return TestClient(main_module.app)


def test_auth_disabled_allows_access_without_token(monkeypatch, tmp_path):
    cfg = replace(load_config(tmp_path), auth_enabled=False)
    monkeypatch.setattr("backend.app.auth.get_config", lambda: cfg)
    assert require_auth(None) == {"username": cfg.auth_username, "mode": "disabled"}
    with _client(monkeypatch, cfg) as client:
        assert client.get("/api/dashboard").status_code == 200


def test_auth_enabled_without_secret_fails_configuration(tmp_path):
    cfg = replace(load_config(tmp_path), auth_enabled=True, auth_password="secret", auth_token_secret=None)
    with pytest.raises(RuntimeError):
        validate_auth_config(cfg)


def test_error_status_survives_persistence_and_summary(tmp_path):
    cfg = load_config(tmp_path)
    save_extraction(
        cfg,
        "extraction_error",
        "synthetic.pdf",
        {
            "document_type": "unknown",
            "error": "synthetic failure",
            "method": "ocr",
            "raw_text": "must not persist",
        },
        source_bytes=b"private",
        status="error",
        error_message="synthetic failure",
    )
    entry = list_history_entries(cfg)[0]
    assert core.history_summary(entry, cfg)["status"] == "error"
    assert entry["payload"]["error"] == "synthetic failure"
    assert "raw_text" not in entry["payload"]
    assert not list(cfg.extraction_history_dir.rglob("*.pdf"))


def test_timeout_terminates_worker_before_late_side_effect(tmp_path):
    marker = tmp_path / "late.txt"
    outcome, _ = core._run_process_with_timeout(
        _slow_marker_worker,
        (str(marker),),
        0.1,
    )
    assert outcome == "timeout"
    time.sleep(0.6)
    assert not marker.exists()


@pytest.mark.parametrize(
    ("files", "cfg_changes", "expected_detail"),
    [
        ({"files": ("large.pdf", b"12345", "application/pdf")}, {"max_document_bytes": 4}, "Fichier trop volumineux"),
        (
            [
                ("files", ("one.pdf", b"123", "application/pdf")),
                ("files", ("two.pdf", b"456", "application/pdf")),
            ],
            {"max_document_bytes": 10, "max_batch_bytes": 5},
            "Taille totale du lot depassee",
        ),
    ],
)
def test_upload_size_limits(monkeypatch, tmp_path, files, cfg_changes, expected_detail):
    cfg = replace(load_config(tmp_path), **cfg_changes)
    with _client(monkeypatch, cfg) as client:
        response = client.post("/api/extractions", files=files)
    assert response.status_code == 413
    assert expected_detail in response.json()["detail"]


@pytest.mark.parametrize(("field", "value"), [("retries", "6"), ("retries", "-1"), ("retryDelay", "11")])
def test_retry_parameters_are_bounded(monkeypatch, tmp_path, field, value):
    cfg = load_config(tmp_path)
    with _client(monkeypatch, cfg) as client:
        response = client.post(
            "/api/extractions",
            data={field: value},
            files={"files": ("synthetic.pdf", b"pdf", "application/pdf")},
        )
    assert response.status_code == 422


def test_sroie_ground_truth_is_not_part_of_runtime():
    source = inspect.getsource(core.process_single_document)
    assert "sroie" not in source.lower()
    assert not hasattr(core, "_sroie_annotation_payload")


def test_invalid_entry_key_and_unsupported_file(monkeypatch, tmp_path):
    cfg = load_config(tmp_path)
    with _client(monkeypatch, cfg) as client:
        invalid_key = client.get("/api/history/not-valid-base64")
        unsupported = client.post(
            "/api/extractions",
            files={"files": ("synthetic.exe", b"nope", "application/octet-stream")},
        )
    assert invalid_key.status_code == 404
    assert unsupported.status_code == 400


def test_public_meta_hides_server_paths_and_hosts(monkeypatch, tmp_path):
    cfg = replace(load_config(tmp_path), ollama_host="http://internal-host:11434")
    with _client(monkeypatch, cfg) as client:
        response = client.get("/api/meta")
    assert response.status_code == 200
    serialized = response.text
    assert "internal-host" not in serialized
    assert str(tmp_path.resolve()) not in serialized
    assert "pathHint" not in serialized


def test_tesseract_status_requires_real_executable(monkeypatch, tmp_path):
    missing = tmp_path / "missing-tesseract"
    monkeypatch.setattr(core.shutil, "which", lambda _name: None)
    assert core._tesseract_available(str(missing)) is False
    executable = tmp_path / "tesseract.exe"
    executable.write_bytes(b"synthetic")
    assert core._tesseract_available(str(executable)) is True


def test_steg_normalization_uses_existing_temp_file(monkeypatch, tmp_path):
    cfg = load_config(tmp_path)
    monkeypatch.setattr(core, "_detect_kind_safely", lambda *args, **kwargs: "steg_invoice")
    monkeypatch.setattr(
        core,
        "_try_process_document",
        lambda *args, **kwargs: (
            {"kind": "steg", "result": {"reference": "SYNTH", "extraction_source": "gemini"}},
            None,
        ),
    )

    def normalize(payload, path):
        assert path.exists()
        return payload

    monkeypatch.setattr(core, "_normalize_steg_payload_fields_from_image_path", normalize)
    result = core.process_single_document(
        cfg,
        filename="synthetic.png",
        file_bytes=b"synthetic",
        origin="upload",
        mode="steg",
        extraction_method="gemini",
        gemini_api_key="synthetic-key",
        gemini_model="synthetic-model",
        ollama_host=None,
        local_model=None,
        retries=0,
        retry_delay=0,
    )
    assert result["status"] == "ok"
