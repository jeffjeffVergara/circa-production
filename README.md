<div align="center">

[![Circa](docs/circa-logo.png)](https://circa.pe/)

**Circa — infraestructura para el crecimiento de los negocios en LATAM**  
[Más sobre Circa](https://circa.pe/) · *Compra hoy. Paga después.*

</div>

---

## Qué es este repositorio

Backend **MVP** de **Circa**: crédito embebido orientado a **bodegas en Perú**. El dueño de la bodega opera casi todo por **WhatsApp** (Meta Cloud API y WhatsApp Flows), con **FastAPI** y datos en **Supabase**.

## Arquitectura principal

| Pieza | Rol |
| --- | --- |
| `app/main.py` | App FastAPI: webhook Meta, flows cifrados, APIs REST, páginas estáticas (`/catalogo`, `/pin`), salud y textos legales. |
| `app/state_machine.py` | Máquina de estados del chat (`handle_message`): sesión en BD, fases (bienvenida, RUC/DNI, menú, carrito, etc.) y señales a `meta_client`. |
| `app/services/` | Negocio: `db`, `meta_client`, identidad (RUC/DNI), tracking, cobranza, contratos, PIN, fees, etc. |
| `app/routes/distribuidor.py` | API del distribuidor (token) para pedidos y estados. |
| `app/flows/` | Handlers de **WhatsApp Flows** (onboarding, catálogo, PIN) y cifrado (`crypto`). |
| `static/` | HTML del catálogo web, PIN, admin distribuidor y **backoffice** (`/backoffice`). |

## Flujo de negocio (resumido)

1. Bodega preaprobada entra por WhatsApp → **onboarding** (datos, contrato, validaciones) → **PIN** → cuenta **activa**.
2. **Catálogo** (Flow o web) → pedido en **borrador** → **contado o financiación** (plazos y fees) → confirmación con **PIN**.
3. Distribuidor/backoffice actualiza estados; hay **cobranza** y endpoints para vencimientos y recordatorios.

## Configuración y ejecución

Variables en `.env` (ver `.env.example`). Referencia en `app/config.py`: Supabase, Meta, IDs de flows, APIs Perú, etc.

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

Para exponer el webhook (desarrollo): túnel tipo `ngrok http 8000` y configurar la URL en Meta Developer Console (`/webhook/meta`).

## Documentación interna

| Documento | Contenido |
|-----------|-----------|
| [**Estados por journey**](docs/JOURNEY_ESTADOS.md) | **Guía de estados:** onboarding, venta, preventa, cobranza, vendedor WA, diagramas |
| [`docs/flows/README.md`](docs/flows/README.md) | **Mapa de flujos**, matriz de escenarios (~50), smoke P0 |
| [`docs/flows/figma/README.md`](docs/flows/figma/README.md) | **Guía Figma:** wireframes, diagramas, componentes, journeys funcional + técnico |
| [`arquitectura.md`](arquitectura.md) | Arquitectura técnica, diagramas Mermaid |
| `CIRCA_PLAN_MAESTRO_v2.md`, `CIRCA_PLAN_MAESTRO_WHATSAPP_FLOWS.md` | Planes históricos de producto |

## Logo

El archivo `docs/circa-logo.png` corresponde al logo embebido en la web pública [circa.pe](https://circa.pe/) (misma marca; útil para README y vistas offline).

---

© Circa / Pali S.A.C. — ver términos y privacidad expuestos en la API (`/terms`, `/privacy`) cuando aplique.
