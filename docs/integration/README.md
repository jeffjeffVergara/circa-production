# Circa · API Socios v1

API pública para que **sistemas de socios distribuidores** se integren a Circa sin duplicar altas de clientes, preventas y pedidos.

Circa **expone** la API. El socio **consume** la API.

## Documentación interactiva (Swagger / OpenAPI)

| Recurso | URL (producción) |
|---------|------------------|
| **Swagger UI** | https://circa-production-c517.up.railway.app/api/v1/docs |
| **ReDoc** | https://circa-production-c517.up.railway.app/api/v1/redoc |
| **OpenAPI JSON** | https://circa-production-c517.up.railway.app/api/v1/openapi.json |
| Landing | https://circa-production-c517.up.railway.app/static/integration.html |

Local: `http://localhost:8000/api/v1/docs`

## Postman

Importar la colección:

[`postman/Circa_Integration_API_v1.postman_collection.json`](../../postman/Circa_Integration_API_v1.postman_collection.json)

Variables:

- `baseUrl` → `https://circa-production-c517.up.railway.app/api/v1`
- `api_token` → token del distribuidor (`distribuidores.api_token`)

## Autenticación

### 1) Obtener access token

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

Respuesta:

```json
{
  "access_token": "...",
  "token_type": "Bearer",
  "data_mode": "prod",
  "expires_in": null,
  "distribuidor_id": "...",
  "distribuidor": "ZOOM CORP"
}
```

Usa `data_mode: "test"` para el token de pruebas.

### 2) Llamar APIs

```http
Authorization: Bearer <access_token>
```

| Modo | Base URL | Token |
|------|----------|--------|
| **Producción** | `…/api/v1` | token con `data_mode=prod` |
| **Pruebas** | `…/api/v1/test` | token con `data_mode=test` |

El token de prod **no** funciona en `/test` (403) y viceversa.

Credenciales (`api_client_id`, `api_client_secret`, `api_token`, `api_token_test`) las configura Circa Ops en `distribuidores`.

## Alcance MVP

| Recurso | Métodos |
|---------|---------|
| Bodegas (enrolamiento) | `POST` upsert, `GET` list/detail, `PATCH` |
| Preventas | `POST` create, `GET` list/detail |
| Pedidos | `GET` list/detail, `PATCH .../estado` |

### Reglas de negocio importantes

1. `POST /bodegas` **no libera línea** (`linea_disponible = 0`).
2. Use `external_id` del sistema del socio para no duplicar.
3. Activación del dueño (selfie / PIN) sigue en WhatsApp Circa.
4. Preventa requiere bodega existente (crear primero con upsert).

## Ejemplo rápido

```bash
export TOKEN="..."
export BASE="https://circa-production-c517.up.railway.app/api/v1"

curl -s "$BASE/health"

curl -s -X POST "$BASE/bodegas" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "external_id": "SOCIO-001",
    "telefono_whatsapp": "987654321",
    "dni_representante": "42868000",
    "razon_social": "BODEGA DEMO",
    "solo_dni_sin_ruc": true
  }'
```

## Migración DB

Ejecutar en Supabase:

`migrations/20260814_integration_external_ids.sql`

(añade `external_id` en `bodegas` y `pedidos`).

## Roadmap

- Webhooks (`bodega.activa`, `pedido.estado_cambiado`, `pago.confirmado`)
- Invite WhatsApp desde API
- Catálogo / mapeo SKU socio↔Circa
- Rate limiting por token
