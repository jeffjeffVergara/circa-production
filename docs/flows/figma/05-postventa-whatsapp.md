# 05 — Postventa WhatsApp (spec Figma)

| | |
|--|--|
| **Figma** | [Wireframes — página 06 Postventa](https://www.figma.com/design/8uXIOxgppRe67aNbThSyv6) |
| **Escenarios** | POS-01 … POS-06 |
| **Código** | `state_machine` menú, `send_linea_info`, `cobranza.py`, `send_tracking_update` |
| **Actor** | Bodeguero |

**Entrada:** menú principal (`send_menu`) o comandos de texto.

---

## POS-01 · Ver pedidos (ESTADO)

| | |
|--|--|
| **Bodeguero** | Menú → **Ver mis pedidos** (`ESTADO`) o escribe `ESTADO` / `3` |
| **Circa** | `text` — lista pedidos activos, estados, vencimientos |
| **Ejemplo estados** | confirmado, preparando, en_camino, entregado (`send_tracking_update`) |

---

## POS-02 · Línea de crédito (LINEA)

| | |
|--|--|
| **Bodeguero** | Menú → **Comprar y pagar luego** (`LINEA`) |
| **Circa** | `button_reply` · `send_linea_info` |
| **Mensaje** | Línea aprobada S/X, disponible S/Y, barra progreso, scoring /100 |
| **Botones** | Hacer pedido · Menú principal |
| **Bodeguero** | Elige acción |

---

## POS-03 · Reportar pago (PAGUE)

| | |
|--|--|
| **Bodeguero** | Escribe `PAGUE` / **YA PAGUE** desde menú |
| **Circa** | `text` — confirma recepción reporte, verificación pendiente |
| **Backend** | `estado → pago_reportado` |
| **Siguiente** | Admin verifica (POS-05, fuera del chat) |

---

## POS-04 · Recordatorio cobranza (proactivo)

| | |
|--|--|
| **Actor** | Sistema / cron (`send_pending_reminders`) |
| **Circa** | `text` · `messages.msg_recordatorio` |
| **Mensaje** | Recordatorio: pago S/{monto} vence {fecha}. Yape/Plin + «escribe PAGUE» |
| **Bodeguero** | Paga fuera de WA → escribe **PAGUE** |

---

## POS-05 · Pago verificado (éxito)

| | |
|--|--|
| **Circa** | `text` · `msg_pago_recibido` |
| **Mensaje** | Pago registrado S/X. Línea disponible ahora S/Y. Escribe PEDIDO… |
| **Bodeguero** | Lee confirmación |

---

## POS-06 · Mora

Reflejada en totales de cobranza (`fees.calcular_total_a_pagar`) — mensaje puede incluir interés mora en recordatorios post-vencimiento.

---

## Mapa menú → postventa

| Fila menú | ID | Journey |
|-----------|-----|---------|
| Ver mis pedidos | `ESTADO` | POS-01 |
| Comprar y pagar luego | `LINEA` | POS-02 |
| (texto libre) | `PAGUE` | POS-03 |

[← Índice Figma](./README.md) · [Journey técnico](../05-postventa-cobranza.md)
