# Circa × BsSoft — Entrantes (pedidos antes de la pre-venta)

**Versión:** 1.0 · **Fecha:** 12 oct 2026
**Dirigido a:** BsSoft — equipo que envía los pedidos del distribuidor
**Alcance:** solo **pruebas** hasta aviso de Circa. No llama a producción.

Circa expone el servicio. BsSoft lo consume. Un entrante **no es una pre-venta**: no crea pedido Circa, no asigna número CRC y no reserva línea de crédito.

La pre-venta oficial sigue siendo `POST /preventas` (SVC-04), y solo cuando la bodega ya está activa y Circa aceptó el entrante. Este documento no reemplaza ese paso.

---

## 1. URLs

| Recurso | URL |
|---------|-----|
| Base de pruebas | `https://circa-production-c517.up.railway.app/api/v1/test` |
| Enviar entrante | `POST /api/v1/test/entrantes` |
| Consultar uno | `GET /api/v1/test/entrantes/{id}` |
| Listar | `GET /api/v1/test/entrantes` |
| Auth | `POST /api/v1/auth/token` |
| Swagger | https://circa-production-c517.up.railway.app/api/v1/docs |

Producción, cuando Circa lo habilite: las mismas rutas **sin** `/test` (`POST /api/v1/entrantes`). El token de pruebas no sirve en producción, ni al revés.

Todo lo que entre por `/api/v1/test` queda marcado como prueba y se ve en el backoffice de Circa con el interruptor **Pruebas**.

---

## 2. Acceso

Usen las credenciales de prueba que Circa ya entregó (cliente `zoom-circa`, `data_mode: "test"`). El mismo Bearer de los demás servicios.

```http
Authorization: Bearer <access_token>
Content-Type: application/json
```

Si el token responde 401, pídanlo de nuevo:

```bash
curl -s -X POST "https://circa-production-c517.up.railway.app/api/v1/auth/token" \
  -H "Content-Type: application/json" \
  -d '{"grant_type":"client_credentials","client_id":"zoom-circa","client_secret":"<el secret ya entregado>","data_mode":"test"}'
```

No hace falta una clave distinta para entrantes.

---

## 3. Qué enviar

Es el mismo pedido que hoy sale en el Excel DIMAX.

| Campo | Obligatorio | Equivale en el Excel |
|-------|-------------|----------------------|
| `external_id` | Sí | Número de documento en BsSoft. Es la llave: reenviar el mismo valor **actualiza** ese entrante, no crea otro. |
| `bodega_nombre` | Sí | Nombre de la bodega en el archivo |
| `fecha` | Sí | Fecha **y hora** del pedido |
| `items` | Sí | Las filas del Excel. Al menos una. |
| `bodega_external_id` | No | Código del cliente en BsSoft, si lo tienen |
| `telefono_whatsapp` | No | Celular de la bodega, 9 dígitos o `+51XXXXXXXXX` |
| `bodega_id` | No | UUID de Circa, solo si ya lo guardaron de SVC-01 o SVC-02 |
| `monto_credito` | No | Cuánto de ese total pide crédito Circa. Puede ir vacío y completarse después. |
| `pago_confirmado` | No | `true` solo cuando el pago del tramo Circa ya está confirmado. Si no viene, queda `false`. |

Cada ítem:

| Campo | Obligatorio | Columna del Excel |
|-------|-------------|-------------------|
| `codigo` | Sí | Codigo |
| `descripcion` | Sí | Descripcion |
| `cantidad` | Sí | Cantidad, mayor a 0 |
| `unidad` | No | Unidad. Si no viene, Circa usa `UND`. |
| `precio_unitario` | Sí | P. Unitario |
| `subtotal` | Sí | SubTotal, antes del descuento |
| `total` | Sí | Total, monto cobrado. `0` es un regalo. |

`subtotal` no puede ser menor que `total`.

### Hora

`fecha` acepta `2026-10-12T09:40:00` o con zona (`2026-10-12T09:40:00-05:00`). Si no trae zona, Circa la toma como **GMT-5** (Perú). Si solo llega el día (`2026-10-12`), queda a las 00:00 GMT-5. En la respuesta la hora siempre vuelve en GMT-5.

### Cómo se calcula el dinero

Circa no pide el total del documento. Lo calcula:

- **Total del pedido** = suma de `total` de las líneas que no son regalo.
- **Descuento** = suma de `subtotal − total` en esas mismas líneas.
- Una línea es **regalo** si `total` es 0 o si `descripcion` empieza con `BONIFICACION`. No suma al total ni al descuento.

