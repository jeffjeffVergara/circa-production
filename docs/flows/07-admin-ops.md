# 07 — Admin y operaciones

| | |
|--|--|
| **Figma** | *[pendiente — página «07 Admin»]* |
| **Escenarios** | ADM-01 … ADM-05, OPS-01, OPS-02 |
| **Código** | `app/routes/distribuidor.py` (rutas `/admin/*`), migraciones `migrations/` |

## Objetivo

Monitoreo operativo, cobranza, alertas, migraciones de datos y smoke de release.

## Endpoints clave

| Ruta | Uso |
|------|-----|
| `GET /admin/resumen` | ADM-01 |
| `GET /admin/cobranzas` | ADM-02 |
| `GET /admin/alerts/sobregiro` | ADM-03 |
| `POST /admin/verificar-pago/{id}` | POS-05 |

## Migraciones manuales (Supabase)

| ID | Archivo | Cuándo |
|----|---------|--------|
| ADM-05 | `20260520_pedidos_fee_regimen.sql` | Antes de fees nuevos en prod |
| ADM-04 | `20260521_pedidos_zoom_a_dimax_solo_piloto.sql` | Corrección histórico Zoom (solo `en_piloto`) |

## Latencia bot (OPS-01)

Tras deploy con `analytics.py` actualizado:

```sql
SELECT telefono, response_time_ms, message_type, created_at
FROM messages
WHERE direction = 'outbound' AND response_time_ms IS NOT NULL
ORDER BY created_at DESC LIMIT 20;
```

Consultas: `migrations/20260522_message_latency_queries.sql`

## Smoke release (OPS-02)

Checklist P0 en [README.md § Smoke](./README.md#smoke-checklist--release-piloto-p0).

[← Índice](./README.md)
