# Anexo A — Catálogo de servicios Circa ↔ BsSoft

**Documento técnico · anexo al Requerimiento v1.0**

| Campo | Detalle |
|-------|---------|
| Versión | v1.1 |
| Fecha | 5 de septiembre de 2026 |
| Emite | Circa (Pali S.A.C., RUC 20600627806) |
| Dirigido a | BsSoft — equipo de producto y desarrollo |
| Con copia a | ZOOM |
| Relacionado | *Circa_Requerimiento_Tecnico_BsSoft_v1* (11 ago 2026) |
| Cambios v1.1 | Campo `situacion`; SVC-02 multipart con fotos; SVC-04 `monto_a_financiar` + `plazo_dias` |

Este anexo cierra el **punto abierto 1** (protocolo) y el **punto abierto 2** (notificación de resultados) del requerimiento: Circa **expone** una API REST; BsSoft **consume**. BsSoft no necesita publicar servicios propios en la primera entrega.

---

## 1. Cómo leer este anexo

El requerimiento describe cuatro cosas que Circa necesita. Aquí se traduce cada una a un servicio concreto, con método, URL, cuándo llamarlo y el contrato de datos.

| # | Del requerimiento | Cómo se cubre |
|---|-------------------|---------------|
| 1 | Historial de compras | **Archivo** (CSV/Excel). No es un servicio en línea. |
| 2 | Preventas en línea | `POST /preventas` + consulta de estado |
| 3 | Estados de despacho y entrega | `PATCH /pedidos/{id}/estado` |
| 4 | Botón Circa | BsSoft construye el componente; llama a los servicios de este anexo |

**Disponible hoy** = ya está en producción. **En siguiente entrega** = Circa lo publica antes de que el botón entre a piloto combinado.

---

## 2. Acceso

| Dato | Valor |
|------|--------|
| Base URL producción (datos reales) | `https://circa-production-c517.up.railway.app/api/v1` |
| Base URL pruebas (`es_test`) | `https://circa-production-c517.up.railway.app/api/v1/test` |
| Swagger | `https://circa-production-c517.up.railway.app/api/v1/docs` |
| ReDoc | `https://circa-production-c517.up.railway.app/api/v1/redoc` |
| OpenAPI JSON | `https://circa-production-c517.up.railway.app/api/v1/openapi.json` |
| Landing | `https://circa-production-c517.up.railway.app/static/integration.html` |
| Autenticación | `POST /auth/token` → `Authorization: Bearer <access_token>` |
| Token | Circa Ops configura `api_client_id`, `api_client_secret`, `api_token` (prod) y `api_token_test` |

El token viaja en cada request salvo `GET /health` y `POST /auth/token`. No compartir tokens del portal HTML de Circa.

```http
POST /api/v1/auth/token
Content-Type: application/json

{ "grant_type": "client_credentials", "client_id": "...", "client_secret": "...", "data_mode": "prod" }

Authorization: Bearer <access_token>
Content-Type: application/json
```

Códigos HTTP habituales: `200` ok · `400` validación · `401` token inválido · `403` token de otro modo · `404` no encontrado · `409` sin línea / monto inválido · `500`/`502` error interno.

Si Circa no responde en un tiempo razonable (propuesta: **2 s** al abrir el detalle del pedido), el botón no se muestra y el pedido sigue al contado. Eso cubre el estado **Sin conexión** del requerimiento §6.4.

---

## 3. Identificadores que BsSoft debe persistir

Para no duplicar clientes ni pedidos, BsSoft guarda estos campos en su pedido / maestro:

| Campo en BsSoft (sugerido) | Origen | Para qué |
|----------------------------|--------|----------|
| `circa_bodega_id` | `id` de `POST/GET /bodegas` | UUID Circa de la bodega (**lo genera Circa**) |
| `circa_pedido_id` | `id` de `POST /preventas` | UUID de la solicitud / pedido |
| `circa_pedido_numero` | `numero` (ej. `CRC-123`) | Número de operación Circa |
| `external_id` (pedido) | Número de documento BsSoft | Idempotencia de la preventa (opcional) |

