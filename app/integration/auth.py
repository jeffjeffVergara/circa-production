"""Auth para Circa Integration API v1 (socios → Circa)."""
from __future__ import annotations

import logging
import secrets
from typing import Annotated, Literal, Optional

from fastapi import Depends, HTTPException, Request, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.services import db

logger = logging.getLogger("circa.integration.auth")

DataMode = Literal["prod", "test"]

_bearer = HTTPBearer(
    auto_error=False,
    scheme_name="BearerAuth",
    description="Access token del distribuidor (prod o test). Obtener vía POST /auth/token.",
)

_DIST_SELECT = (
    "id,ruc,razon_social,nombre_comercial,estado,"
    "api_token,api_token_test,api_client_id,api_client_secret"
)


def path_data_mode(path: str) -> DataMode:
    """Detecta modo según path (/test/... o /api/v1/test/...)."""
    p = (path or "").rstrip("/")
    if p == "/test" or p.startswith("/test/"):
        return "test"
    if p.endswith("/api/v1/test") or "/api/v1/test/" in (path or ""):
        return "test"
    return "prod"


def _dist_activo(dist: dict) -> None:
    estado = (dist.get("estado") or "").lower()
    if estado and estado not in ("activo", "active", "habilitado", ""):
        raise HTTPException(status_code=403, detail="Distribuidor no activo")


def resolve_distribuidor_by_bearer(token: str) -> tuple[dict, DataMode]:
    """Busca distribuidor por api_token (prod) o api_token_test."""
    tok = (token or "").strip()
    if not tok:
        raise HTTPException(
            status_code=401,
            detail="Falta Authorization: Bearer <access_token>",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        by_prod = (
            db.sb.table("distribuidores")
            .select(_DIST_SELECT)
            .eq("api_token", tok)
            .limit(1)
            .execute()
            .data
            or []
        )
        if by_prod:
            return by_prod[0], "prod"
        by_test = (
            db.sb.table("distribuidores")
            .select(_DIST_SELECT)
            .eq("api_token_test", tok)
            .limit(1)
            .execute()
            .data
            or []
        )
        if by_test:
            return by_test[0], "test"
    except Exception as e:
        logger.error("Error validando access_token: %s", e)
        raise HTTPException(status_code=503, detail="No se pudo validar el token") from e

    raise HTTPException(
        status_code=401,
        detail="Token inválido",
        headers={"WWW-Authenticate": "Bearer"},
    )


async def get_current_distribuidor(
    request: Request,
    creds: Annotated[HTTPAuthorizationCredentials | None, Security(_bearer)],
) -> dict:
    """Valida Bearer y exige que el token coincida con el modo de la URL."""
    if not creds or not (creds.credentials or "").strip():
        raise HTTPException(
            status_code=401,
            detail="Falta Authorization: Bearer <access_token>",
            headers={"WWW-Authenticate": "Bearer"},
        )
    dist, token_mode = resolve_distribuidor_by_bearer(creds.credentials)
    _dist_activo(dist)

    url_mode = path_data_mode(request.url.path)
    if token_mode != url_mode:
        raise HTTPException(
            status_code=403,
            detail=(
                f"Este access_token es de modo '{token_mode}' pero la URL es modo '{url_mode}'. "
                "Use el token de producción en /api/v1/... y el de prueba en /api/v1/test/..."
            ),
        )
    dist = {**dist, "_token_mode": token_mode}
    return dist


def issue_access_token(
    *,
    client_id: str,
    client_secret: str,
    data_mode: DataMode = "prod",
) -> dict:
    """Intercambia client credentials por access_token del modo pedido."""
    cid = (client_id or "").strip()
    csec = (client_secret or "").strip()
    if not cid or not csec:
        raise HTTPException(status_code=400, detail="client_id y client_secret son obligatorios")

    try:
        rows = (
            db.sb.table("distribuidores")
            .select(_DIST_SELECT)
            .eq("api_client_id", cid)
            .limit(1)
            .execute()
            .data
            or []
        )
    except Exception as e:
        # Columnas aún no migradas
        logger.error("issue_access_token lookup failed: %s", e)
        raise HTTPException(
            status_code=503,
            detail="Auth no disponible (¿migración api_client_id pendiente?)",
        ) from e

    if not rows:
        raise HTTPException(status_code=401, detail="client_id o client_secret inválidos")

    dist = rows[0]
    stored = (dist.get("api_client_secret") or "").strip()
    if not stored or not secrets.compare_digest(stored, csec):
        raise HTTPException(status_code=401, detail="client_id o client_secret inválidos")

    _dist_activo(dist)

    if data_mode == "test":
        access = (dist.get("api_token_test") or "").strip()
        if not access:
            raise HTTPException(
                status_code=403,
                detail="Este distribuidor no tiene api_token_test configurado",
            )
    else:
        access = (dist.get("api_token") or "").strip()
        if not access:
            raise HTTPException(
                status_code=403,
                detail="Este distribuidor no tiene api_token configurado",
            )

    return {
        "access_token": access,
        "token_type": "Bearer",
        "data_mode": data_mode,
        "expires_in": None,
        "distribuidor_id": dist["id"],
        "distribuidor": dist.get("nombre_comercial") or dist.get("razon_social"),
    }
