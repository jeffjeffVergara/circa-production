# Circa × ZOOM — Guía de integración (ambiente de **pruebas**)

**Versión:** 1.0 · **Fecha:** 7 sep 2026  
**Alcance actual:** solo **pruebas** (`/api/v1/test`). **No usar producción** hasta aviso de Circa.

Circa expone la API. ZOOM / BsSoft consume.

---

## 1. URLs (solo test)

| Recurso | URL |
|---------|-----|
| **Base API pruebas** | `https://circa-production-c517.up.railway.app/api/v1/test` |
| Auth (token) | `https://circa-production-c517.up.railway.app/api/v1/auth/token` |
| Swagger | https://circa-production-c517.up.railway.app/api/v1/docs |
| ReDoc | https://circa-production-c517.up.railway.app/api/v1/redoc |
| Landing | https://circa-production-c517.up.railway.app/static/integration.html |

> Todo lo que escriban bajo `/api/v1/test` queda con `es_test=true` (no afecta data real).  
> **No llamen** `/api/v1/...` (sin `/test`) en esta fase.

---

## 2. Credenciales de prueba (ZOOM CORP)

| Campo | Valor |
|-------|--------|
| `client_id` | `zoom-circa` |
| `client_secret` | `VDgiZdWPaEhqghHiyurUQZyQT2wqWYfSz5KTkyfLsWA` |
| Access token test (Bearer) | `woeVXt0ZdO4Dx9m4OuwC2oFYzLMgQzdD` |

También pueden obtener el Bearer así (recomendado al integrar):

```bash
curl -s -X POST "https://circa-production-c517.up.railway.app/api/v1/auth/token" \
  -H "Content-Type: application/json" \
  -d '{
    "grant_type": "client_credentials",
    "client_id": "zoom-circa",
    "client_secret": "VDgiZdWPaEhqghHiyurUQZyQT2wqWYfSz5KTkyfLsWA",
    "data_mode": "test"
  }'
```

Respuesta esperada:

```json
{
  "access_token": "woeVXt0ZdO4Dx9m4OuwC2oFYzLMgQzdD",
  "token_type": "Bearer",
  "data_mode": "test",
  "expires_in": null,
  "distribuidor": "ZOOM CORP"
}
```

`expires_in: null` = no caduca solo. Cachear el token; renovar ante 401.

Luego en cada request:

```http
Authorization: Bearer woeVXt0ZdO4Dx9m4OuwC2oFYzLMgQzdD
```

---

## 3. Catálogo (bajo `/api/v1/test`)

| ID | Método | Ruta | Notas |
|----|--------|------|--------|
| Auth | `POST` | `/api/v1/auth/token` | `data_mode: "test"` |
| SVC-00 | `GET` | `/health` | Sin token |
| SVC-01 | `GET` | `/bodegas?q=` | Ver `situacion` por item |
| SVC-01b | `GET` | `/bodegas/{id}` | Refresco |
| SVC-02 | `POST` | `/bodegas` | **multipart** + fotos |
| SVC-03 | `PATCH` | `/bodegas/{id}` | JSON |
| SVC-04 | `POST` | `/preventas` | `monto_a_financiar` + `plazo_dias` |
| SVC-05 | `GET` | `/preventas/{id}` · `/pedidos/{id}` | Polling |
| SVC-06 | `GET` | `/preventas` · `/pedidos` | Listar |
| SVC-07 | `PATCH` | `/pedidos/{id}/estado` | Despacho |

---

## 4. Flujo recomendado

```
Auth (data_mode=test)
  → SVC-01  mirar items[i].situacion
       ├─ no_registrada  → SVC-02 (datos + foto_dueno + foto_bodega) → guardar id
       ├─ en_evaluacion  → reconsultar SVC-01b
       ├─ no_disponible  → UI sin cupo
       └─ con_linea      → SVC-04 → SVC-05 → SVC-07
```

### `situacion` (por bodega)

| Valor | Acción |
|-------|--------|
| `no_registrada` | Precargar (SVC-02) |
| `en_evaluacion` | Esperar / reconsultar (no reenviar SVC-02) |
| `no_disponible` | Sin cupo |
| `con_linea` | Financiar (SVC-04) |

---

## 5. Datos de prueba (modo `/api/v1/test`)

Usar en **SVC-01** como query `q`. Todos pertenecen al distribuidor ZOOM CORP con `es_test=true`.

