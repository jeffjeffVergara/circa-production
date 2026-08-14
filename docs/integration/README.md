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

```http
Authorization: Bearer <api_token>
```

El token lo genera / entrega Circa Ops por distribuidor. No compartir tokens del portal HTML con terceros.

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
