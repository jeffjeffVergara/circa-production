# Circa × ZOOM — Documentación de servicios core

**Auth → SVC-01 → SVC-02 → SVC-04**

| Campo | Valor |
|-------|--------|
| Versión | 1.0 |
| Fecha | 7 sep 2026 |
| Ambiente | **Solo pruebas** (`/api/v1/test`) |
| Audiencia | Equipo ZOOM / BsSoft |

Este documento describe la **relación entre** la generación del token de seguridad y los tres servicios principales del botón Circa: consulta (SVC-01), precarga (SVC-02) y financiamiento (SVC-04).

---

## 1. Visión del flujo

```
┌─────────────────────────────────────────────────────────────┐
│  1. AUTH                                                     │
│  POST /api/v1/auth/token   (data_mode=test)                 │
│  → access_token (Bearer)                                     │
└───────────────────────────┬─────────────────────────────────┘
                            │ Authorization: Bearer …
                            ▼
┌─────────────────────────────────────────────────────────────┐
│  2. SVC-01  Consultar bodega                                 │
│  GET /api/v1/test/bodegas?q={dni|ruc|tel|nombre}            │
│  → leer items[i].situacion                                   │
└───────────────────────────┬─────────────────────────────────┘
          ┌─────────────────┼─────────────────┬────────────────┐
          ▼                 ▼                 ▼                ▼
   no_registrada     en_evaluacion     no_disponible      con_linea
          │                 │                 │                │
          ▼                 ▼                 ▼                ▼
   ┌─────────────┐   Reconsultar      UI “Sin cupo”    ┌─────────────┐
   │   SVC-02    │   SVC-01b                           │   SVC-04    │
   │  Precargar  │   (esperar)                         │  Financiar  │
   │  + fotos    │                                     │ monto+plazo │
   └──────┬──────┘                                     └──────┬──────┘
          │                                                   │
          │  guardar circa_bodega_id                          │  guardar circa_pedido_id
          ▼                                                   ▼
   situacion =                                        POST /preventas
   en_evaluacion                                      → SVC-05 poll (opcional)
```

**Regla de oro:** siempre mirar `situacion` de la **bodega elegida** (`items[i]`), no solo la raíz del listado.

---

## 2. Ambiente y URLs

| Recurso | URL |
|---------|-----|
| Auth | `https://circa-production-c517.up.railway.app/api/v1/auth/token` |
| Base servicios (test) | `https://circa-production-c517.up.railway.app/api/v1/test` |
| Swagger | https://circa-production-c517.up.railway.app/api/v1/docs |
| Postman | Carpeta **02 · Pruebas** |

> **No usar** `/api/v1/...` (sin `/test`) hasta que Circa habilite producción.

---

## 3. Auth — generación del token de seguridad

### 3.1 Para qué sirve

Obtiene un **access token Bearer** ligado al distribuidor ZOOM y al modo de datos (`test` o `prod`).  
Todas las llamadas a SVC-01 / 02 / 04 (y el resto) llevan ese Bearer.

### 3.2 Credenciales de prueba (ZOOM CORP)

| Campo | Valor |
|-------|--------|
| `client_id` | `zoom-circa` |
| `client_secret` | `VDgiZdWPaEhqghHiyurUQZyQT2wqWYfSz5KTkyfLsWA` |
| Bearer test (ya emitido) | `woeVXt0ZdO4Dx9m4OuwC2oFYzLMgQzdD` |

### 3.3 Request

```http
POST /api/v1/auth/token
Content-Type: application/json

{
  "grant_type": "client_credentials",
  "client_id": "zoom-circa",
  "client_secret": "VDgiZdWPaEhqghHiyurUQZyQT2wqWYfSz5KTkyfLsWA",
  "data_mode": "test"
}
```

### 3.4 Response

```json
{
  "access_token": "woeVXt0ZdO4Dx9m4OuwC2oFYzLMgQzdD",
  "token_type": "Bearer",
  "data_mode": "test",
  "expires_in": null,
  "distribuidor_id": "d1a2b3c4-0001-4000-8000-000000000002",
  "distribuidor": "ZOOM CORP"
}
```

