# 03 — Pago y PIN WhatsApp (spec Figma)

| | |
|--|--|
| **Figma** | [Wireframes — página 04 Pago](https://www.figma.com/design/8uXIOxgppRe67aNbThSyv6) |
| **Escenarios** | PAY-01 … PAY-09 |
| **Código** | `catalogo._send_payment_options`, `meta_client.send_pin_request(mode=verify)`, `pin_flow.py` |
| **Actor** | Bodeguero |

**Disparador:** tras `submit-cart` venta (delay 2 s, PAY-09).

---

## PAY-01 · Resumen + opciones de pago

| | |
|--|--|
| **Circa** | `text` + `list_reply` |
| **Mensaje 1** | Resumen ítems + **TOTAL: S/{total}** |
| **Mensaje 2** | ¿Cómo quieres pagar? |
| **Botón lista** | Ver opciones |
| **Filas (orden PAY-01)** | 1. 💵 Pago todo hoy · 2. Financiar S/500…S/100 · 3. ✏️ Editar carrito |
| **Bodeguero** | Elige fila de la lista |

IDs ejemplo: `CONTADO_{pid}`, `FINFIJO500_{pid}`, `EDITAR_{pid}`.

---

## PAY-02 · Contado

| | |
|--|--|
| **Bodeguero** | Toca **Pago todo hoy** |
| **Circa** | `flow` o `text` → pide PIN verificación |
| **Mensaje** | Ingresa tu clave Circa de 4 dígitos para confirmar (Flow `PIN_VERIFY`) |
| **Bodeguero** | Ingresa PIN en Flow |
| **Siguiente** | PAY-07 confirmado |

---

## PAY-03 · Financiar tramo

| | |
|--|--|
| **Bodeguero** | Toca **Financiar S/{monto}** (≤ línea y ≤ total) |
| **Circa** | Resumen: paga hoy + cuota 7d (fee según `fees.py`) |
| **Bodeguero** | Confirma → PIN Flow |
| **Siguiente** | PAY-07 |

---

## PAY-04 / PAY-05 · Sin tiers / sin línea

| Caso | Comportamiento Circa |
|------|----------------------|
| Total &lt; S/100 | Solo contado + opcional FIN100 a 7d |
| `linea <= 0` (PAY-05) | «Sin crédito disponible. Solo contado.» + PIN |

---

## PAY-07 · Pedido confirmado

| | |
|--|--|
| **Circa** | `text` · `send_order_confirmation` |
| **Mensaje** | 🎉 ¡Pedido confirmado! Pedido {numero}, Pago hoy S/X, Pago después S/Y. Escribe MENU… |
| **Bodeguero** | Lee confirmación (fin flujo pago) |

---

## PAY-09 · Delay

Entre cierre catálogo y opciones de pago: `asyncio.sleep(2)` — mostrar frame **loading** «Preparando opciones de pago…».

---

## Errores PIN (pago)

| Circa | Bodeguero |
|-------|-----------|
| Clave incorrecta. Te quedan N intentos. | Reingresa PIN |
| Clave bloqueada N minutos. | Espera |

Código: `messages.msg_pin_incorrecto`, `msg_pin_bloqueado`.

[← Índice Figma](./README.md) · [Journey técnico](../03-pago-pin.md)