La llave de cruce de negocio sigue siendo **DNI (8) o RUC (11)**. El `external_id` de cliente en precarga es **opcional**.

---

## 4. Mapa de servicios

| ID | Servicio | Quién llama | Método | Ruta | Flujo del requerimiento | Estado |
|----|----------|-------------|--------|------|-------------------------|--------|
| SVC-00 | Salud | BsSoft | `GET` | `/health` | Comprobar conexión | Disponible hoy |
| SVC-01 | Consultar afiliación y línea | BsSoft | `GET` | `/bodegas?q={documento}` | §6.1 al abrir el detalle | Disponible hoy |
| SVC-01b | Obtener bodega | BsSoft | `GET` | `/bodegas/{circa_bodega_id}` | Refresco de línea | Disponible hoy |
| SVC-02 | Precargar bodega (+ fotos) | BsSoft | `POST` | `/bodegas` | §6.2 Caso A | Disponible hoy (multipart) |
| SVC-03 | Actualizar datos de bodega | BsSoft | `PATCH` | `/bodegas/{id}` | Corregir WhatsApp / dirección | Disponible hoy |
| SVC-04 | Solicitar financiamiento | BsSoft | `POST` | `/preventas` | §4 Flujo 2 · §6.3 Caso B | Disponible hoy (`monto_a_financiar` + `plazo_dias`) |
| SVC-05 | Consultar resultado | BsSoft | `GET` | `/preventas/{id}` o `/pedidos/{id}` | §4.2 · punto abierto 2 | Disponible hoy (consulta) |
| SVC-06 | Listar preventas / pedidos | BsSoft | `GET` | `/preventas` · `/pedidos` | Conciliación | Disponible hoy |
| SVC-07 | Informar despacho / entrega | BsSoft | `PATCH` | `/pedidos/{id}/estado` | §5 Flujo 3 | Disponible hoy |
| HIST-01 | Carga inicial de cartera | BsSoft → Circa | Archivo | — | §3.1 | Archivo, no API |
| HIST-02 | Refresco mensual | BsSoft → Circa | Archivo | — | §3.2 | Archivo, no API |
| WHK-01 | Aviso de resultado | Circa → BsSoft | `POST` | URL de BsSoft | §4.2 | Siguiente entrega |

---

## 5. Catálogo — servicios que BsSoft consume

### SVC-00 Salud

Comprobar que la API está arriba. Sin token.

`GET /health`

```json
{ "status": "ok", "service": "circa-integration-api", "version": "1.0.0" }
```

---

### SVC-01 Consultar afiliación y línea

**Cuándo:** al abrir el detalle de un pedido no facturado ni anulado. Es la llamada que decide qué pinta la franja.

`GET /bodegas?q={dni_o_ruc}&limit=20`

Usar el campo **`situacion`** (en el listado y en cada item):

| `situacion` | Condición | Acción del socio |
|-------------|-----------|------------------|
| `no_registrada` | `total=0` / sin coincidencia | Precargar → **SVC-02** |
| `en_evaluacion` | Existe, data ya enviada (`estado≠activo`, p.ej. precarga) | **No** reenviar SVC-02; reconsultar luego |
| `no_disponible` | `estado=activo` y `linea_disponible≤0` | Mostrar sin cupo |
| `con_linea` | `estado=activo` y `linea_disponible>0` | Financiar → **SVC-04** |
| *(error red)* | Timeout / 5xx / 401 | Sin conexión → no mostrar franja |

Campos útiles de cada item:

| Campo | Tipo | Uso en el botón |
|-------|------|-----------------|
| `id` | UUID | Guardar como `circa_bodega_id` |
| `situacion` | enum | Decisión de UI (preferir este campo) |
| `external_id` | texto | Código cliente BsSoft (si aplica) |
| `estado` | texto | `inactivo` / `activo` |
| `onboarding_fase` | texto | `precargada`, `invited`, … |
| `kyc_nivel` | texto | Avance de verificación |
| `linea_aprobada` | decimal | Tope |
| `linea_disponible` | decimal | Monto a mostrar (S/ N disponible) |
| `telefono_whatsapp` | texto | Celular en Circa |

