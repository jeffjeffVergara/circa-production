"""
Circa Integration API v1 — sub-aplicación FastAPI con Swagger/ReDoc propios.

URLs (un solo ambiente):
  Producción (datos reales):  https://<host>/api/v1/...
  Pruebas (es_test=true):     https://<host>/api/v1/test/...

  Swagger UI:  https://<host>/api/v1/docs
  ReDoc:       https://<host>/api/v1/redoc
  OpenAPI:     https://<host>/api/v1/openapi.json
"""
from __future__ import annotations

from typing import Annotated, Optional

from fastapi import APIRouter, Depends, FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.docs import get_redoc_html
from fastapi.responses import HTMLResponse

from app.integration.auth import get_current_distribuidor
from app.integration import schemas as S
from app.integration import service as svc
from app.services import prospect_media as media

DESCRIPTION = """
## API para socios

API de Circa para que **sistemas de socios distribuidores** se conecten sin
duplicar registros de clientes, preventas y pedidos.

### Modos de datos (mismo ambiente)

| Modo | Base URL | Datos | Token |
|------|----------|--------|--------|
| **Producción** | `/api/v1` | `es_test=false` | `api_token` (prod) |
| **Pruebas** | `/api/v1/test` | `es_test=true` | `api_token_test` |

Obtener access token:

```http
POST /api/v1/auth/token
Content-Type: application/json

{
  "grant_type": "client_credentials",
  "client_id": "<api_client_id>",
  "client_secret": "<api_client_secret>",
  "data_mode": "prod"
}
```

Luego: `Authorization: Bearer <access_token>`.
El token de prod **no** sirve en `/test` y viceversa.

### Autenticación
```
Authorization: Bearer <access_token>
```
Credenciales (`client_id` / `client_secret`) y tokens los emite Circa Ops por distribuidor.

### Principios
- **Upsert** de bodegas por `external_id`, WhatsApp, RUC o DNI/CE
- Precarga **no libera línea** (`linea_disponible = 0`)
- La activación KYC/PIN del dueño sigue en WhatsApp
- Use `external_id` del sistema del socio para idempotencia
- No mezclar IDs entre modos: una bodega de `/test` no existe en `/api/v1`

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

DistDep = Annotated[dict, Depends(get_current_distribuidor)]

_SWAGGER_CSS = "https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui.css"
_SWAGGER_JS = "https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui-bundle.js"


@integration_app.get("/docs", include_in_schema=False)
async def swagger_ui_html() -> HTMLResponse:
    openapi_url = "/api/v1/openapi.json"
    html = _DOCS_SHELL.format(
        title="Circa · API Socios",
        swagger_css=_SWAGGER_CSS,
        swagger_js=_SWAGGER_JS,
        openapi_url=openapi_url,
    )
    return HTMLResponse(html)


@integration_app.get("/redoc", include_in_schema=False)
async def redoc_html():
    return get_redoc_html(
        openapi_url="/api/v1/openapi.json",
        title="Circa · API Socios",
        redoc_js_url="https://cdn.jsdelivr.net/npm/redoc@2/bundles/redoc.standalone.js",
    )


_MAX_FOTO_BYTES = 8 * 1024 * 1024  # 8 MB
_ALLOWED_IMAGE_CT = frozenset({"image/jpeg", "image/jpg", "image/png", "image/webp"})


async def _read_foto(upload: UploadFile, *, campo: str) -> tuple[bytes, str]:
    ct = (upload.content_type or "image/jpeg").split(";")[0].strip().lower()
    if ct not in _ALLOWED_IMAGE_CT:
        raise HTTPException(
            status_code=400,
            detail=f"{campo} debe ser imagen JPEG/PNG/WebP (recibido: {ct or 'desconocido'})",
        )
    data = await upload.read()
    if not data:
        raise HTTPException(status_code=400, detail=f"{campo} está vacío")
    if len(data) > _MAX_FOTO_BYTES:
        raise HTTPException(status_code=400, detail=f"{campo} supera el máximo de 8 MB")
    return data, ct


def _register_business_routes(router: APIRouter, *, es_test: bool) -> None:
    """Registra el mismo catálogo de servicios bajo prod o /test."""
    modo = "test" if es_test else "prod"
    tag_suffix = " · test" if es_test else ""

    @router.get(
        "/health",
        response_model=S.HealthResponse,
        summary=f"Health check ({modo})",
        tags=[f"Meta{tag_suffix}"],
    )
    async def health():
        return S.HealthResponse(data_mode=modo)  # type: ignore[arg-type]

    @router.post(
        "/bodegas",
        response_model=S.BodegaResponse,
        summary=f"Precargar bodega con fotos ({modo})",
        tags=[f"Bodegas{tag_suffix}"],
    )
    async def upsert_bodega(
        dist: DistDep,
        telefono_whatsapp: str = Form(..., description="Celular PE 9 dígitos o +51…"),
        foto_dueno: UploadFile = File(..., description="Foto del dueño (JPEG/PNG/WebP, máx 8 MB)"),
        foto_bodega: UploadFile = File(..., description="Foto de la bodega/fachada (máx 8 MB)"),
        dni_representante: Optional[str] = Form(None),
        ruc: Optional[str] = Form(None),
        razon_social: Optional[str] = Form(None),
        nombre_comercial: Optional[str] = Form(None),
        representante_legal: Optional[str] = Form(None),
        direccion_fiscal: Optional[str] = Form(None),
        distrito: Optional[str] = Form(None),
        external_id: Optional[str] = Form(None),
        solo_dni_sin_ruc: bool = Form(True),
    ):
        """SVC-02 — multipart/form-data. Requiere foto_dueno + foto_bodega."""
        if not (dni_representante or "").strip() and not (ruc or "").strip():
            raise HTTPException(status_code=400, detail="Envíe dni_representante o ruc")

        body = {
            "telefono_whatsapp": telefono_whatsapp,
            "dni_representante": dni_representante,
            "ruc": ruc,
            "razon_social": razon_social,
            "nombre_comercial": nombre_comercial,
            "representante_legal": representante_legal,
            "direccion_fiscal": direccion_fiscal,
            "distrito": distrito,
            "external_id": external_id,
            "solo_dni_sin_ruc": solo_dni_sin_ruc,
        }

        dueno_bytes, dueno_ct = await _read_foto(foto_dueno, campo="foto_dueno")
        bodega_bytes, bodega_ct = await _read_foto(foto_bodega, campo="foto_bodega")

        tel = svc.normalizar_telefono(telefono_whatsapp)
        saved_dueno = media.persist_image_bytes(tel, dueno_bytes, "dueno", dueno_ct)
        if not saved_dueno:
            raise HTTPException(status_code=502, detail="No se pudo guardar foto_dueno")
        saved_bodega = media.persist_image_bytes(tel, bodega_bytes, "local", bodega_ct)
        if not saved_bodega:
            raise HTTPException(status_code=502, detail="No se pudo guardar foto_bodega")

        body["foto_dueno_url"] = saved_dueno["path"]
        body["foto_bodega_url"] = saved_bodega["path"]
        return svc.upsert_bodega(dist, body, es_test=es_test)

    @router.get(
        "/bodegas",
        response_model=S.ListResponse,
        summary=f"Listar / buscar bodegas ({modo})",
        tags=[f"Bodegas{tag_suffix}"],
    )
    async def list_bodegas(
        dist: DistDep,
        q: Optional[str] = Query(None, description="Busca en nombre, DNI, RUC, tel, external_id"),
        limit: int = Query(50, ge=1, le=200),
        offset: int = Query(0, ge=0),
    ):
        return svc.list_bodegas(dist, q=q, limit=limit, offset=offset, es_test=es_test)

    @router.get(
        "/bodegas/{bodega_id}",
        response_model=S.BodegaResponse,
        summary=f"Obtener bodega ({modo})",
        tags=[f"Bodegas{tag_suffix}"],
    )
    async def get_bodega(bodega_id: str, dist: DistDep):
        row = svc.find_bodega(dist["id"], bodega_id=bodega_id, es_test=es_test)
        if not row:
            raise HTTPException(status_code=404, detail="Bodega no encontrada")
        return svc._bodega_out(row)

    @router.patch(
        "/bodegas/{bodega_id}",
        response_model=S.BodegaResponse,
        summary=f"Modificar bodega ({modo})",
        tags=[f"Bodegas{tag_suffix}"],
    )
    async def patch_bodega(bodega_id: str, body: S.BodegaPatchRequest, dist: DistDep):
        return svc.patch_bodega(
            dist, bodega_id, body.model_dump(exclude_unset=True), es_test=es_test,
        )

    @router.post(
        "/preventas",
        response_model=S.PedidoResponse,
        summary=f"Crear preventa ({modo})",
        tags=[f"Preventas{tag_suffix}"],
    )
    async def create_preventa(body: S.PreventaCreateRequest, dist: DistDep):
        return svc.create_preventa(dist, body.model_dump(), es_test=es_test)

    @router.get(
        "/preventas",
        response_model=S.ListResponse,
        summary=f"Listar preventas ({modo})",
        tags=[f"Preventas{tag_suffix}"],
    )
    async def list_preventas(
        dist: DistDep,
        estado: Optional[str] = None,
        bodega_id: Optional[str] = None,
        limit: int = Query(50, ge=1, le=200),
        offset: int = Query(0, ge=0),
    ):
        return svc.list_pedidos(
            dist,
            estado=estado,
            tipo="preventa",
            bodega_id=bodega_id,
            limit=limit,
            offset=offset,
            es_test=es_test,
        )

    @router.get(
        "/preventas/{pedido_id}",
        response_model=S.PedidoResponse,
        summary=f"Obtener preventa ({modo})",
        tags=[f"Preventas{tag_suffix}"],
    )
    async def get_preventa(pedido_id: str, dist: DistDep):
        return svc.get_pedido(dist, pedido_id, es_test=es_test)

    @router.get(
        "/pedidos",
        response_model=S.ListResponse,
        summary=f"Listar pedidos ({modo})",
        tags=[f"Pedidos{tag_suffix}"],
    )
    async def list_pedidos(
        dist: DistDep,
        estado: Optional[str] = None,
        bodega_id: Optional[str] = None,
        limit: int = Query(50, ge=1, le=200),
        offset: int = Query(0, ge=0),
    ):
        return svc.list_pedidos(
            dist, estado=estado, bodega_id=bodega_id, limit=limit, offset=offset, es_test=es_test,
        )

    @router.get(
        "/pedidos/{pedido_id}",
        response_model=S.PedidoResponse,
        summary=f"Obtener pedido ({modo})",
        tags=[f"Pedidos{tag_suffix}"],
    )
    async def get_pedido(pedido_id: str, dist: DistDep):
        return svc.get_pedido(dist, pedido_id, es_test=es_test)

    @router.patch(
        "/pedidos/{pedido_id}/estado",
        response_model=S.PedidoResponse,
        summary=f"Cambiar estado ({modo})",
        tags=[f"Pedidos{tag_suffix}"],
    )
    async def patch_estado(pedido_id: str, body: S.PedidoEstadoPatch, dist: DistDep):
        return svc.patch_pedido_estado(
            dist, pedido_id, body.estado, body.comentario, es_test=es_test,
        )


router_prod = APIRouter()
router_test = APIRouter(prefix="/test")
_register_business_routes(router_prod, es_test=False)
_register_business_routes(router_test, es_test=True)
integration_app.include_router(router_prod)
integration_app.include_router(router_test)


@integration_app.post(
    "/auth/token",
    response_model=S.TokenResponse,
    summary="Obtener access token (client_credentials)",
    tags=["Auth"],
)
async def auth_token(body: S.TokenRequest):
    """Intercambia client_id + client_secret por el Bearer del modo pedido.

    - `data_mode=prod` → token para `/api/v1/...`
    - `data_mode=test` → token para `/api/v1/test/...`
    """
    from app.integration.auth import issue_access_token

    return issue_access_token(
        client_id=body.client_id,
        client_secret=body.client_secret,
        data_mode=body.data_mode,
    )


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
    schema["servers"] = [
        {
            "url": "/api/v1",
            "description": "Producción — datos reales (es_test=false)",
        },
        {
            "url": "/api/v1/test",
            "description": "Pruebas — datos es_test=true (mismo ambiente)",
        },
    ]
    # Evitar duplicar /test en paths cuando el server ya es /api/v1/test:
    # Swagger lista ambos sets de paths; el server selector cambia la base.
    integration_app.openapi_schema = schema
    return schema


integration_app.openapi = custom_openapi