| Campo | Significado |
|-------|-------------|
| `access_token` | Valor del header `Authorization: Bearer …` |
| `data_mode` | Debe ser `test` para llamar `/api/v1/test/...` |
| `expires_in` | `null` = no caduca solo; renovar ante **401** o rotación Ops |

### 3.5 Uso en los demás servicios

```http
Authorization: Bearer woeVXt0ZdO4Dx9m4OuwC2oFYzLMgQzdD
```

Modelo recomendado para la app del socio:

1. Al arrancar (o la primera vez): llamar Auth y cachear el token.  
2. Usar el mismo Bearer en SVC-01 / 02 / 04.  
3. Si llega **401**: volver a Auth y reintentar.  
4. No hace falta pedir token en cada request.

Relación con el resto:

| Si Auth… | Efecto |
|----------|--------|
| OK + `data_mode=test` | Puede llamar `/api/v1/test/...` |
| Token de prod en URL test | **403** |
| Token inválido / ausente | **401** en SVC-01/02/04 |

---

## 4. SVC-01 — Consultar afiliación y línea

### 4.1 Rol en el flujo

Es el **primer servicio de negocio** después del token. Decide qué pantalla/acción mostrar según `situacion`.

### 4.2 Request

```http
GET /api/v1/test/bodegas?q={dato}&limit=20
Authorization: Bearer <access_token>
```

`q` busca (parcial) en: DNI/CE, RUC, teléfono, razón social, nombre comercial, `external_id`.

### 4.3 Response (forma)

```json
{
  "total": 1,
  "situacion": "con_linea",
  "items": [
    {
      "id": "…-uuid-circa-…",
      "dni_representante": "46843088",
      "telefono_whatsapp": "+51942616682",
      "razon_social": "…",
      "estado": "activo",
      "linea_aprobada": 500.0,
      "linea_disponible": 500.0,
      "situacion": "con_linea",
      "tiene_foto_dueno": false,
      "tiene_foto_bodega": false,
      "es_test": true,
      "created": false
    }
  ]
}
```

- `situacion` en la **raíz** = atajo del primer item (o `no_registrada` si `total=0`).  
- Decidir siempre con `items[i].situacion` de la bodega del pedido.  
- Persistir `items[i].id` como `circa_bodega_id`.

### 4.4 Valores de `situacion` y siguiente paso

| `situacion` | Condición típica | Siguiente servicio |
|-------------|------------------|--------------------|
| `no_registrada` | `total=0` | **SVC-02** precargar |
| `en_evaluacion` | Existe, `estado ≠ activo` | Esperar → **SVC-01b** (no SVC-02) |
| `no_disponible` | `activo` y `linea_disponible ≤ 0` | Solo UI “sin cupo” |
| `con_linea` | `activo` y `linea_disponible > 0` | **SVC-04** financiar |

### 4.5 Datos de prueba (`q`)

| `q` | `situacion` esperada |
|-----|----------------------|
| `00000000` | `no_registrada` |
| `08608042` | `en_evaluacion` |
| `46843088` | `con_linea` |
| `73217300` | `con_linea` |
| `46097938` | `con_linea` |
| `10991291415` | `en_evaluacion` (RUC) |

### 4.6 Relación con Auth y con SVC-02 / 04

```
Auth OK
  → SVC-01(q)
       ├─ no_registrada  ──necesita──► SVC-02  ──luego──► SVC-01b (hasta con_linea)
       ├─ en_evaluacion  ──no llama──► SVC-02 ni SVC-04
       ├─ no_disponible  ──no llama──► SVC-04
       └─ con_linea      ──necesita──► SVC-04 (usa bodega_id de SVC-01)
```

### 4.7 SVC-01b (refresco)

Si ya tienen `circa_bodega_id`:

```http
GET /api/v1/test/bodegas/{circa_bodega_id}
Authorization: Bearer <access_token>
```

Misma forma de bodega + `situacion`. Útil tras SVC-02 mientras Circa evalúa.

---

