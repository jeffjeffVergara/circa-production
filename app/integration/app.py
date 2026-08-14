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
from fastapi.openapi.docs import get_redoc_html
from fastapi.responses import HTMLResponse

from app.integration.auth import get_current_distribuidor
from app.integration import schemas as S
from app.integration import service as svc

DESCRIPTION = """
## API para socios

API de Circa para que **sistemas de socios distribuidores** se conecten sin
duplicar registros de clientes, preventas y pedidos.

### Autenticación
```
Authorization: Bearer <api_token>
```
El `api_token` lo emite Circa por distribuidor (`distribuidores.api_token`).

### Principios
- **Upsert** de bodegas por `external_id`, WhatsApp, RUC o DNI/CE
- Precarga **no libera línea** (`linea_disponible = 0`)
- La activación KYC/PIN del dueño sigue en WhatsApp
- Use `external_id` del sistema del socio para idempotencia

### Soporte
contacto@circa.pe · +51 986 311 567
"""

_DOCS_SHELL = """<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  <link rel="stylesheet" type="text/css" href="{swagger_css}">
  <link rel="stylesheet" type="text/css" href="/static/integration-swagger.css">
  <link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'%3E%3Crect width='64' height='64' rx='14' fill='%230a1628'/%3E%3Ctext x='50%25' y='54%25' text-anchor='middle' font-family='Arial' font-size='28' font-weight='700' fill='%2300c2ff'%3EC%3C/text%3E%3C/svg%3E">
  <style>html{{box-sizing:border-box}}*,*::before,*::after{{box-sizing:inherit}}</style>
</head>
<body>
  <header class="circa-docs-top">
    <a class="circa-docs-brand" href="/static/integration.html">
      <span class="mark">Circa</span>
      <span class="sub">API Socios · v1</span>
    </a>
    <nav class="circa-docs-nav">
      <a href="/api/v1/docs" class="primary">Swagger</a>
      <a href="/api/v1/redoc">ReDoc</a>
      <a href="/api/v1/openapi.json">OpenAPI</a>
      <a href="/static/integration.html">Inicio</a>
    </nav>
  </header>
  <div id="swagger-ui"></div>
  <script src="{swagger_js}"></script>
  <script>
    window.ui = SwaggerUIBundle({{
      url: "{openapi_url}",
      dom_id: "#swagger-ui",
      presets: [SwaggerUIBundle.presets.apis, SwaggerUIBundle.SwaggerUIStandalonePreset],
      layout: "BaseLayout",
      deepLinking: true,
      persistAuthorization: true,
      displayRequestDuration: true,
      tryItOutEnabled: true,
      filter: true,
      defaultModelsExpandDepth: 1
    }});
  </script>
</body>
</html>
"""

integration_app = FastAPI(
    title="Circa · API Socios",
    version="1.0.0",
    description=DESCRIPTION,
    docs_url=None,
    redoc_url=None,
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

_SWAGGER_CSS = "https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui.css"
_SWAGGER_JS = "https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui-bundle.js"


@integration_app.get("/docs", include_in_schema=False)
async def swagger_ui_html() -> HTMLResponse:
    # Ruta absoluta para que el browser resuelva bien bajo /api/v1
    openapi_url = "/api/v1/openapi.json"
    html = _DOCS_SHELL.format(
        title="Circa · API Socios",
        swagger_css=_SWAGGER_CSS,
        swagger_js=_SWAGGER_JS,
        openapi_url=openapi_url,
    )
    return HTMLResponse(html)


@integration_app.get("/redoc", include_in_schema=False)
async def redoc_html() -> HTMLResponse:
    return get_redoc_html(
        openapi_url="/api/v1/openapi.json",
        title="Circa · API Socios",
        redoc_js_url="https://cdn.jsdelivr.net/npm/redoc@2/bundles/redoc.standalone.js",
    )


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
            "description": "Token del socio distribuidor (distribuidores.api_token)",
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