El listado también trae `situacion` a nivel raíz (= del primer item, o `no_registrada` si vacío).

Si BsSoft ya persistió `circa_bodega_id`, preferir **SVC-01b**.

---

### SVC-02 Precargar bodega

**Cuándo:** SVC-01 devolvió `situacion=no_registrada` (o hay que enviar datos + fotos a evaluación).

`POST /bodegas`  
**Content-Type:** `multipart/form-data`  
**Obligatorio:** `foto_dueno` + `foto_bodega` (JPEG/PNG/WebP, máx 8 MB c/u).

Idempotente por teléfono / DNI / RUC / `external_id`. **No libera línea:** `linea_disponible=0` y `situacion=en_evaluacion`.

#### Request (form fields)

| Campo | Tipo | Obl. | Nota |
|-------|------|------|------|
| `telefono_whatsapp` | string | Sí | 9 dígitos o `+51…` |
| `dni_representante` | string | Sí* | DNI 8 o CE 9 |
| `ruc` | string | Sí* | 11 dígitos |
| `foto_dueno` | file | **Sí** | Foto del dueño |
| `foto_bodega` | file | **Sí** | Foto fachada / local |
| `razon_social` | string | Recomendado | |
| `nombre_comercial` | string | No | |
| `representante_legal` | string | No | |
| `direccion_fiscal` | string | Recomendado | |
| `distrito` | string | No | |
| `solo_dni_sin_ruc` | bool | No | Default `true` si no hay RUC |
| `external_id` | string | No | Código del socio (opcional) |

\* Se necesita **DNI o RUC**. El `id` lo genera Circa.

#### Response

| Campo | Nota |
|-------|------|
| `id` | UUID Circa — persistir |
| `created` | `true` si se creó en este request |
| `estado` | `inactivo` en precarga |
| `situacion` | `en_evaluacion` |
| `linea_disponible` | `0` hasta evaluación/activación |
| `tiene_foto_dueno` | `true` si se guardó |
| `tiene_foto_bodega` | `true` si se guardó |

```bash
curl -X POST "$BASE/bodegas" \
  -H "Authorization: Bearer $TOKEN" \
  -F "telefono_whatsapp=987654321" \
  -F "dni_representante=07631909" \
  -F "razon_social=BODEGA EJEMPLO" \
  -F "solo_dni_sin_ruc=true" \
  -F "foto_dueno=@./dueno.jpg;type=image/jpeg" \
  -F "foto_bodega=@./bodega.jpg;type=image/jpeg"
```

**Historial de compras:** no viaja en este `POST` (HIST-01 / HIST-02 por archivo).

---

### SVC-04 Solicitar financiamiento

**Cuándo:** el vendedor toca *Enviar solicitud* (§6.3) con una bodega que ya tiene línea. **No cierra el crédito.** La bodega aprueba después por WhatsApp con su PIN.

`POST /preventas`

Idempotente con `external_id` = número de documento BsSoft.

#### Request

| Campo | Tipo | Obl. | Nota |
|-------|------|------|------|
| `external_id` | string | Recomendado | Número de preventa/pedido BsSoft |
| `bodega_id` | UUID | Una de tres | `circa_bodega_id` (preferido) |
| `bodega_external_id` | string | Una de tres | Código cliente BsSoft |
| `telefono_whatsapp` | string | Una de tres | Lookup alternativo |
| `items[]` | lista | Sí | Debe cuadrar con el total |
| `items[].sku` | string | Recomendado | Código de producto BsSoft |
| `items[].nombre` | string | Sí | Descripción |
| `items[].unidad` | string | No | Default `UND` |
| `items[].cantidad` | decimal | Sí | |
| `items[].precio_unitario` | decimal | Sí | |
| `monto_a_financiar` | decimal | **Sí** | > 0; ≤ total ítems y ≤ `linea_disponible` |
| `plazo_dias` | entero | **Sí** | Solo `7`, `15` o `30` |
| `vendedor_codigo` | string | Recomendado | Atribución |
| `notas` | string | No | |

