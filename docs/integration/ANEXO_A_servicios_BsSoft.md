# Anexo A — Catálogo de servicios Circa ↔ BsSoft

**Documento técnico · anexo al Requerimiento v1.0**

| Campo | Detalle |
|-------|---------|
| Versión | v1.0 |
| Fecha | 17 de agosto de 2026 |
| Emite | Circa (Pali S.A.C., RUC 20600627806) |
| Dirigido a | BsSoft — equipo de producto y desarrollo |
| Con copia a | ZOOM |
| Relacionado | *Circa_Requerimiento_Tecnico_BsSoft_v1* (11 ago 2026) |

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

Códigos HTTP habituales: `200` ok · `400` validación · `401` token inválido · `404` no encontrado · `500` error interno.

Si Circa no responde en un tiempo razonable (propuesta: **2 s** al abrir el detalle del pedido), el botón no se muestra y el pedido sigue al contado. Eso cubre el estado **Sin conexión** del requerimiento §6.4.

---

## 3. Identificadores que BsSoft debe persistir

Para no duplicar clientes ni pedidos, BsSoft guarda estos campos en su pedido / maestro:

| Campo en BsSoft (sugerido) | Origen | Para qué |
|----------------------------|--------|----------|
| `circa_bodega_id` | `id` de `POST/GET /bodegas` | UUID Circa de la bodega |
| `external_id` (cliente) | Código de cliente BsSoft | Idempotencia al precargar |
| `circa_pedido_id` | `id` de `POST /preventas` | UUID de la solicitud / pedido |
| `circa_pedido_numero` | `numero` (ej. `CRC-123`) | Número de operación Circa |
| `external_id` (pedido) | Número de documento BsSoft | Idempotencia de la preventa |

La llave de cruce de negocio sigue siendo **DNI (8) o RUC (11)**, el mismo del maestro de clientes. El `external_id` es la llave técnica.

---

## 4. Mapa de servicios

| ID | Servicio | Quién llama | Método | Ruta | Flujo del requerimiento | Estado |
|----|----------|-------------|--------|------|-------------------------|--------|
| SVC-00 | Salud | BsSoft | `GET` | `/health` | Comprobar conexión | Disponible hoy |
| SVC-01 | Consultar afiliación y línea | BsSoft | `GET` | `/bodegas?q={documento}` | §6.1 al abrir el detalle | Disponible hoy |
| SVC-01b | Obtener bodega | BsSoft | `GET` | `/bodegas/{circa_bodega_id}` | Refresco de línea | Disponible hoy |
| SVC-02 | Precargar bodega | BsSoft | `POST` | `/bodegas` | §6.2 Caso A | Disponible hoy |
| SVC-03 | Actualizar datos de bodega | BsSoft | `PATCH` | `/bodegas/{id}` | Corregir WhatsApp / dirección | Disponible hoy |
| SVC-04 | Solicitar financiamiento | BsSoft | `POST` | `/preventas` | §4 Flujo 2 · §6.3 Caso B | Disponible hoy; campos de monto/plazo en siguiente entrega |
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

| Respuesta | Componente (§6.4) |
|-----------|-------------------|
| Sin coincidencia o `estado=inactivo` / `linea_disponible=0` y sin contrato | **Sin línea** → Caso A |
| `estado=activo` y `linea_disponible > 0` | **Con línea** → Caso B |
| `estado=activo` y `linea_disponible=0` | **No disponible** |
| Timeout / 5xx | **Sin conexión** → no mostrar franja |

Campos útiles de cada item:

| Campo | Tipo | Uso en el botón |
|-------|------|-----------------|
| `id` | UUID | Guardar como `circa_bodega_id` |
| `external_id` | texto | Código cliente BsSoft |
| `estado` | texto | `inactivo` / `activo` |
| `onboarding_fase` | texto | `precargada`, `invited`, … |
| `kyc_nivel` | texto | Avance de verificación |
| `linea_aprobada` | decimal | Tope |
| `linea_disponible` | decimal | Monto a mostrar (S/ N disponible) |
| `telefono_whatsapp` | texto | Ya hay celular en Circa |

Si BsSoft ya persistió `circa_bodega_id`, preferir **SVC-01b**.

---

### SVC-02 Precargar bodega

**Cuándo:** el vendedor toca *Precargar bodega* (§6.2). Ocurre **una vez por bodega**.

`POST /bodegas`

Idempotente si se envía `external_id` (código de cliente BsSoft), WhatsApp, RUC o DNI. **No libera línea:** `linea_disponible` queda en `0` hasta que el dueño termina KYC, contrato y PIN por WhatsApp.

#### Request

| Campo | Tipo | Obl. | Nota |
|-------|------|------|------|
| `external_id` | string ≤64 | Recomendado | Código de cliente en BsSoft |
| `telefono_whatsapp` | string | Sí | 9 dígitos que empiezan en 9, o `+51XXXXXXXXX` |
| `dni_representante` | string | Sí* | DNI 8 dígitos o CE 9 |
| `ruc` | string | No | 11 dígitos |
| `razon_social` | string | Recomendado | Del maestro |
| `nombre_comercial` | string | No | |
| `representante_legal` | string | No | |
| `direccion_fiscal` | string | Recomendado | Del maestro |
| `distrito` | string | No | |
| `solo_dni_sin_ruc` | bool | No | `true` si no tiene RUC |

\* Se necesita DNI o RUC para el cruce posterior.

