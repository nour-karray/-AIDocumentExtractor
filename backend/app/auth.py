from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import sqlite3
import time
from datetime import datetime, timezone
from typing import Any

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from backend.app.core import get_config
from src.config import AppConfig


TOKEN_ALGORITHM = "HS256"
PASSWORD_HASH_ALGORITHM = "pbkdf2_sha256"
security = HTTPBearer(auto_error=False)


class LoginRequest(BaseModel):
    username: str = Field(min_length=1)
    password: str = Field(min_length=1)


class RegisterRequest(BaseModel):
    username: str = Field(min_length=3, max_length=64, pattern=r"^[A-Za-z0-9_.-]+$")
    password: str = Field(min_length=6, max_length=128)


class LoginResponse(BaseModel):
    accessToken: str
    tokenType: str = "bearer"
    expiresAt: str
    user: dict[str, str]


def hash_password(password: str, *, salt: str | None = None, iterations: int = 210_000) -> str:
    """Return a PBKDF2 hash usable as DOCUAI_AUTH_PASSWORD_HASH."""
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        iterations,
    )
    encoded = base64.b64encode(digest).decode("ascii")
    return f"{PASSWORD_HASH_ALGORITHM}${iterations}${salt}${encoded}"


def verify_password(password: str, cfg: AppConfig) -> bool:
    if cfg.auth_password_hash:
        parts = cfg.auth_password_hash.split("$")
        if len(parts) != 4 or parts[0] != PASSWORD_HASH_ALGORITHM:
            return False
        try:
            iterations = int(parts[1])
        except ValueError:
            return False
        candidate = hash_password(password, salt=parts[2], iterations=iterations)
        return hmac.compare_digest(candidate, cfg.auth_password_hash)

    if cfg.auth_password:
        return hmac.compare_digest(password, cfg.auth_password)

    return False


def build_auth_meta(cfg: AppConfig) -> dict[str, Any]:
    return {
        "enabled": cfg.auth_enabled,
        "loginUrl": "/api/auth/login",
        "meUrl": "/api/auth/me",
        "tokenType": "bearer",
        "ttlMinutes": cfg.auth_token_ttl_minutes,
        "usernameHint": cfg.auth_username if cfg.auth_enabled else None,
    }


def create_login_response(cfg: AppConfig, username: str) -> LoginResponse:
    token, expires_at = create_access_token(cfg, username)
    return LoginResponse(
        accessToken=token,
        expiresAt=expires_at,
        user={"username": username},
    )


def authenticate_login(payload: LoginRequest) -> LoginResponse:
    cfg = get_config()
    user = _find_registered_user(cfg, payload.username)
    if user is not None:
        stored_hash = str(user.get("password_hash") or "")
        if _verify_password_hash(payload.password, stored_hash):
            return create_login_response(cfg, payload.username)
        raise _unauthorized("Identifiants invalides.")

    if not (cfg.auth_password_hash or cfg.auth_password):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Aucun compte ne correspond a cet utilisateur. Creez un compte ou configurez DOCUAI_AUTH_PASSWORD.",
        )
    if payload.username != cfg.auth_username or not verify_password(payload.password, cfg):
        raise _unauthorized("Identifiants invalides.")
    return create_login_response(cfg, payload.username)


def register_user(payload: RegisterRequest) -> LoginResponse:
    cfg = get_config()
    username = payload.username.strip()
    if username.casefold() == cfg.auth_username.casefold() and (cfg.auth_password_hash or cfg.auth_password):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Ce nom utilisateur est reserve par la configuration admin.",
        )
    if _find_registered_user(cfg, username) is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Ce nom utilisateur existe deja.",
        )
    _create_registered_user(cfg, username, payload.password)
    return create_login_response(cfg, username)


def require_auth(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
) -> dict[str, str]:
    cfg = get_config()
    if not cfg.auth_enabled:
        return {"username": "anonymous", "mode": "disabled"}
    if credentials is None:
        raise _unauthorized()
    payload = decode_access_token(credentials.credentials, cfg)
    username = str(payload.get("sub") or "")
    if not username:
        raise _unauthorized("Jeton invalide.")
    return {"username": username, "mode": "bearer"}