```json
{
  "external_id": "PV-2026-000451",
  "bodega_id": "a1b2c3d4-0001-4000-8000-000000000011",
  "vendedor_codigo": "V-014",
  "monto_a_financiar": 30.90,
  "plazo_dias": 7,
  "items": [
    {
      "sku": "CAF-SEL-200",
      "nombre": "CAFETAL SELECTO 24x200g",
      "unidad": "UND",
      "cantidad": 3,
      "precio_unitario": 10.30
    }
  ]
}
```

El resto del pedido (`total − monto_a_financiar`) queda como contado.

#### Response inmediata (acuse)

| Campo | Equivalente del requerimiento §4.2 |
|-------|--------------------------------------|
| `id` | Identificador de solicitud — persistir `circa_pedido_id` |
| `numero` | Número de operación Circa (puede llegar nulo al crear) |
| `estado` | Ver tabla de estados abajo |
| `total_pedido` | Total de líneas |
| `monto_financiado` | Monto solicitado (`monto_a_financiar`) |
| `plazo_dias` | 7 / 15 / 30 |

Tras el acuse, el botón queda **inhabilitado** (estado **En espera**). BsSoft **no** acepta el crédito en nombre de la bodega.

---

### SVC-05 Consultar resultado

Cierra el punto abierto 2 **sin que BsSoft publique un servicio**. Circa no llama a BsSoft en v1.

**Cuándo:** mientras el componente esté en *En espera*. Propuesta: cada **15–30 s** mientras el detalle del pedido esté abierto, y una vez al reabrir.

`GET /preventas/{circa_pedido_id}`  
o `GET /pedidos/{circa_pedido_id}`

| `estado` Circa | Qué muestra el botón |
|----------------|----------------------|
| `preventa_confirmada` | En espera |
| `preventa_aceptada` | Aprobado — monto, plazo, vencimiento, número |
| `preventa_cancelada` / `cancelado` | No aprobado |
| `recibido` … `entregado` | Pedido en curso (ya aprobado) |
| `pagado` | Pagado (lo gestiona Circa) |

Webhook **WHK-01** (Circa → URL de BsSoft) queda para después; no bloquea el botón.

---

### SVC-07 Informar despacho y entrega

**Cuándo:** cada cambio real de estado en BsSoft. El plazo del crédito se cuenta desde **entrega física**. Una fecha cargada en lote al final del día desplaza el vencimiento de todos los créditos de ese día (§5).

`PATCH /pedidos/{circa_pedido_id}/estado`

```json
{
  "estado": "en_camino",
  "comentario": "Salió a reparto 2026-08-18 07:42"
}
```

| Evento en BsSoft | Valor `estado` a enviar | Obligatorio |
|------------------|-------------------------|-------------|
| Pedido ingresó al sistema del socio | `recibido` | Sí, si se usa |
| En preparación | `en_preparacion` | Opcional |
| Salió a reparto | `en_camino` | Sí |
| Entrega física confirmada | `entregado` | **Sí — crítico** |

El pedido debe estar en `preventa_aceptada` (bodega ya aprobó) antes de `recibido`.

**Siguiente entrega:** `fecha_hora_efectiva` como campo propio (no solo el comentario) y `prueba_entrega_url` si el socio captura foto/firma.

---

## 6. Historial de compras — no es un servicio

Cubre §3. Un CSV o Excel es suficiente. Circa Ops indica carpeta o correo de carga.

### HIST-01 Carga inicial

Un envío con los últimos **6 meses** de bodegas con compra recurrente (criterio ZOOM). Permite precalcular líneas **antes** de afiliar.

### HIST-02 Refresco mensual

Mismo layout, solo bodegas ya afiliadas.

| Campo | Tipo | Nota |
|-------|------|------|
| Documento del cliente | RUC o DNI | Mismo del maestro |
| Nombre o razón social | texto | |
| Fecha del pedido | fecha | Del documento, no de registro |
| Número de documento | texto | Id del pedido en BsSoft |
| Monto total | decimal | Neto, sin impuestos si aplica (a confirmar) |
| Condición de pago | texto | Contado, crédito u otra |
| Estado final | texto | Para descartar anulados |

