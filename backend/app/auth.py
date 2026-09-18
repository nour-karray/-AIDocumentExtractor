from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import InvalidTokenError
from pydantic import BaseModel, Field

from backend.app.core import get_config
from src.config import AppConfig

TOKEN_ALGORITHM = "HS256"
PASSWORD_HASH_ALGORITHM = "pbkdf2_sha256"
security = HTTPBearer(auto_error=False)


class LoginRequest(BaseModel):
    username: str = Field(min_length=1)
    password: str = Field(min_length=1)


class LoginResponse(BaseModel):
    accessToken: str
    tokenType: str = "bearer"
    expiresAt: str
    user: dict[str, str]


def hash_password(
    password: str, *, salt: str | None = None, iterations: int = 210_000
) -> str:
    """Return a PBKDF2 hash usable as DOCIA_AUTH_PASSWORD_HASH."""
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt.encode("utf-8"), iterations
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


def validate_auth_config(cfg: AppConfig) -> None:
    if not cfg.auth_enabled:
        return
    if not cfg.auth_token_secret:
        raise RuntimeError(
            "DOCIA_AUTH_TOKEN_SECRET is required when DOCIA_AUTH_ENABLED=true."
        )
    if not (cfg.auth_password_hash or cfg.auth_password):
        raise RuntimeError(
            "DOCIA_AUTH_PASSWORD_HASH or DOCIA_AUTH_PASSWORD is required when authentication is enabled."
        )


def build_auth_meta(cfg: AppConfig) -> dict[str, Any]:
    return {
        "enabled": cfg.auth_enabled,
        "loginUrl": "/api/auth/login",
        "meUrl": "/api/auth/me",
        "tokenType": "bearer",
        "ttlMinutes": cfg.auth_token_ttl_minutes,
        "usernameHint": cfg.auth_username if cfg.auth_enabled else None,
    }


def authenticate_login(payload: LoginRequest) -> LoginResponse:
    cfg = get_config()
    validate_auth_config(cfg)
    if payload.username != cfg.auth_username or not verify_password(payload.password, cfg):
        raise _unauthorized("Identifiants invalides.")
    token, expires_at = create_access_token(cfg, payload.username)
    return LoginResponse(
        accessToken=token,
        expiresAt=expires_at,
        user={"username": payload.username},
    )


def require_auth(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
) -> dict[str, str]:
    cfg = get_config()
    if not cfg.auth_enabled:
        return {"username": cfg.auth_username, "mode": "disabled"}
    if credentials is None:
        raise _unauthorized()
    payload = decode_access_token(credentials.credentials, cfg)
    username = str(payload.get("sub") or "")
    if not username:
        raise _unauthorized("Jeton invalide.")
    return {"username": username, "mode": "bearer"}


def create_access_token(cfg: AppConfig, username: str) -> tuple[str, str]:
    validate_auth_config(cfg)
    now = datetime.now(UTC)
    expires_at = now + timedelta(minutes=cfg.auth_token_ttl_minutes)
    token = jwt.encode(
        {"sub": username, "iat": now, "exp": expires_at},
        cfg.auth_token_secret,
        algorithm=TOKEN_ALGORITHM,
    )
    return token, expires_at.isoformat()


def decode_access_token(token: str, cfg: AppConfig) -> dict[str, Any]:
    validate_auth_config(cfg)
    try:
        payload = jwt.decode(
            token,
            cfg.auth_token_secret,
            algorithms=[TOKEN_ALGORITHM],
            options={"require": ["sub", "iat", "exp"]},
        )
    except InvalidTokenError as exc:
        raise _unauthorized("Jeton invalide ou expire.") from exc
    if not isinstance(payload, dict):
        raise _unauthorized("Jeton invalide.")
    return payload


def _unauthorized(detail: str = "Authentification requise.") -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )
