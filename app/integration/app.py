"""
Circa Integration API v1 — sub-aplicación FastAPI con Swagger/ReDoc propios.

URLs (producción):
  Swagger UI:  https://<host>/api/v1/docs
  ReDoc:       https://<host>/api/v1/redoc
  OpenAPI:     https://<host>/api/v1/openapi.json
"""
from __future__ import annotations

from typing import Annotated, Optional

from fastapi import APIRouter, Depends, FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware

from app.integration.auth import get_current_distribuidor
from app.integration import schemas as S
from app.integration import service as svc

DESCRIPTION = """
## Circa Integration API

API para que **ERPs externos de distribuidores** se conecten a Circa sin duplicar
registros de clientes, preventas y pedidos.

### Autenticación
```
Authorization: Bearer <api_token>
```
El `api_token` lo emite Circa por distribuidor (`distribuidores.api_token`).

### Principios
- **Upsert** de bodegas por `external_id`, WhatsApp, RUC o DNI/CE
- Precarga **no libera línea** (`linea_disponible = 0`)
- La activación KYC/PIN del dueño sigue en WhatsApp
- Use `external_id` del ERP para idempotencia

### Soporte
contacto@circa.pe · +51 986 311 567
"""

integration_app = FastAPI(
    title="Circa Integration API",
    version="1.0.0",
    description=DESCRIPTION,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    contact={"name": "Circa / PALI S.A.C.", "email": "contacto@circa.pe"},
    license_info={"name": "Proprietary"},
)

integration_app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

router = APIRouter(tags=["Integration"])
DistDep = Annotated[dict, Depends(get_current_distribuidor)]


@router.get(
    "/health",
    response_model=S.HealthResponse,
    summary="Health check",
    tags=["Meta"],
)
async def health():
    return S.HealthResponse()


# ── Bodegas / Enrolamiento ──────────────────────────────────────────────────

@router.post(
    "/bodegas",
    response_model=S.BodegaResponse,
    summary="Crear o actualizar bodega (enrolamiento / precarga)",
    tags=["Bodegas"],
)
async def upsert_bodega(body: S.BodegaUpsertRequest, dist: DistDep):
    """
    Crea la bodega si no existe, o actualiza datos comerciales si ya está.
    No libera línea de crédito. Idempotente si envía `external_id`.
    """
    return svc.upsert_bodega(dist, body.model_dump())


@router.get(
    "/bodegas",
    response_model=S.ListResponse,
    summary="Listar / buscar bodegas",
    tags=["Bodegas"],
)
async def list_bodegas(
    dist: DistDep,
    q: Optional[str] = Query(None, description="Busca en nombre, DNI, RUC, tel, external_id"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    return svc.list_bodegas(dist, q=q, limit=limit, offset=offset)


@router.get(
    "/bodegas/{bodega_id}",
    response_model=S.BodegaResponse,
    summary="Obtener bodega por ID Circa",
    tags=["Bodegas"],
)
async def get_bodega(bodega_id: str, dist: DistDep):
    row = svc.find_bodega(dist["id"], bodega_id=bodega_id)
    if not row:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Bodega no encontrada")
    return svc._bodega_out(row)


@router.patch(
    "/bodegas/{bodega_id}",
    response_model=S.BodegaResponse,
    summary="Modificar datos comerciales de bodega",
    tags=["Bodegas"],
)
async def patch_bodega(bodega_id: str, body: S.BodegaPatchRequest, dist: DistDep):
    return svc.patch_bodega(dist, bodega_id, body.model_dump(exclude_unset=True))


# ── Preventas ───────────────────────────────────────────────────────────────

@router.post(
    "/preventas",
    response_model=S.PedidoResponse,
    summary="Crear preventa",
    tags=["Preventas"],
)
async def create_preventa(body: S.PreventaCreateRequest, dist: DistDep):
    """Crea pedido tipo preventa. Idempotente con `external_id`."""
    return svc.create_preventa(dist, body.model_dump())


@router.get(
    "/preventas",
    response_model=S.ListResponse,
    summary="Listar preventas",
    tags=["Preventas"],
)
async def list_preventas(
    dist: DistDep,
    estado: Optional[str] = None,
    bodega_id: Optional[str] = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    return svc.list_pedidos(
        dist, estado=estado, tipo="preventa", bodega_id=bodega_id, limit=limit, offset=offset,
    )


@router.get(
    "/preventas/{pedido_id}",
    response_model=S.PedidoResponse,
    summary="Obtener preventa",
    tags=["Preventas"],
)
async def get_preventa(pedido_id: str, dist: DistDep):
    ped = svc.get_pedido(dist, pedido_id)
    return ped


# ── Pedidos ─────────────────────────────────────────────────────────────────

@router.get(
    "/pedidos",
    response_model=S.ListResponse,
    summary="Listar pedidos",
    tags=["Pedidos"],
)
async def list_pedidos(
    dist: DistDep,
    estado: Optional[str] = None,
    bodega_id: Optional[str] = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    return svc.list_pedidos(dist, estado=estado, bodega_id=bodega_id, limit=limit, offset=offset)


@router.get(
    "/pedidos/{pedido_id}",
    response_model=S.PedidoResponse,
    summary="Obtener pedido",
    tags=["Pedidos"],
)
async def get_pedido(pedido_id: str, dist: DistDep):
    return svc.get_pedido(dist, pedido_id)


@router.patch(
    "/pedidos/{pedido_id}/estado",
    response_model=S.PedidoResponse,
    summary="Cambiar estado de pedido / preventa",
    tags=["Pedidos"],
)
async def patch_estado(pedido_id: str, body: S.PedidoEstadoPatch, dist: DistDep):
    return svc.patch_pedido_estado(dist, pedido_id, body.estado, body.comentario)


integration_app.include_router(router)


def custom_openapi():
    if integration_app.openapi_schema:
        return integration_app.openapi_schema
    from fastapi.openapi.utils import get_openapi

    schema = get_openapi(
        title=integration_app.title,
        version=integration_app.version,
        description=integration_app.description,
        routes=integration_app.routes,
        contact=integration_app.contact,
    )
    schema["components"] = schema.get("components") or {}
    schema["components"]["securitySchemes"] = {
        "BearerAuth": {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "API Token",
            "description": "Token del distribuidor (distribuidores.api_token)",
        }
    }
    # Aplicar seguridad global (excepto health)
    for path, methods in schema.get("paths", {}).items():
        if path.endswith("/health"):
            continue
        for method in methods.values():
            if isinstance(method, dict):
                method.setdefault("security", [{"BearerAuth": []}])
    integration_app.openapi_schema = schema
    return schema


integration_app.openapi = custom_openapi
