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
_bearer = HTTPBearer(auto_error=False)


def _jwt_secret() -> str:
    return (
        os.getenv("BACKOFFICE_JWT_SECRET")
        or os.getenv("CIRCA_ADMIN_TOKEN")
        or "circa-backoffice-dev-secret"
    )


def bootstrap_credentials() -> tuple[str, str]:
    email = (os.getenv("BACKOFFICE_EMAIL") or "soporte@circa.pe").strip().lower()
    password = os.getenv("BACKOFFICE_PASSWORD") or "circa-soporte-2026"
    return email, password


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


def create_token(user_id: str, email: str) -> str:
    payload = {
        "sub": user_id,
        "email": email,
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
    }


def verify_reauth_password(password: str) -> None:
    if not verify_password(password or ""):
        raise HTTPException(status_code=403, detail="Contraseña incorrecta")