def _auth_db_path(cfg: AppConfig) -> str:
    path = cfg.project_root / "Data" / "auth" / "users.db"
    path.parent.mkdir(parents=True, exist_ok=True)
    return str(path)


def _ensure_user_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS auth_users (
            username TEXT PRIMARY KEY,
            password_hash TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )


def _find_registered_user(cfg: AppConfig, username: str) -> dict[str, Any] | None:
    with sqlite3.connect(_auth_db_path(cfg)) as conn:
        conn.row_factory = sqlite3.Row
        _ensure_user_table(conn)
        row = conn.execute(
            "SELECT username, password_hash, created_at FROM auth_users WHERE lower(username) = lower(?)",
            (username.strip(),),
        ).fetchone()
    return dict(row) if row is not None else None


def _create_registered_user(cfg: AppConfig, username: str, password: str) -> None:
    with sqlite3.connect(_auth_db_path(cfg)) as conn:
        _ensure_user_table(conn)
        conn.execute(
            """
            INSERT INTO auth_users (username, password_hash, created_at)
            VALUES (?, ?, ?)
            """,
            (username, hash_password(password), datetime.now(timezone.utc).isoformat()),
        )


def _verify_password_hash(password: str, password_hash: str) -> bool:
    parts = password_hash.split("$")
    if len(parts) != 4 or parts[0] != PASSWORD_HASH_ALGORITHM:
        return False
    try:
        iterations = int(parts[1])
    except ValueError:
        return False
    candidate = hash_password(password, salt=parts[2], iterations=iterations)
    return hmac.compare_digest(candidate, password_hash)


def create_access_token(cfg: AppConfig, username: str) -> tuple[str, str]:
    now = int(time.time())
    exp = now + (cfg.auth_token_ttl_minutes * 60)
    header = {"alg": TOKEN_ALGORITHM, "typ": "JWT"}
    payload = {"sub": username, "iat": now, "exp": exp}
    signing_input = f"{_b64_json(header)}.{_b64_json(payload)}"
    signature = hmac.new(
        _token_secret(cfg),
        signing_input.encode("ascii"),
        hashlib.sha256,
    ).digest()
    token = f"{signing_input}.{_b64_bytes(signature)}"
    expires_at = datetime.fromtimestamp(exp, timezone.utc).isoformat()
    return token, expires_at


def decode_access_token(token: str, cfg: AppConfig) -> dict[str, Any]:
    try:
        header_part, payload_part, signature_part = token.split(".", 2)
    except ValueError as exc:
        raise _unauthorized("Jeton invalide.") from exc

    signing_input = f"{header_part}.{payload_part}"
    expected = hmac.new(
        _token_secret(cfg),
        signing_input.encode("ascii"),
        hashlib.sha256,
    ).digest()
    try:
        received = _b64_decode(signature_part)
    except ValueError as exc:
        raise _unauthorized("Signature invalide.") from exc
    if not hmac.compare_digest(expected, received):
        raise _unauthorized("Signature invalide.")

    header = _json_from_b64(header_part)
    if header.get("alg") != TOKEN_ALGORITHM:
        raise _unauthorized("Algorithme de jeton invalide.")

    payload = _json_from_b64(payload_part)
    exp = payload.get("exp")
    if not isinstance(exp, int) or exp < int(time.time()):
        raise _unauthorized("Jeton expire.")
    return payload


def _token_secret(cfg: AppConfig) -> bytes:
    raw = cfg.auth_token_secret or cfg.auth_password_hash or cfg.auth_password
    if not raw:
        raw = "docuai-development-token-secret"
    return raw.encode("utf-8")


def _b64_json(data: dict[str, Any]) -> str:
    raw = json.dumps(data, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return _b64_bytes(raw)


def _json_from_b64(data: str) -> dict[str, Any]:
    try:
        decoded = json.loads(_b64_decode(data).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise _unauthorized("Jeton invalide.") from exc
    if not isinstance(decoded, dict):
        raise _unauthorized("Jeton invalide.")
    return decoded


def _b64_bytes(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _b64_decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    try:
        return base64.urlsafe_b64decode((data + padding).encode("ascii"))
    except Exception as exc:
        raise ValueError("Invalid base64") from exc


def _unauthorized(detail: str = "Authentification requise.") -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )
