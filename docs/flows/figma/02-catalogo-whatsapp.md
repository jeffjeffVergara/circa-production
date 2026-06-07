# 02 — Catálogo y pedido WhatsApp (spec Figma)

| | |
|--|--|
| **Figma** | [Wireframes — página 03 Catalogo](https://www.figma.com/design/8uXIOxgppRe67aNbThSyv6) · Flowchart [Circa - Bodeguero](https://www.figma.com/board/S3d80RJeYAIuuyGz9V9Qk0) |
| **Escenarios** | CAT-01 … CAT-09 |
| **Código** | `meta_client.send_menu`, `send_catalogo_flow`, `POST /api/catalogo/submit-cart` |
| **Actor** | Bodeguero (cuenta activa) |

**Prerrequisito:** onboarding completo → `sesiones.fase = menu`.

---

## CAT-01 · Menú → pedido

| | |
|--|--|
| **Circa** | `list_reply` · `send_menu` |
| **Mensaje** | ¿Qué deseas hacer? |
| **Bodeguero** | Abre lista → elige **Pedido / preventa** (`id: PEDIDO`) |
| **Siguiente** | CAT-02 |

Alternativas desde menú: `VER_PROMOS`, `REPETIR`, `LINEA`, `ESTADO` → otros journeys.

---

## CAT-02 · Link catálogo web (venta)

| | |
|--|--|
| **Circa** | `cta_url` · `send_catalogo_flow(tipo=venta)` |
| **Mensaje** | ¡Vamos con tu pedido! Abre el catálogo, busca por nombre o marca, elige cantidades y confírmalo. |
| **Botón CTA** | Abrir catálogo → URL `/catalogo-v2?b={bodega_id}&t=venta` |
| **Bodeguero** | Toca **Abrir catálogo** — navega en web in-app WhatsApp |
| **Siguiente** | CAT-03 (web, no chat) |

Variantes:

| Escenario | Parámetro URL | Copy CTA |
|-----------|---------------|----------|
| CAT-07 REPETIR | `repeat=1` | «Ya te cargamos tu último pedido…» |
| CAT-09 EDITAR | `edit=1` | Desde lista de pago |
| PRV-01 preventa | `t=preventa` | «¡Sigamos con tu pre-venta!…» → [04-preventa](./04-preventa-whatsapp.md) |

---

## CAT-03 · Carrito web (fuera del chat)

Interacción en `catalogo_v2.html` — no es burbuja WhatsApp. El bodeguero:

1. Busca productos y promos
2. Ajusta cantidades / packs
3. Toca confirmar → `submit-cart`

| | |
|--|--|
| **Bodeguero** | Confirma carrito en web |
| **Backend** | Crea `pedidos` borrador, routing DIMAX/Zoom (CAT-04) |
| **Siguiente** | [PAY-01](./03-pago-whatsapp.md) (venta) o PRV-02 (preventa) |

---

## CAT-04 · Routing (sistema, sin mensaje)

| Bodega | `distribuidor_id` |
|--------|-------------------|
| `es_test=true` | Zoom |
| Real | DIMAX |

Mostrar en Figma como nota de sistema, no como chat.

---

## Resumen interacciones

| Pantalla | Actor | Tipo | Input bodeguero |
|----------|-------|------|-----------------|
| Menú | Circa → Bodeguero | list_reply | Fila `PEDIDO` |
| CTA catálogo | Circa → Bodeguero | cta_url | Tap Abrir catálogo |
| Catálogo web | Bodeguero | web | Tap productos, confirmar |
| Post-submit | Sistema | — | → opciones pago |

[← Índice Figma](./README.md) · [Journey técnico](../02-catalogo-pedido.md)