## 5. SVC-02 — Precargar bodega (con fotos)

### 5.1 Rol en el flujo

Se invoca **solo** cuando SVC-01 devolvió `no_registrada` (o hay que enviar datos nuevos a Circa).  
No activa la línea: deja la bodega en evaluación.

### 5.2 Request

`Content-Type: multipart/form-data`

```http
POST /api/v1/test/bodegas
Authorization: Bearer <access_token>
```

| Campo | Obl. | Nota |
|-------|------|------|
| `telefono_whatsapp` | **Sí** | 9 dígitos o `+51…` |
| `dni_representante` **o** `ruc` | **Sí** | Al menos uno |
| `foto_dueno` | **Sí** | Archivo JPEG/PNG/WebP ≤ 8 MB |
| `foto_bodega` | **Sí** | Idem |
| `razon_social` | Recomendado | |
| `direccion_fiscal`, `distrito`, … | Opcionales | |
| `solo_dni_sin_ruc` | No | Default `true` si no hay RUC |
| `external_id` | No | Opcional del socio |

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

### 5.3 Response

```json
{
  "id": "…-uuid-circa-…",
  "telefono_whatsapp": "+51999000001",
  "dni_representante": "00000001",
  "razon_social": "BODEGA TEST ZOOM",
  "estado": "inactivo",
  "onboarding_fase": "precargada",
  "linea_disponible": 0.0,
  "situacion": "en_evaluacion",
  "tiene_foto_dueno": true,
  "tiene_foto_bodega": true,
  "es_test": true,
  "created": true
}
```

| Campo | Qué hacer |
|-------|-----------|
| `id` | Guardar como `circa_bodega_id` |
| `situacion` | Queda `en_evaluacion` |
| `linea_disponible` | `0` — **aún no se puede financiar** |

### 5.4 Relación con Auth y SVC-01 / 04

| Antes | Después |
|-------|---------|
| Auth debe haber dado Bearer test | Sin token → 401 |
| SVC-01 dijo `no_registrada` | Motivo típico para llamar SVC-02 |
| Tras SVC-02 | **No** llamar SVC-04 todavía |
| Siguiente | SVC-01b hasta `con_linea` (o `no_disponible`) |

```
SVC-01 (no_registrada)
  → SVC-02 (fotos + datos)
  → guardar id
  → [Circa evalúa]
  → SVC-01b / SVC-01
  → si con_linea → SVC-04
```

---

## 6. SVC-04 — Solicitar financiamiento

### 6.1 Rol en el flujo

Se invoca **solo** cuando SVC-01/01b devolvió `situacion=con_linea`.  
Crea la preventa/solicitud con monto y plazo.

### 6.2 Request

```http
POST /api/v1/test/preventas
Authorization: Bearer <access_token>
Content-Type: application/json
```

| Campo | Obl. | Nota |
|-------|------|------|
| `bodega_id` | **Sí*** | UUID de SVC-01 / SVC-02 (`circa_bodega_id`) |
| `items[]` | **Sí** | ≥ 1 línea |
| `items[].nombre` | **Sí** | |
| `items[].cantidad` | **Sí** | > 0 |
| `items[].precio_unitario` | **Sí** | ≥ 0 |
| `monto_a_financiar` | **Sí** | > 0; ≤ total ítems y ≤ `linea_disponible` |
| `plazo_dias` | **Sí** | Solo **7**, **15** o **30** |
| `external_id` | Recomendado | Nº preventa en el sistema del socio |
| `vendedor_codigo` | Recomendado | |
| `notas` | No | |

\* Alternativas a `bodega_id`: `bodega_external_id` o `telefono_whatsapp` (preferir UUID Circa).

