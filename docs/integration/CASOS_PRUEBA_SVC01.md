# Casos de prueba — SVC-01 Consultar afiliación y línea

Matriz de **`situacion`**. Complementa `tests/test_integration_svc01.py` y la guía [`README.md`](./README.md).

**Base prod:** `https://circa-production-c517.up.railway.app/api/v1`  
**Base test:** `https://circa-production-c517.up.railway.app/api/v1/test`  
**Auth:** `Authorization: Bearer <access_token>` (obtener vía `POST /auth/token`)

Usar `$BASE` = prod o test según el caso. Los DNIs de prueba deben existir con `es_test=true` si usas `/test`.

## Cómo interpretar la respuesta

Usar el campo **`situacion`** (raíz del listado o `items[0].situacion` / bodega SVC-01b).

| Condición | `situacion` | Acción BsSoft |
|-----------|-------------|---------------|
| Timeout / 5xx / 401 | `sin_conexion`* | No mostrar Circa |
| `total=0` / `items=[]` | `no_registrada` | Caso A → SVC-02 |
| Existe, `estado≠activo` (data ya enviada) | `en_evaluacion` | Esperar / reconsultar; **no** SVC-02 |
| `estado=activo` y `linea_disponible≤0` | `no_disponible` | Bloquear financiar |
| `estado=activo` y `linea_disponible>0` | `con_linea` | Caso B → SVC-04 |

\* `sin_conexion` no viene en el JSON de bodega: lo deriva el cliente ante fallo de red/HTTP.

En código Circa: `app.integration.franja.calcular_situacion` / `interpretar_franja_svc01`.

---

## Datos de prueba (ZOOM · `es_test=true`)

Usar como `q` en `GET /api/v1/test/bodegas?q=...` (Bearer test).

| Alias | Condición / `situacion` | Valor de `q` |
|-------|-------------------------|--------------|
| A | `no_registrada` | `00000000` |
| B | `en_evaluacion` (inactiva) | `08608042` |
| B2 | `en_evaluacion` (por RUC) | `10991291415` |
| D | `con_linea` | `46843088` |
| D2 | `con_linea` | `73217300` |
| D3 | `con_linea` | `46097938` |
| D4 | `con_linea` | `06806355` |
| Tel | Match por teléfono | `912114088` |
| E | SVC-01b 404 | UUID `00000000-0000-0000-0000-000000000000` |

También se puede buscar por razón social parcial, p.ej. `JONATHAN TEST`.

Detalle y credenciales: [`GUIA_ZOOM_PRUEBAS.md`](./GUIA_ZOOM_PRUEBAS.md).

---

## Casos

### TP-01 — No encuentra bodega → no_registrada

```bash
curl -s -H "Authorization: Bearer $TOKEN" \
  "$BASE/bodegas?q=00000000&limit=20"
```

| Esperado | Valor |
|----------|--------|
| HTTP | `200` |
| Body | `{"total":0,"items":[],"situacion":"no_registrada"}` |
| Franja | `sin_linea` |

### TP-02 — Bodega inactiva → en_evaluacion

```bash
curl -s -H "Authorization: Bearer $TOKEN" \
  "$BASE/bodegas?q=<DNI_INACTIVA>&limit=20"
```

| Esperado | Valor |
|----------|--------|
| HTTP | `200` |
| `items[0].estado` | `inactivo` |
| `items[0].situacion` | `en_evaluacion` |
| `situacion` (raíz) | `en_evaluacion` |
| Acción | No reenviar SVC-02; reconsultar |

### TP-03 — Activa sin cupo → No disponible

```bash
curl -s -H "Authorization: Bearer $TOKEN" \
  "$BASE/bodegas?q=<DNI_ACTIVA_SIN_CUPO>&limit=20"
```

| Esperado | Valor |
|----------|--------|
| HTTP | `200` |
| `estado` | `activo` |
| `linea_disponible` | `0` |
| Franja | `no_disponible` |

### TP-04 — Activa con línea → Con línea (happy)

```bash
curl -s -H "Authorization: Bearer $TOKEN" \
  "$BASE/bodegas?q=<DNI_ACTIVA_CON_CUPO>&limit=20"
```

| Esperado | Valor |
|----------|--------|
| HTTP | `200` |
| `estado` | `activo` |
| `linea_disponible` | `> 0` |
| Franja | `con_linea` |
| Campos útiles | `id`, `linea_aprobada`, `telefono_whatsapp` |

### TP-05 — Timeout / Sin conexión

Simular cortando red o con timeout de cliente < 1 ms.

| Esperado | Valor |
|----------|--------|
| Franja | `sin_conexion` |
| UI | No mostrar botón Circa |

### TP-06 — 5xx

| Esperado | Valor |
|----------|--------|
| HTTP | `5xx` |
| Franja | `sin_conexion` |

### TP-07 — Token inválido

```bash
curl -s -o /dev/null -w "%{http_code}" \
  -H "Authorization: Bearer token-invalido" \
  "$BASE/bodegas?q=07631909"
```

| Esperado | Valor |
|----------|--------|
| HTTP | `401` |
| Franja | `sin_conexion` |

### TP-08 — SVC-01b UUID inexistente

```bash
curl -s -o /dev/null -w "%{http_code}" \
  -H "Authorization: Bearer $TOKEN" \
  "$BASE/bodegas/00000000-0000-0000-0000-000000000000"
```

| Esperado | Valor |
|----------|--------|
| HTTP | `404` |
| Situación | `no_registrada` |

### TP-09 — Inactiva con tope aprobado

Misma query que TP-02 con `linea_aprobada > 0`.

| Esperado | Valor |
|----------|--------|
| Situación | `en_evaluacion` (no usar el tope hasta `activo`) |

### TP-10 — Varias coincidencias

Buscar un término ambiguo (`q=BODEGA`) si hay más de un match.

| Esperado | Valor |
|----------|--------|
| HTTP | `200` |
| `total` | `> 1` |
| Acción | Elegir por DNI exacto; usar `items[i].situacion` |

---

## Checklist rápido QA

- [ ] TP-01 lista vacía
- [ ] TP-02 inactiva → Caso A
- [ ] TP-03 activa sin cupo → No disponible
- [ ] TP-04 activa con cupo → Caso B
- [ ] TP-07 401
- [ ] TP-08 404 en SVC-01b
- [ ] `created` siempre `false` en GET
- [ ] Timeout no pinta franja

## Tests automatizados

```bash
python3 -m pytest tests/test_integration_svc01.py -q
```
