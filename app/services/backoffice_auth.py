"""Autenticación del backoffice Circa (usuario soporte, token firmado HMAC)."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from typing import Any

import bcrypt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

TOKEN_TTL_SEC = int(os.getenv("BACKOFFICE_TOKEN_TTL_SEC", str(8 * 3600)))
ROLE_ADMIN = "admin"
ROLE_VIEWER = "viewer"
_bearer = HTTPBearer(auto_error=False)


def _jwt_secret() -> str:
    from app.config import backoffice_jwt_secret_or_raise

    return backoffice_jwt_secret_or_raise()


def bootstrap_credentials() -> tuple[str, str]:
    from app.config import backoffice_password_or_raise

    email = (os.getenv("BACKOFFICE_EMAIL") or "soporte@circa.pe").strip().lower()
    password = backoffice_password_or_raise()
    return email, password


def viewer_credentials() -> tuple[str, str] | None:
    accounts = backoffice_viewer_accounts()
    return accounts[0] if accounts else None


def _viewer_accounts() -> list[tuple[str, str]]:
    from app.config import backoffice_viewer_accounts

    return backoffice_viewer_accounts()


def verify_password(plain: str, hashed: str | None = None) -> bool:
    """Verifica contra hash en BD o contra password de entorno (bootstrap)."""
    if hashed:
        try:
            return bcrypt.checkpw(plain.encode(), hashed.encode())
        except Exception:
            return False
    _, env_pass = bootstrap_credentials()
    return hmac.compare_digest(plain, env_pass)


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()


def authenticate(email: str, password: str) -> dict[str, Any] | None:
    """Valida credenciales admin o viewer (solo lectura)."""
    normalized = email.strip().lower()
    plain = password or ""
    boot_email, _ = bootstrap_credentials()
    if normalized == boot_email and verify_password(plain):
        return {"id": "bootstrap-admin", "email": normalized, "role": ROLE_ADMIN}
    for viewer_email, viewer_pass in _viewer_accounts():
        if normalized == viewer_email and hmac.compare_digest(plain, viewer_pass):
            return {"id": "bootstrap-viewer", "email": normalized, "role": ROLE_VIEWER}
    return None


def create_token(user_id: str, email: str, role: str = ROLE_ADMIN) -> str:
    payload = {
        "sub": user_id,
        "email": email,
        "role": role,
        "exp": int(time.time()) + TOKEN_TTL_SEC,
    }
    body = base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode()).decode().rstrip("=")
    sig = hmac.new(_jwt_secret().encode(), body.encode(), hashlib.sha256).hexdigest()
    return f"{body}.{sig}"


def decode_token(token: str) -> dict[str, Any]:
    if not token or "." not in token:
        raise HTTPException(status_code=401, detail="Token inválido")
    body, sig = token.split(".", 1)
    expected = hmac.new(_jwt_secret().encode(), body.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, sig):
        raise HTTPException(status_code=401, detail="Token inválido")
    pad = "=" * (-len(body) % 4)
    try:
        payload = json.loads(base64.urlsafe_b64decode(body + pad))
    except Exception:
        raise HTTPException(status_code=401, detail="Token inválido")
    if int(payload.get("exp") or 0) < int(time.time()):
        raise HTTPException(status_code=401, detail="Sesión expirada")
    return payload


async def get_backoffice_user(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> dict[str, Any]:
    if not creds or creds.scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="Autenticación requerida")
    payload = decode_token(creds.credentials)
    return {
        "id": payload.get("sub") or "bootstrap",
        "email": payload.get("email") or bootstrap_credentials()[0],
        "role": payload.get("role") or ROLE_ADMIN,
    }


async def get_backoffice_writer(
    user: dict[str, Any] = Depends(get_backoffice_user),
) -> dict[str, Any]:
    if user.get("role") == ROLE_VIEWER:
        raise HTTPException(
            status_code=403,
            detail="Acceso de solo lectura: no puedes modificar datos",
        )
    return user


def verify_reauth_password(password: str) -> None:
    if not verify_password(password or ""):
        raise HTTPException(status_code=403, detail="Contraseña incorrecta")
