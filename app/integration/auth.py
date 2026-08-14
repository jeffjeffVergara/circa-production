"""Auth para Circa Integration API v1 (ERP externos → Circa)."""
from __future__ import annotations

import logging
from typing import Annotated

from fastapi import Depends, HTTPException, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.services import db

logger = logging.getLogger("circa.integration.auth")

_bearer = HTTPBearer(
    auto_error=False,
    scheme_name="BearerAuth",
    description="API token del distribuidor (campo distribuidores.api_token).",
)


async def get_current_distribuidor(
    creds: Annotated[HTTPAuthorizationCredentials | None, Security(_bearer)],
) -> dict:
    """Valida Bearer token contra distribuidores.api_token."""
    if not creds or not (creds.credentials or "").strip():
        raise HTTPException(
            status_code=401,
            detail="Falta Authorization: Bearer <api_token>",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = creds.credentials.strip()
    try:
        rows = (
            db.sb.table("distribuidores")
            .select("id,ruc,razon_social,nombre_comercial,estado,api_token")
            .eq("api_token", token)
            .limit(1)
            .execute()
            .data
            or []
        )
    except Exception as e:
        logger.error("Error validando api_token: %s", e)
        raise HTTPException(status_code=503, detail="No se pudo validar el token") from e

    if not rows:
        raise HTTPException(
            status_code=401,
            detail="Token inválido",
            headers={"WWW-Authenticate": "Bearer"},
        )
    dist = rows[0]
    estado = (dist.get("estado") or "").lower()
    if estado and estado not in ("activo", "active", "habilitado", ""):
        raise HTTPException(status_code=403, detail="Distribuidor no activo")
    return dist