```json
{
  "external_id": "CLI-07631909",
  "telefono_whatsapp": "987654321",
  "dni_representante": "07631909",
  "razon_social": "RABANAL ALVARADO GLADYS ROCIO",
  "direccion_fiscal": "Av. Ejemplo 123",
  "distrito": "Comas",
  "solo_dni_sin_ruc": true
}
```

#### Response

| Campo | Nota |
|-------|------|
| `id` | UUID Circa — persistir |
| `created` | `true` si se creó en este request |
| `estado` | Queda `inactivo` en precarga |
| `linea_aprobada` | Tope provisional; Circa puede ajustar con el historial |
| `linea_disponible` | Siempre `0` hasta activación |

**Adjuntos (foto DNI / foto bodega):** el requerimiento §6.2 los marca opcionales. En v1 **no viajan por este servicio**. Circa los capta en WhatsApp durante la verificación. La vista embebida servida por Circa (§6.5) queda para una entrega posterior.

**Historial de esa bodega en el mismo clic:** no viaja en el `POST`. Se cubre con HIST-01 / HIST-02 (archivo). Circa ya puede precargar sin historial; la línea se refina cuando llega el archivo.

---

### SVC-04 Solicitar financiamiento

**Cuándo:** el vendedor toca *Enviar solicitud* (§6.3) con una bodega que ya tiene línea. **No cierra el crédito.** La bodega aprueba después por WhatsApp con su PIN.

`POST /preventas`

Idempotente con `external_id` = número de documento BsSoft.

#### Request — disponible hoy

| Campo | Tipo | Obl. | Nota |
|-------|------|------|------|
| `external_id` | string | Recomendado | Número de preventa/pedido BsSoft |
| `bodega_id` | UUID | Una de tres | `circa_bodega_id` |
| `bodega_external_id` | string | Una de tres | Código cliente BsSoft |
| `telefono_whatsapp` | string | Una de tres | Lookup alternativo |
| `items[]` | lista | Sí | Debe cuadrar con el total |
| `items[].sku` | string | Recomendado | Código de producto BsSoft |
| `items[].nombre` | string | Sí | Descripción |
| `items[].unidad` | string | No | Default `UND` |
| `items[].cantidad` | decimal | Sí | |
| `items[].precio_unitario` | decimal | Sí | |
| `vendedor_codigo` | string | Recomendado | Atribución |
| `notas` | string | No | |

```json
{
  "external_id": "PV-2026-000451",
  "bodega_external_id": "CLI-07631909",
  "vendedor_codigo": "V-014",
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

#### Request — siguiente entrega (ya previstos en el requerimiento §4.1)

Estos campos **aún no están en el contrato publicado**. Circa los añadirá antes del piloto del botón. BsSoft puede dejarlos en el formulario y no enviarlos hasta el aviso de Circa.

| Campo | Tipo | Nota |
|-------|------|------|
| `monto_a_financiar` | decimal | Default: `min(linea_disponible, total)`. El resto es contado. |
| `plazo_dias` | entero | `7` (preseleccionado), `15` o `30` |
| `fecha_entrega_prevista` | date | Fecha de entrega planeada |
| `total_pedido` | decimal | Control: debe coincidir con la suma de líneas |

#### Response inmediata (acuse)

| Campo | Equivalente del requerimiento §4.2 |
|-------|--------------------------------------|
| `id` | Identificador de solicitud — persistir `circa_pedido_id` |
| `numero` | Número de operación Circa (puede llegar nulo al crear) |
| `estado` | Ver tabla de estados abajo |
| `total_pedido` | Total de líneas |
| `monto_financiado` | Monto Circa (hoy 0 al crear; se completa al aprobar) |

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
2. Consulta SVC-01 al abrir el detalle.
3. Caso A: formulario de precarga → SVC-02.
4. Caso B: monto, plazo, desglose, *Enviar solicitud* → SVC-04.
5. En espera: polling SVC-05.
6. Ocultar franja si el pedido está facturado, anulado, o si SVC-01 falla.

Reglas de datos personales (§6.5), vigentes desde v1:

- El WhatsApp del dueño viaja a Circa en SVC-02; no debe quedar en cola local sin conexión.
- Las fotos del DNI no deben guardarse en la galería del equipo del vendedor.
- En v1 Circa no pide esas fotos por API.

---

## 8. Secuencias

### 8.1 Precargar bodega (una vez)

```
Vendedor → BsSoft: abre pedido / toca Precargar
BsSoft   → Circa  : POST /bodegas          (SVC-02)
Circa    → BsSoft : id, linea_disponible=0
Circa    → Dueño  : WhatsApp (KYC, contrato, PIN)
Dueño    → Circa  : completa activación
BsSoft   → Circa  : GET /bodegas/{id}      (SVC-01b, al reabrir)
Circa    → BsSoft : estado=activo, linea_disponible>0
```

### 8.2 Financiar un pedido

```
Vendedor → BsSoft: Enviar solicitud
BsSoft   → Circa  : POST /preventas        (SVC-04)
Circa    → BsSoft : id, estado=preventa_confirmada
Circa    → Dueño  : resumen + PIN
Dueño    → Circa  : aprueba
BsSoft   → Circa  : GET /preventas/{id}    (SVC-05, poll)
Circa    → BsSoft : preventa_aceptada
BsSoft   → Circa  : PATCH .../estado       (SVC-07: recibido → en_camino → entregado)
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
| 5 | Campos `monto_a_financiar` / `plazo_dias` en SVC-04 | Circa siguiente entrega |
| 6 | WHK-01 webhook de resultado | Circa siguiente entrega · BsSoft URL |

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