| `q` (sugerido) | `situacion` esperada | Notas |
|----------------|----------------------|--------|
| `00000000` | `no_registrada` | DNI inventado — no existe |
| `08608042` | `en_evaluacion` | Inactiva, sin cupo |
| `00141018` | `en_evaluacion` | Inactiva (también RUC `10991291415`) |
| `46843088` | `con_linea` | Activa, cupo ~500 |
| `73217300` | `con_linea` | Activa, cupo ~500 |
| `46097938` | `con_linea` | Activa, cupo ~100 |
| `06806355` | `con_linea` | Activa, cupo ~500 |
| `912114088` | (match por tel.) | Parcial de `+51912114088` → bodega en evaluación |
| `10991291415` | `en_evaluacion` | Búsqueda por RUC |

`q` también acepta razón social (parcial), p.ej. `JONATHAN TEST`.

> Si necesitan un caso **`no_disponible`** (activa sin cupo), avisar a Circa Ops para sembrar una bodega test con `linea_disponible=0`.

---

## 6. Ejemplos mínimos

### SVC-01 — consultar

```bash
export BASE="https://circa-production-c517.up.railway.app/api/v1/test"
export TOKEN="woeVXt0ZdO4Dx9m4OuwC2oFYzLMgQzdD"

# no_registrada
curl -s -H "Authorization: Bearer $TOKEN" \
  "$BASE/bodegas?q=00000000&limit=20"

# en_evaluacion
curl -s -H "Authorization: Bearer $TOKEN" \
  "$BASE/bodegas?q=08608042&limit=20"

# con_linea
curl -s -H "Authorization: Bearer $TOKEN" \
  "$BASE/bodegas?q=46843088&limit=20"
```

Ejemplo vacío:

```json
{ "total": 0, "items": [], "situacion": "no_registrada" }
```

### SVC-02 — precargar con fotos

```bash
curl -X POST "$BASE/bodegas" \
  -H "Authorization: Bearer $TOKEN" \
  -F "telefono_whatsapp=999000001" \
  -F "dni_representante=00000001" \
  -F "razon_social=BODEGA TEST ZOOM" \
  -F "solo_dni_sin_ruc=true" \
  -F "foto_dueno=@dueno.jpg;type=image/jpeg" \
  -F "foto_bodega=@bodega.jpg;type=image/jpeg"
```

Respuesta típica: `situacion=en_evaluacion`, `linea_disponible=0`, `tiene_foto_dueno/bodega=true`, `es_test=true`.

### SVC-04 — financiar (solo si `con_linea`)

```json
{
  "bodega_id": "<uuid Circa>",
  "monto_a_financiar": 31.0,
  "plazo_dias": 7,
  "vendedor_codigo": "ZOOM-TEST",
  "items": [
    {
      "sku": "T0001",
      "nombre": "Producto test",
      "cantidad": 2,
      "precio_unitario": 15.5
    }
  ]
}
```

`plazo_dias` solo: **7**, **15** o **30**.

---

## 7. Postman

1. Importar: `postman/Circa_Integration_API_v1.postman_collection.json`
2. Variables ya vienen con `client_id` / `client_secret` / `access_token_test` y DNIs de prueba (`q_dni_*`)
3. Usar solo la carpeta **02 · Pruebas**
4. Primero: **00 · Auth → Obtener token — pruebas** (o usar el Bearer ya cargado)

La carpeta **01 · Producción** está documentada pero **no debe usarse** en esta fase.

---

## 8. Swagger

Abrir https://circa-production-c517.up.railway.app/api/v1/docs  

1. Authorize → Bearer con el access token test  
2. Probar endpoints del tag **· test** (rutas `/api/v1/test/...`)

---

## 9. Documentación adicional

| Doc | Uso |
|-----|-----|
| [DOCUMENTO_SERVICIOS_CORE.md](./DOCUMENTO_SERVICIOS_CORE.md) | **Auth + SVC-01 + SVC-02 + SVC-04** (relación y contratos) |
| [README.md](./README.md) | Guía general API socios |
| [ANEXO_A_servicios_BsSoft.md](./ANEXO_A_servicios_BsSoft.md) | Contrato detallado SVC-00…07 |
| [CASOS_PRUEBA_SVC01.md](./CASOS_PRUEBA_SVC01.md) | Matriz QA de `situacion` + datos de prueba |

---

## 10. Soporte

contacto@circa.pe · +51 986 311 567  

Cuando Circa habilite producción, se entregarán credenciales/`data_mode=prod` por canal seguro (no reutilizar estas de test en prod).