```json
{
  "external_id": "PV-TEST-001",
  "bodega_id": "<circa_bodega_id de SVC-01>",
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

### 6.3 Response

```json
{
  "id": "…-uuid-pedido-…",
  "external_id": "PV-TEST-001",
  "bodega_id": "…",
  "estado": "preventa_confirmada",
  "total_pedido": 31.0,
  "monto_financiado": 31.0,
  "plazo_dias": 7
}
```

Persistir `id` como `circa_pedido_id`. Luego opcional: **SVC-05** para polling de estado.

### 6.4 Errores frecuentes

| HTTP | Causa |
|------|--------|
| 401 | Falta / token inválido (volver a Auth) |
| 400 | Falta `monto_a_financiar` / `plazo_dias` inválido / monto > total |
| 409 | Bodega sin línea (`situacion` no es `con_linea`) o monto > `linea_disponible` |
| 404 | `bodega_id` no existe en modo test |

### 6.5 Relación con Auth y SVC-01 / 02

```
Auth
  → SVC-01  (debe ser con_linea; si vino de SVC-02, ya pasó por evaluación)
  → SVC-04  (bodega_id + monto_a_financiar + plazo_dias + items)
  → [opcional] SVC-05 GET /preventas/{id}
```

**No** se llama SVC-04 directamente tras SVC-02: falta que Circa deje la bodega en `con_linea`.

---

## 7. Secuencia completa (resumen)

### Caso A — Cliente nuevo

| Paso | Servicio | Resultado |
|------|----------|-----------|
| 1 | Auth | Bearer test |
| 2 | SVC-01 `q=DNI` | `no_registrada` |
| 3 | SVC-02 + fotos | `id`, `en_evaluacion` |
| 4 | SVC-01b (después) | Esperar `con_linea` |
| 5 | SVC-04 | Solo cuando haya línea |

### Caso B — Cliente con línea

| Paso | Servicio | Resultado |
|------|----------|-----------|
| 1 | Auth | Bearer test |
| 2 | SVC-01 `q=46843088` | `con_linea` + `id` |
| 3 | SVC-04 | Preventa con monto y plazo |

### Caso C — Ya precargado

| Paso | Servicio | Resultado |
|------|----------|-----------|
| 1 | Auth | Bearer |
| 2 | SVC-01 / 01b | `en_evaluacion` |
| 3 | — | **No** SVC-02 ni SVC-04; reconsultar |

---

## 8. Identificadores a guardar

| Campo en el socio | Origen |
|-------------------|--------|
| Bearer / access_token | Auth |
| `circa_bodega_id` | `id` de SVC-01 o SVC-02 |
| `circa_pedido_id` | `id` de SVC-04 |

---

## 9. Catálogo completo (referencia)

| ID | Método | Ruta (bajo `/api/v1/test`) | Rol |
|----|--------|----------------------------|-----|
| Auth | `POST` | `/api/v1/auth/token` | Token |
| SVC-00 | `GET` | `/health` | Salud |
| **SVC-01** | `GET` | `/bodegas?q=` | Consulta + `situacion` |
| **SVC-01b** | `GET` | `/bodegas/{id}` | Refresco |
| **SVC-02** | `POST` | `/bodegas` | Precarga + fotos |
| SVC-03 | `PATCH` | `/bodegas/{id}` | Corregir datos |
| **SVC-04** | `POST` | `/preventas` | Financiar |
| SVC-05 | `GET` | `/preventas/{id}` | Resultado |
| SVC-06 | `GET` | `/preventas` · `/pedidos` | Listar |
| SVC-07 | `PATCH` | `/pedidos/{id}/estado` | Despacho |

---

## 10. Documentos relacionados

| Doc | Contenido |
|-----|-----------|
| [GUIA_ZOOM_PRUEBAS.md](./GUIA_ZOOM_PRUEBAS.md) | Credenciales + datos de prueba + quick start |
| [ANEXO_A_servicios_BsSoft.md](./ANEXO_A_servicios_BsSoft.md) | Contrato detallado de todos los SVC |
| [CASOS_PRUEBA_SVC01.md](./CASOS_PRUEBA_SVC01.md) | Matriz QA de `situacion` |
| [README.md](./README.md) | Índice general |
| Postman | `postman/Circa_Integration_API_v1.postman_collection.json` · **02 · Pruebas** |
| Swagger | https://circa-production-c517.up.railway.app/api/v1/docs |

---

## 11. Soporte

contacto@circa.pe · +51 986 311 567
