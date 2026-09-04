# Casos de prueba — SVC-01 Consultar afiliación y línea

Matriz §6.4 del botón Circa. Complementa `tests/test_integration_svc01.py`.

**Base prod:** `https://circa-production-c517.up.railway.app/api/v1`  
**Base test:** `https://circa-production-c517.up.railway.app/api/v1/test`  
**Auth:** `Authorization: Bearer <api_token>`

Usar `$BASE` = prod o test según el caso. Los DNIs de prueba deben existir con `es_test=true` si usas `/test`.

## Cómo interpretar la respuesta

| Condición | Franja UI | Acción BsSoft |
|-----------|-----------|---------------|
| Timeout / 5xx / 401 | `sin_conexion` | No mostrar Circa |
| `total=0` / `items=[]` | `sin_linea` | Caso A → SVC-02 |
| `estado≠activo` | `sin_linea` | Caso A → SVC-02 |
| `estado=activo` y `linea_disponible≤0` | `no_disponible` | Bloquear financiar |
| `estado=activo` y `linea_disponible>0` | `con_linea` | Caso B → SVC-04 |

En código Circa: `app.integration.franja.interpretar_franja_svc01`.

---

## Datos de prueba sugeridos (sembrar en BD o usar existentes)

| Alias | Condición | Ejemplo de `q` |
|-------|-----------|----------------|
| A | No existe | DNI `00000000` |
| B | `inactivo`, `linea_disponible=0` | DNI de bodega precargada |
| C | `activo`, `linea_disponible=0` | Bodega activa sin cupo |
| D | `activo`, `linea_disponible>0` | Bodega activa con cupo |
| E | UUID inventado | SVC-01b |

---

## Casos

### TP-01 — No encuentra bodega → Sin línea

```bash
curl -s -H "Authorization: Bearer $TOKEN" \
  "$BASE/bodegas?q=00000000&limit=20"
```

| Esperado | Valor |
|----------|--------|
| HTTP | `200` |
| Body | `{"total":0,"items":[]}` |
| Franja | `sin_linea` |

### TP-02 — Bodega inactiva → Sin línea (Caso A)

```bash
curl -s -H "Authorization: Bearer $TOKEN" \
  "$BASE/bodegas?q=<DNI_INACTIVA>&limit=20"
```

| Esperado | Valor |
|----------|--------|
| HTTP | `200` |
| `items[0].estado` | `inactivo` |
| `items[0].created` | `false` |
| Franja | `sin_linea` (aunque `linea_aprobada` > 0) |

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
| Franja | `sin_linea` |

### TP-09 — Inactiva con tope aprobado

Misma query que TP-02 con `linea_aprobada > 0`.

| Esperado | Valor |
|----------|--------|
| Franja | `sin_linea` (no usar el tope hasta `activo`) |

### TP-10 — Varias coincidencias

Buscar un término ambiguo (`q=BODEGA`) si hay más de un match.

| Esperado | Valor |
|----------|--------|
| HTTP | `200` |
| `total` | `> 1` |
| Acción | Elegir por `external_id` / DNI exacto; evaluar franja sobre ese item |

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
