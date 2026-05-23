# 09 — Legacy (Twilio y Flows chat)

| | |
|--|--|
| **Figma** | *[opcional — solo referencia histórica]* |
| **Escenarios** | LEG-01, LEG-02, CAT-05, CAT-06 |
| **Estado** | Producción actual = **Meta Cloud API** (LEG-02) |

## Qué sigue activo

| Componente | Estado | Notas |
|------------|--------|-------|
| `POST /webhook/meta` | ✅ Prod | Canal principal |
| `meta_client.send_menu` | ✅ Prod | Menú lista interactiva |
| `POST /webhook/twilio` | ⛔ Legacy | Mantener solo si hay número Twilio |
| Carrito por chat (`fase=catalogo*`) | ⛔ | Sustituido por `catalogo_v2` web |
| `POST /flows/catalogo` | 🟡 | Flow JSON; uso secundario |
| `POST /flows/onboarding` | 🟡 | Paralelo a chat texto |

## Referencia histórica

Plan original de migración a Flows: [`CIRCA_PLAN_MAESTRO_WHATSAPP_FLOWS.md`](../../CIRCA_PLAN_MAESTRO_WHATSAPP_FLOWS.md)

No invertir en wireframes Twilio salvo que se reactive el canal.

[← Índice](./README.md)
