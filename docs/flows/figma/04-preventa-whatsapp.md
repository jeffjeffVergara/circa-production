# 04 — Preventa WhatsApp (spec Figma)

| | |
|--|--|
| **Figma** | [Wireframes — página 05 Preventa](https://www.figma.com/design/8uXIOxgppRe67aNbThSyv6) |
| **Escenarios** | PRV-01 … PRV-06 |
| **Código** | `send_catalogo_flow(tipo=preventa)`, admin `aceptar preventa` |
| **Actor** | Bodeguero (+ admin fuera del chat) |

---

## PRV-01 · Menú → preventa

| | |
|--|--|
| **Circa** | `list_reply` · menú |
| **Bodeguero** | Elige **Pedido / preventa** → flujo preventa (mismo entry que venta, URL `t=preventa`) |
| **Siguiente** | PRV-02 |

---

## PRV-02 · Catálogo preventa

| | |
|--|--|
| **Circa** | `cta_url` |
| **Mensaje** | ¡Sigamos con tu pre-venta! Entra al catálogo, arma tu lista y confírmala. |
| **Botón** | Abrir catálogo |
| **Bodeguero** | Arma carrito en web → `submit-cart` con `tipo_operacion=preventa` |
| **Siguiente** | PRV-03 |

---

## PRV-03 · Confirmada sin pago inmediato

| | |
|--|--|
| **Circa** | `text` — confirmación preventa (sin lista de pago) |
| **Bodeguero** | Lee confirmación |
| **Estado pedido** | `preventa_borrador` → `preventa_confirmada` |
| **Siguiente** | Espera admin (PRV-04) |

---

## PRV-04 · Admin acepta (notificación)

| | |
|--|--|
| **Circa** | `text` / notificación WA al bodeguero (estado actualizado) |
| **Actor admin** | Portal / API — no es bodeguero en chat |
| **Siguiente** | PRV-05 cuando admin aprueba |

---

## PRV-05 · Pagar mi preventa

| | |
|--|--|
| **Circa** | `list_reply` · menú con primera fila **Pagar mi preventa** si hay preventa pendiente |
| **Mensaje menú** | Tienes una preventa lista. ¿Qué deseas hacer? |
| **Bodeguero** | Toca `PAGAR_PREVENTA_{id}` |
| **Siguiente** | Mismo flujo que [PAY-01](./03-pago-whatsapp.md) |

Número pedido preventa: prefijo `PRV-*` (vs `CRC-*` venta).

[← Índice Figma](./README.md) · [Journey técnico](../04-preventa.md)
