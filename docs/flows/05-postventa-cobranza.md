# 05 — Postventa y cobranza

| | |
|--|--|
| **Figma** | [Wireframes — página 06 Postventa](https://www.figma.com/design/8uXIOxgppRe67aNbThSyv6) · [Spec WhatsApp](./figma/05-postventa-whatsapp.md) |
| **Escenarios** | POS-01 … POS-06 |
| **Código** | `app/state_machine.py` (menú), `app/services/cobranza.py`, `app/routes/distribuidor.py` admin |

## Objetivo

Consultar pedidos activos, reportar pago, recordatorios automáticos, verificación admin y mora.

## Menú bodeguero

| Comando | Escenario | Acción |
|---------|-----------|--------|
| ESTADO / 3 | POS-01 | Lista pedidos activos + vencimiento |
| LINEA / 2 | POS-02 | Línea aprobada/disponible/scoring |
| PAGUE | POS-03 | `estado → pago_reportado` si entregado |
| PEDIDO / 1 | — | Nuevo pedido (ver catálogo) |

## Cobranza backoffice

- Recordatorios: `POST /api/cobranza/send-reminders`
- Verificar pago: `POST /admin/verificar-pago/{pedido_id}` (POS-05)
- Mora: `fees.calcular_total_a_pagar` (POS-06)

## Wireframes (placeholder)

| Pantalla | ID |
|----------|-----|
| Texto lista pedidos activos | POS-01 |
| Confirmación pago reportado | POS-03 |

[← Índice](./README.md)