### Qué no enviar

No hace falta mandar el total del documento ni nombres viejos. Si igual llegan, Circa los trata así:

| Clave | Qué pasa |
|-------|----------|
| `sku` | No la envíen. Si viene y no hay `codigo`, Circa la usa como código. |
| `nombre` | No la envíen. Si viene y no hay `descripcion`, Circa la usa como descripción. |
| `total_pedido`, `descuento_prorrateado`, `monto_productos` | Circa las calcula. Si vienen en el JSON, no se usan. |

`monto_a_financiar` y `plazo_dias` pertenecen a `POST /preventas`, no a este servicio.

---

## 4. Ejemplo

```bash
curl -s -X POST "https://circa-production-c517.up.railway.app/api/v1/test/entrantes" \
  -H "Authorization: Bearer <access_token>" \
  -H "Content-Type: application/json" \
  -d '{
    "external_id": "PV-2026-000451",
    "bodega_nombre": "URBANO CHIHUANTITO DAVID GENARO",
    "fecha": "2026-10-12T09:40:00",
    "bodega_external_id": "CLI-10442",
    "telefono_whatsapp": "989153197",
    "items": [
      {
        "codigo": "004521",
        "descripcion": "CAFETAL SELECTO 24x200g",
        "cantidad": 3,
        "unidad": "UND x 24",
        "precio_unitario": 10.30,
        "subtotal": 32.10,
        "total": 30.90
      },
      {
        "codigo": "001102",
        "descripcion": "BONIFICACION GALLETA SODA",
        "cantidad": 1,
        "unidad": "UND",
        "precio_unitario": 0,
        "subtotal": 2.50,
        "total": 0
      }
    ]
  }'
```

Ese pedido queda en total **S/30.90**, descuento **S/1.20**, y una línea de regalo.

Reenviar el mismo `external_id` con líneas corregidas actualiza el entrante. La respuesta trae `"created": false`.

---

## 5. Qué responde Circa

| Campo | Significado |
|-------|-------------|
| `id` | Identificador Circa del entrante. Guárdenlo si van a consultarlo. |
| `created` | `true` la primera vez, `false` si se actualizó. |
| `estado` | Ver la tabla de abajo. |
| `fecha` | La misma hora, en GMT-5. |
| `total_pedido` | Suma cobrada. |
| `descuento_prorrateado` | Descuento calculado. |
| `existe_en_circa` | Circa encontró una bodega. |
| `bodega_activa` | Esa bodega está activa. No bloquea el entrante: una bodega aún no enrolada puede quedar `lista`. |
| `bodega_id` | UUID Circa, si hubo match. |
| `n_items` / `n_regalos` | Conteo de líneas. |

| `estado` | Cuándo |
|----------|--------|
| `sin_match` | No hay bodega Circa para ese nombre, código o teléfono. |
| `pendiente_monto` | Hay bodega, y `monto_credito` no vino o es 0. |
| `pendiente_pago` | Hay monto de crédito, y el pago todavía no está confirmado. |
| `lista` | Hay match, monto de crédito mayor a 0 y pago confirmado. |
| `descartada` | Circa lo sacó de la bandeja. Un POST nuevo del mismo `external_id` lo vuelve a calcular. |

El match no exige que la bodega esté enrolada. Circa cruza, en este orden: `bodega_id`, `bodega_external_id`, `telefono_whatsapp`, y al final el nombre.

Consultar: `GET /api/v1/test/entrantes/{id}`. Listar: `GET /api/v1/test/entrantes?estado=lista`.

Para corregir solo el crédito o el pago, sin reenviar las líneas:

```http
PATCH /api/v1/test/entrantes/{id}
```

```json
{ "monto_credito": 30.90, "pago_confirmado": true }
```

---

## 6. Errores

| HTTP | Cuándo |
|------|--------|
| 401 | Token ausente o inválido |
| 403 | Token de producción usado en `/test`, o al revés |
| 400 | Falta `codigo` o `descripcion`, `cantidad` no es mayor a 0, `subtotal` es menor que `total`, `fecha` no se entiende, o `monto_credito` supera el total |
| 404 | El `id` no existe en este modo |

---

## 7. Qué no hace este servicio

- No llama a `POST /preventas`.
- No manda WhatsApp a la bodega.
- No reserva `linea_disponible`.

Cuando Circa acepte el entrante y la bodega corresponda, el financiamiento sigue el flujo ya documentado en SVC-04.

Soporte: contacto@circa.pe · +51 986 311 567
