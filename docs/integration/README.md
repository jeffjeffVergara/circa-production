# Circa · API Socios v1

API pública para que **sistemas de socios distribuidores** (BsSoft / ZOOM u otros) se integren a Circa.

Circa **expone** la API. El socio **consume** la API.

| Documento | Contenido |
|-----------|-----------|
| Este README | Guía rápida + contratos actuales |
| [ANEXO_A_servicios_BsSoft.md](./ANEXO_A_servicios_BsSoft.md) | Catálogo detallado SVC-00…07 |
| [CASOS_PRUEBA_SVC01.md](./CASOS_PRUEBA_SVC01.md) | Matriz QA de `situacion` |
| Postman | [`postman/Circa_Integration_API_v1.postman_collection.json`](../../postman/Circa_Integration_API_v1.postman_collection.json) |

---

## Documentación interactiva

| Recurso | URL |
|---------|-----|
| **Swagger UI** | https://circa-production-c517.up.railway.app/api/v1/docs |
| **ReDoc** | https://circa-production-c517.up.railway.app/api/v1/redoc |
| **OpenAPI JSON** | https://circa-production-c517.up.railway.app/api/v1/openapi.json |
| Landing | https://circa-production-c517.up.railway.app/static/integration.html |

Local: `http://localhost:8000/api/v1/docs`

---

## Modos prod / test (un solo ambiente)

| Modo | Base URL | Datos | Token |
|------|----------|--------|--------|
| **Producción** | `…/api/v1` | `es_test=false` | `data_mode=prod` |
| **Pruebas** | `…/api/v1/test` | `es_test=true` | `data_mode=test` |

El token de prod **no** funciona en `/test` (403) y viceversa.

---

## Autenticación

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

Luego en cada request (salvo `/health` y `/auth/token`):

```http
Authorization: Bearer <access_token>
```

`expires_in: null` = token de larga duración. Cachearlo; renovar solo ante 401 o rotación Ops.

Credenciales las configura Circa Ops en `distribuidores` (`api_client_id`, `api_client_secret`, `api_token`, `api_token_test`).

---

## Catálogo de servicios

| ID | Método | Ruta | Notas |
|----|--------|------|--------|
| Auth | `POST` | `/auth/token` | Client credentials |
| **SVC-00** | `GET` | `/health` | Sin token |
| **SVC-01** | `GET` | `/bodegas?q=` | Buscar; campo **`situacion`** por item |
| **SVC-01b** | `GET` | `/bodegas/{id}` | Refresco de una bodega |
| **SVC-02** | `POST` | `/bodegas` | Precarga **multipart** + fotos |
| **SVC-03** | `PATCH` | `/bodegas/{id}` | Corregir datos (JSON) |
| **SVC-04** | `POST` | `/preventas` | Financiar: **`monto_a_financiar`** + **`plazo_dias`** |
| **SVC-05** | `GET` | `/preventas/{id}` · `/pedidos/{id}` | Resultado / polling |
| **SVC-06** | `GET` | `/preventas` · `/pedidos` | Listar |
| **SVC-07** | `PATCH` | `/pedidos/{id}/estado` | Despacho / entrega |

---

## Flujo del socio

```
Auth → token
  → SVC-01 / 01b  (mirar items[i].situacion)
       ├─ no_registrada  → SVC-02 (datos + foto_dueno + foto_bodega) → guardar id
       ├─ en_evaluacion  → esperar / reconsultar SVC-01b (no reenviar SVC-02)
       ├─ no_disponible  → UI sin cupo
       └─ con_linea      → SVC-04 (monto + plazo + items)
                              → SVC-05 (poll)
                              → SVC-07 (recibido → en_camino → entregado)
```

### Campo `situacion` (por **bodega**)

| Valor | Significado | Acción |
|-------|-------------|--------|
| `no_registrada` | No hay match (`total=0`) | Precargar → SVC-02 |
| `en_evaluacion` | Data ya enviada; aún no activa / sin cupo usable | Reconsultar; **no** SVC-02 |
| `no_disponible` | Activa con `linea_disponible ≤ 0` | Sin cupo |
| `con_linea` | Activa con cupo > 0 | Financiar → SVC-04 |