---

## 7. Qué construye BsSoft (no es un servicio)

Nada de lo siguiente se publica como API. Es el componente del requerimiento §6.

1. Franja colapsada bajo el total del pedido.
2. Consulta SVC-01 al abrir el detalle → pintar según **`situacion`**.
3. `no_registrada`: formulario de precarga → SVC-02 (**incluye foto dueño + foto bodega**).
4. `en_evaluacion`: mensaje de espera; reconsultar SVC-01b.
5. `con_linea`: monto, plazo (7/15/30), desglose → SVC-04.
6. En espera: polling SVC-05.
7. Ocultar franja si el pedido está facturado, anulado, o si SVC-01 falla (`sin_conexion`).

Reglas de datos personales:

- El celular del dueño viaja a Circa en SVC-02; no debe quedar en cola local sin conexión.
- Las fotos se envían por API (multipart); no deben quedar en la galería del equipo del vendedor más de lo necesario.

---

## 8. Secuencias

### 8.1 Precargar bodega (una vez)

```
Vendedor → Socio : abre pedido / toca Precargar
Socio    → Circa : GET /bodegas?q=…          (SVC-01 → no_registrada)
Socio    → Circa : POST /bodegas multipart   (SVC-02 + fotos)
Circa    → Socio : id, situacion=en_evaluacion, linea_disponible=0
… Circa evalúa / activa …
Socio    → Circa : GET /bodegas/{id}         (SVC-01b)
Circa    → Socio : situacion=con_linea (o no_disponible)
```

### 8.2 Financiar un pedido

```
Vendedor → Socio : Enviar solicitud (monto + plazo)
Socio    → Circa : POST /preventas           (SVC-04)
Circa    → Socio : id, monto_financiado, plazo_dias, estado=preventa_confirmada
Circa    → Dueño : resumen + PIN (si aplica el flujo Circa)
Dueño    → Circa : aprueba
Socio    → Circa : GET /preventas/{id}       (SVC-05, poll)
Circa    → Socio : preventa_aceptada
Socio    → Circa : PATCH .../estado          (SVC-07: recibido → en_camino → entregado)
```

---

## 9. Orden de implementación sugerido

Coincide con el punto abierto 7 del requerimiento.

| Orden | Entrega | Responsable |
|------:|---------|-------------|
| 1 | SVC-00, SVC-01, SVC-04, SVC-05 | Circa ya publicado · BsSoft consume |
| 2 | HIST-01 archivo de cartera | BsSoft + ZOOM + Circa Ops |
| 3 | SVC-02 precarga desde el botón | BsSoft UI + Circa (ya publicado) |
| 4 | SVC-07 estados de despacho | BsSoft |
| 5 | WHK-01 webhook de resultado | Circa · BsSoft URL |

---

## 10. Ambiente de pruebas

**Un solo ambiente (producción Railway).** La diferencia es el prefijo de URL **y** el access token:

| Modo | Base | Token | Datos |
|------|------|--------|--------|
| Real | `…/api/v1` | `data_mode=prod` | `es_test=false` |
| Prueba | `…/api/v1/test` | `data_mode=test` | `es_test=true` |

Circa entregará:

- `api_client_id` + `api_client_secret` (para `POST /auth/token`)
- `api_token` (prod) y `api_token_test` (pruebas)
- Bodegas de prueba (`es_test=true`) con y sin línea
- Swagger: `/api/v1/docs`
- Postman: carpetas **00 · Auth**, **01 · Producción**, **02 · Pruebas**

```bash
curl -s -X POST "$BASE/auth/token" -H 'Content-Type: application/json' \
  -d '{"grant_type":"client_credentials","client_id":"...","client_secret":"...","data_mode":"test"}'
```

---

## 11. Soporte

contacto@circa.pe · +51 986 311 567

Documentación interactiva: [API Socios v1](https://circa-production-c517.up.railway.app/api/v1/docs)
