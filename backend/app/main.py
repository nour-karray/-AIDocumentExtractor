from __future__ import annotations

import io
import json
import mimetypes
import zipfile
from datetime import date
from functools import partial
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from starlette.concurrency import run_in_threadpool

from backend.app.auth import LoginRequest, RegisterRequest, authenticate_login, register_user, require_auth
from backend.app.core import (
    build_dashboard_payload,
    build_history_detail,
    build_history_list_payload,
    build_meta_payload,
    build_models_payload,
    build_report_for_entry,
    delete_entry_by_key,
    find_history_entry,
    get_config,
    process_batch,
    resolve_archived_source_blob,
    resolve_archived_source_path,
)

AuthUser = Annotated[dict[str, str], Depends(require_auth)]

app = FastAPI(
    title="DocuAI API",
    version="2.0.0",
    summary="Backend FastAPI pour la nouvelle interface DocuAI",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:3001",
        "http://127.0.0.1:3001",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _parse_date(raw: str | None) -> date | None:
    if not raw:
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Date invalide: {raw}") from exc


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/auth/login")
def auth_login(payload: LoginRequest) -> dict:
    return authenticate_login(payload).model_dump()


@app.post("/api/auth/register")
def auth_register(payload: RegisterRequest) -> dict:
    return register_user(payload).model_dump()


@app.get("/api/auth/me")
def auth_me(user: AuthUser) -> dict:
    return {"user": {"username": user["username"]}, "mode": user["mode"]}


@app.get("/api/meta")
def meta() -> dict:
    return build_meta_payload(get_config())


@app.get("/api/dashboard")
def dashboard(_user: AuthUser) -> dict:
    return build_dashboard_payload(get_config())


@app.get("/api/models")
def models(_user: AuthUser) -> dict:
    return build_models_payload(get_config())


@app.get("/api/history")
def history(
    _user: AuthUser,
    kind: str = "",
    search: str = "",
    typeQuery: str = "",
    dateFrom: str | None = None,
    dateTo: str | None = None,
    page: int = 1,
    pageSize: int = 12,
) -> dict:
    return build_history_list_payload(
        get_config(),
        kind=kind,
        search=search,
        type_query=typeQuery,
        date_from=_parse_date(dateFrom),
        date_to=_parse_date(dateTo),
        page=page,
        page_size=pageSize,
    )


@app.get("/api/history/export/zip")
def history_export_zip(
    _user: AuthUser,
    entryKey: Annotated[list[str], Query(alias="entryKey")] = [],
) -> Response:
    if not entryKey:
        raise HTTPException(status_code=400, detail="Aucune entree selectionnee.")

    cfg = get_config()
    buffer = io.BytesIO()
    used_names: dict[str, int] = {}

    with zipfile.ZipFile(buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        for index, key in enumerate(entryKey, start=1):
            entry = find_history_entry(cfg, key)
            if entry is None:
                continue

            pdf_bytes = build_report_for_entry(cfg, entry)
            raw_name = str(entry.get("source_filename") or f"document_{index}")
            stem = Path(raw_name).stem or f"document_{index}"
            count = used_names.get(stem, 0)
            used_names[stem] = count + 1
            suffix = f"_{count + 1}" if count else ""
            archive.writestr(f"{stem}{suffix}_rapport.pdf", pdf_bytes)

    buffer.seek(0)
    headers = {
        "Content-Disposition": 'attachment; filename="documents_export.zip"'
    }
    return Response(content=buffer.getvalue(), media_type="application/zip", headers=headers)


@app.get("/api/history/{entry_key}")
def history_detail(entry_key: str, _user: AuthUser) -> dict:
    cfg = get_config()
    entry = find_history_entry(cfg, entry_key)
    if entry is None:
        raise HTTPException(status_code=404, detail="Entree introuvable.")
    return build_history_detail(cfg, entry)


@app.delete("/api/history/{entry_key}")
def history_delete(entry_key: str, _user: AuthUser) -> dict[str, str]:
    ok, message = delete_entry_by_key(get_config(), entry_key)
    if not ok:
        raise HTTPException(status_code=404, detail=message)
    return {"status": "ok", "message": message}


@app.get("/api/history/{entry_key}/report.pdf")
def history_report(entry_key: str, _user: AuthUser) -> Response:
    cfg = get_config()
    entry = find_history_entry(cfg, entry_key)
    if entry is None:
        raise HTTPException(status_code=404, detail="Entree introuvable.")
    pdf_bytes = build_report_for_entry(cfg, entry)
    stem = Path(str(entry.get("source_filename") or "document")).stem or "document"
    stem = stem.replace('"', "_").replace("\\", "_").replace("/", "_")
    headers = {"Content-Disposition": f'attachment; filename="DOCEXTRACT_{stem}.pdf"'}
    return Response(content=pdf_bytes, media_type="application/pdf", headers=headers)


@app.get("/api/history/{entry_key}/source")
def history_source(entry_key: str, _user: AuthUser):
    cfg = get_config()
    entry = find_history_entry(cfg, entry_key)
    if entry is None:
        raise HTTPException(status_code=404, detail="Entree introuvable.")
    payload = build_history_detail(cfg, entry).get("payload")
    source_path = resolve_archived_source_path(entry, cfg, payload if isinstance(payload, dict) else None)
    if source_path is None:
        source_blob = resolve_archived_source_blob(cfg, entry)
        if source_blob is not None:
            content, media_type = source_blob
            return Response(content=content, media_type=media_type)
        raise HTTPException(status_code=404, detail="Source archivee indisponible.")
    media_type, _ = mimetypes.guess_type(str(source_path))
    return FileResponse(path=source_path, media_type=media_type or "application/octet-stream")


@app.get("/api/results/latest")
def latest_result(_user: AuthUser):
    cfg = get_config()
    history = build_history_list_payload(cfg, page=1, page_size=1)
    items = history.get("items") if isinstance(history.get("items"), list) else []
    if not items:
        return JSONResponse({"item": None})
    entry = find_history_entry(cfg, items[0]["entryKey"])
    if entry is None:
        return JSONResponse({"item": None})
    return {"item": build_history_detail(cfg, entry)}


@app.post("/api/extractions")
async def extractions(
    files: Annotated[list[UploadFile], File(...)],
    _user: AuthUser,
    mode: Annotated[str, Form()] = "auto",
    method: Annotated[str, Form()] = "local",
    geminiApiKey: Annotated[str | None, Form()] = None,
    geminiModel: Annotated[str | None, Form()] = None,
    ollamaHost: Annotated[str | None, Form()] = None,
    localModel: Annotated[str | None, Form()] = None,
    retries: Annotated[int, Form()] = 5,
    retryDelay: Annotated[float, Form()] = 2.0,
    originsJson: Annotated[str | None, Form()] = None,
) -> dict:
    if not files:
        raise HTTPException(status_code=400, detail="Aucun fichier envoye.")

    origins: list[str] = []
    if originsJson:
        try:
            parsed = json.loads(originsJson)
            if isinstance(parsed, list):
                origins = [str(item or "upload") for item in parsed]
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=400, detail="originsJson invalide.") from exc

    payload_files: list[dict] = []
    for index, upload in enumerate(files):
        file_bytes = await upload.read()
        payload_files.append(
            {
                "name": upload.filename or f"document_{index + 1}",
                "bytes": file_bytes,
                "origin": origins[index] if index < len(origins) else "upload",
            }
        )

    return await run_in_threadpool(
        partial(
            process_batch,
            get_config(),
            files=payload_files,
            mode=mode,
            extraction_method=method,
            gemini_api_key=geminiApiKey,
            gemini_model=geminiModel,
            ollama_host=ollamaHost,
            local_model=localModel,
            retries=retries,
            retry_delay=retryDelay,
        )
    )