Decidir siempre con `items[i].situacion`. La `situacion` de la raíz del listado es solo atajo del **primer** item.

---

## SVC-02 — Precargar (con fotos)

`POST /bodegas` · **`multipart/form-data`**

| Campo | Obl. |
|-------|------|
| `telefono_whatsapp` | Sí |
| `dni_representante` **o** `ruc` | Sí (uno) |
| `foto_dueno` | **Sí** (JPEG/PNG/WebP ≤ 8 MB) |
| `foto_bodega` | **Sí** |
| `razon_social`, dirección, etc. | Recomendados |
| `external_id` | No (opcional del socio) |

Respuesta típica: `id` Circa, `situacion=en_evaluacion`, `linea_disponible=0`, `tiene_foto_dueno/bodega=true`.

```bash
curl -X POST "$BASE/bodegas" \
  -H "Authorization: Bearer $TOKEN" \
  -F "telefono_whatsapp=987654321" \
  -F "dni_representante=07631909" \
  -F "razon_social=BODEGA EJEMPLO" \
  -F "solo_dni_sin_ruc=true" \
  -F "foto_dueno=@dueno.jpg;type=image/jpeg" \
  -F "foto_bodega=@bodega.jpg;type=image/jpeg"
```

---

## SVC-04 — Solicitar financiamiento

`POST /preventas` · JSON · requiere `situacion=con_linea`

| Campo | Obl. |
|-------|------|
| `bodega_id` (o `bodega_external_id` / `telefono_whatsapp`) | Sí* |
| `items[]` | Sí |
| `monto_a_financiar` | **Sí** (> 0; ≤ total ítems y ≤ `linea_disponible`) |
| `plazo_dias` | **Sí** (`7`, `15` o `30`) |
| `external_id`, `vendedor_codigo`, `notas` | Opcionales |

```json
{
  "external_id": "PV-2026-000451",
  "bodega_id": "<uuid Circa>",
  "monto_a_financiar": 31.0,
  "plazo_dias": 7,
  "vendedor_codigo": "V-014",
  "items": [
    {
      "sku": "CAF-SEL-200",
      "nombre": "CAFETAL SELECTO 24x200g",
      "cantidad": 3,
      "precio_unitario": 10.30
    }
  ]
}
```

Respuesta: `id`, `estado=preventa_confirmada`, `total_pedido`, `monto_financiado`, `plazo_dias`.

---

## Identificadores a persistir

| Campo socio | Origen Circa |
|-------------|--------------|
| `circa_bodega_id` | `id` de bodega (SVC-02 / 01) |
| `circa_pedido_id` | `id` de preventa (SVC-04) |
| `circa_pedido_numero` | `numero` (si viene) |

El `id` de bodega lo **genera Circa**. `external_id` del socio es opcional (idempotencia).

---

## Postman

Importar:

[`postman/Circa_Integration_API_v1.postman_collection.json`](../../postman/Circa_Integration_API_v1.postman_collection.json)

Variables: `client_id`, `client_secret`, `baseUrl`, `baseUrlTest`.  
Carpetas: **00 · Auth**, **01 · Producción**, **02 · Pruebas** (con Examples de `situacion` y SVC-02/04).

---

## Migraciones DB relacionadas

| Archivo | Qué agrega |
|---------|------------|
| `migrations/20260814_integration_external_ids.sql` | `external_id` bodegas/pedidos |
| `migrations/20260903_distribuidores_api_tokens_dual.sql` | tokens duales + client credentials |
| `migrations/20260904_bodegas_fotos_precarga.sql` | `foto_dueno_url`, `foto_bodega_url` |

---

## Roadmap

- Webhooks (`bodega.activa`, `pedido.estado_cambiado`, `pago.confirmado`) — WHK-01
- `fecha_entrega_prevista` / prueba de entrega en SVC-07
- Rate limiting por token
- Catálogo / mapeo SKU socio ↔ Circa

## Soporte

contacto@circa.pe · +51 986 311 567
