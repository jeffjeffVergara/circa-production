# Arquitectura — Circa Production

Documento técnico del backend **Circa MVP** (FastAPI): canales WhatsApp, WhatsApp Flows, persistencia y APIs auxiliares. Referencia de código: `app/main.py`, `app/config.py`, `app/services/`, `app/flows/`, `app/routes/`.

---

## 0. Diagramas en este documento

| Formato | Dónde se ve bien | Uso |
|---------|-------------------|-----|
| **Mermaid** (` ```mermaid `) | GitHub, GitLab, preview Markdown en Cursor/VS Code, Notion | Diagramas interactivos al hacer zoom en el preview |
| **ASCII** (secciones 0.1–0.2) | Cualquier editor, terminal, `less` | Misma idea que el diagrama Mermaid vecino, sin motor de render |

Si los bloques Mermaid aparecen como texto plano, cópialos en **[Mermaid Live Editor](https://mermaid.live)** y exporta SVG/PNG si necesitas incluirlos en presentaciones.

### 0.1 Contexto del sistema — ASCII (alto nivel)

```
                    +------------------+
                    |   Meta (WABA)    |
                    |  Graph + Webhook |
                    +--------+---------+
                             |
   +------------+            |             +----------------+
   | Bodeguero  |---WhatsApp-|             | FastAPI Circa |
   +------------+            |             |  (app/main)    |
                             +-------------+--------+-------+
   +------------+            |                      |
   | Twilio WA  |------------+                      v
   +------------+                          +--------+--------+
                                           |    Supabase    |
   +------------+                          +----------------+
   | API RUC/DNI|-------------------------+
   | (Perú)     |
   +------------+

   Distribuidor ----HTTPS API----> Circa (/api/distribuidor)
   Flow DDE -------HTTPS cifrado-> Circa (/flows/*)
```

### 0.2 Módulos dentro del proceso — ASCII (nivel medio)

```
  +------------------- app.main:app ----------------------+
  |  /webhook/meta  /webhook/twilio  /flows/*  /api/*     |
  +-------+-----------+-----------+-----------+----------+
          |           |           |           |
          v           v           v           v
   +------------+ +----------+ +-------+ +-----------+
   |meta_webhook| |state_    | |flows/ | |routes/    |
   |parse_incom.| |machine   | |crypto | |distribuidor|
   +------+-----+ +----+-----+ +---+---+ +-----+-----+
          |           |           |           |
          +-----------+-----------+-----------+
                              |
                              v
                    +---------+---------+
                    | app/services/db |
                    +---------+---------+
                              |
                              v
                         [ Supabase ]
```

---

## 1. Contexto de negocio (alto nivel)

Circa es una plataforma de **crédito embebido y pedidos** orientada a **bodegas en Perú**. Los usuarios interactúan principalmente por **WhatsApp**; el catálogo puede abrirse también en **web** dentro del cliente de WhatsApp. Los datos viven en **Supabase** (Postgres + API REST). Los mensajes salientes y el webhook principal usan la **Meta Cloud API**; existe un camino **Twilio** legacy.

---

## 2. Diagrama de contexto (alto nivel)

Actores y sistemas externos conectados a esta aplicación.

```mermaid
flowchart LR
  subgraph usuarios [Usuarios]
    B[Bodeguero WhatsApp]
    D[Distribuidor portal]
  end

  subgraph circa [Circa Backend FastAPI]
    API[App Circa]
  end

  subgraph meta [Meta]
    WABA[WhatsApp Business API]
    Flows[WhatsApp Flows runtime]
  end

  subgraph data [Datos]
    SB[(Supabase)]
  end

  subgraph legacy [Legacy]
    TW[Twilio WhatsApp]
  end

  subgraph peru [Validación Perú]
    PAPI[(API RUC/DNI)]
  end

  B --> WABA
  WABA --> API
  Flows <-->|HTTPS cifrado DDE| API
  B --> TW
  TW --> API
  D --> API
  API --> SB
  API --> PAPI
  API --> WABA
```

**Leyenda**

- **Meta**: webhook de mensajes + envío de interactivos, plantillas y Flows vía Graph API.
- **Flows runtime**: Meta invoca los endpoints `/flows/*` con payload cifrado (Dynamic Data Exchange).
- **Supabase**: fuente de verdad operativa (bodegas, pedidos, sesiones, catálogo, etc.).
- **Twilio**: webhook `/webhook/twilio` y envío por plantillas Content API (mismo dominio de negocio, otro transporte).

---

## 3. Diagrama de contenedores (nivel medio)

Componentes dentro del proceso FastAPI y fuera.

```mermaid
flowchart TB
  subgraph app [Proceso uvicorn app.main:app]
    MAIN[main.py rutas y orquestación]
    SM[state_machine.py]
    MC[meta_client.py]
    MW[meta_webhook.py]
    DB[db.py Supabase client]
    RT[routes/distribuidor.py]
    FL[flows: onboarding catalogo pin_flow]
    CR[crypto.py Flows]
    ID[identity.py]
    OT[services: cobranza tracking pin fees etc]
  end

  subgraph static [Estáticos montados]
    ST[static/ HTML catálogo pin admin]
  end

  MAIN --> SM
  MAIN --> MC
  MAIN --> MW
  MAIN --> DB
  MAIN --> FL
  MAIN --> RT
  FL --> CR
  FL --> DB
  FL --> ID
  SM --> DB
  MC --> META[(Graph API)]
  MW --> MAIN
  RT --> SBREST[(Supabase REST httpx)]
  DB --> SBSDK[(Supabase SDK)]
  MAIN --> ST
```

**Notas**

- **`main.py`**: concentra webhooks Meta/Twilio, endpoints `/flows/*`, APIs REST (`/api/*`), páginas legales y `FileResponse` a HTML estático.
- **`distribuidor`**: router propio con cliente HTTP directo a Supabase (además del cliente en `db.py`).
- **`state_machine.py`**: máquina de estados del chat para Twilio y, en parte, señales equivalentes vía Meta.

---

## 4. Flujos de mensajería (bajo nivel)

### 4.1 Entrada Meta (webhook)

```mermaid
sequenceDiagram
  participant M as Meta
  participant API as POST /webhook/meta
  participant P as parse_incoming
  participant H as handle_message / handlers botón
  participant DB as Supabase
  participant G as Graph API meta_client

  M->>API: JSON mensaje / interactivo / nfm_reply
  API->>P: parse_incoming body
  P-->>API: lista msgs normalizados
  alt Botón lista PEDIDO etc
    API->>G: send_catalogo_flow send_text ...
    API->>DB: lectura/escritura pedidos sesiones bodegas
  else nfm_reply Flow terminado
    API->>DB: PIN pedido contrato
    API->>G: send_text send_menu ...
  else Texto / estado
    API->>H: handle_message
    H->>DB: sesiones bodegas
    H-->>API: señales o strings
    API->>G: send_* según señal
  end
  API-->>M: 200 OK
```

**Puntos clave**

- `interactive.nfm_reply` → `flow_data` + `body` sintético `__FLOW_RESPONSE__` (`meta_webhook.py`).
- Botones `PEDIDO`, `ACEPTO`, `FIN*`, `PAY*`, etc. tratados en `main.py` antes o después de la máquina de estados según el caso.

### 4.2 WhatsApp Flows — Dynamic Data Exchange (DDE)

Meta → servidor cifrado; respuesta cifrada. Sin Graph API en este tramo.

```mermaid
sequenceDiagram
  participant F as WhatsApp Flow cliente
  participant M as Infra Meta
  participant API as POST /flows/onboarding|catalogo|pin
  participant C as crypto decrypt encrypt
  participant H as handle_* flow
  participant DB as Supabase

  F->>M: Usuario avanza pantalla
  M->>API: encrypted_flow_data encrypted_aes_key IV
  API->>C: decrypt_request
  C-->>API: flow_data AES key IV
  API->>H: handle_onboarding / catalogo / pin_flow
  H->>DB: RUC catálogo pedidos sesiones flow_sessions
  H-->>API: response_data dict
  API->>C: encrypt_response
  C-->>API: body cifrado
  API-->>M: PlainTextResponse cifrado
```

**Dependencias**: `FLOW_PRIVATE_KEY` (PEM RSA), `cryptography`, tablas y RPC acordes con cada handler (`app/flows/*.py`).

### 4.3 Abrir un Flow desde el chat (salida)

```mermaid
sequenceDiagram
  participant API as main o meta_client
  participant G as Graph API
  participant U as Usuario

  API->>G: POST messages interactive type flow
  G->>U: Mensaje con CTA Flow
  U->>U: Abre Flow embebido
```

Parámetros relevantes: `flow_id` (env, p. ej. `FLOW_PIN_ID` en `send_pin_request`), `flow_action` / `navigate`, `screen`, `data` inicial.

### 4.4 Twilio (legacy)

```mermaid
flowchart LR
  WA[WhatsApp vía Twilio]
  TW[POST /webhook/twilio]
  SM[state_machine]
  DISP[dispatch_signal]
  SEND[twilio_client plantillas]

  WA --> TW
  TW --> SM
  SM --> DISP
  DISP --> SEND
  SEND --> WA
```

El cuerpo del mensaje se arma con `ButtonPayload`, `ListReply`, etc. (`main.py`).

### 4.5 Catálogo web (complemento)

```mermaid
flowchart LR
  U[Usuario]
  HTML[static/catalogo*.html]
  SUB[POST /api/catalogo/submit-cart]
  DB[(Supabase pedidos)]
  META[Meta async notificación pago]

  U --> HTML
  HTML --> SUB
  SUB --> DB
  SUB --> META
```

El pedido en borrador y las opciones de pago enlazan con la misma lógica de negocio que el chat Meta.

### 4.6 Capas de software (bajo nivel)

Vista por capas del mismo proceso FastAPI.

```mermaid
flowchart TB
  subgraph capa_entrada [Entrada HTTP]
    R1["/webhook/meta"]
    R2["/webhook/twilio"]
    R3["/flows/*"]
    R4["/api/*"]
  end

  subgraph capa_app [Aplicación]
    ORQ[Orquestación main.py]
    SM[state_machine]
    FH[Flow handlers]
  end

  subgraph capa_dom [Dominio / integración]
    MC[meta_client]
    TW[twilio_client]
    ID[identity cobranza tracking pin]
  end

  subgraph capa_datos [Datos]
    DB[db.py SDK Supabase]
    RT[distribuidor httpx REST]
  end

  subgraph capa_ext [Externos]
    META[(Meta Graph)]
    SB[(Supabase)]
    EXT[(APIs Perú)]
  end

  R1 --> ORQ
  R2 --> ORQ
  R3 --> FH
  R4 --> ORQ
  ORQ --> SM
  ORQ --> MC
  ORQ --> FH
  FH --> DB
  SM --> DB
  MC --> META
  FH --> ID
  ID --> EXT
  DB --> SB
  RT --> SB
  ORQ --> RT
```

### 4.7 Onboarding Flow — pantallas (referencia `flow_onboarding.json`)

Navegación lógica entre pantallas del Flow; el endpoint dinámico la satisface con `handle_onboarding`.

```mermaid
stateDiagram-v2
  [*] --> RUC_INPUT: INIT
  RUC_INPUT --> RUC_CONFIRM: RUC válido
  RUC_CONFIRM --> TERMS: usuario confirma
  TERMS --> PIN_CREATE: acepta términos
  PIN_CREATE --> PIN_CONFIRM: PIN ingresado
  PIN_CONFIRM --> SUCCESS: confirmación
  SUCCESS --> [*]
  RUC_INPUT --> RUC_INPUT: error / reintento
```

### 4.8 Pago financiado — secuencia simplificada (Meta + PIN)

Después de elegir plazo en lista; alineado con handlers en `main.py` (sesión `pin_pago`, confirmación de pedido).

```mermaid
sequenceDiagram
  participant U as Usuario
  participant M as Meta
  participant API as main.py
  participant DB as Supabase
  participant G as meta_client

  U->>M: elige PAY7 / PAY15 / PAY30
  M->>API: list_reply id PAY*
  API->>DB: sesión fase pin_pago datos pedido
  API->>G: send_text resumen + send_pin_request verify
  G->>U: Flow o texto PIN
  U->>M: 4 dígitos PIN
  M->>API: texto o nfm_reply
  API->>DB: valida pin actualiza pedido confirmado
  API->>G: send_text confirmación
  G->>U: mensaje pedido CRC-xxx
```

### 4.9 Dependencias entre paquetes Python (bajo nivel)

Imports típicos entre módulos propios (no incluye `fastapi`, `httpx`, etc.).

```mermaid
flowchart BT
  main_py[app/main.py]
  sm[state_machine.py]
  mc[meta_client.py]
  mw[meta_webhook.py]
  db[db.py]
  fl_on[flows/onboarding.py]
  fl_cat[flows/catalogo.py]
  fl_pin[flows/pin_flow.py]
  cr[flows/crypto.py]
  idn[identity.py]
  rt[distribuidor.py router]

  main_py --> sm
  main_py --> mc
  main_py --> mw
  main_py --> db
  main_py --> fl_on
  main_py --> fl_cat
  main_py --> fl_pin
  main_py --> rt
  fl_on --> db
  fl_on --> idn
  fl_cat --> db
  fl_pin --> db
  main_py --> cr
  fl_on --> cr
  fl_cat --> cr
  fl_pin --> cr
  sm --> db
```

---

## 5. Modelo de datos lógico (bajo nivel, simplificado)

Entidades tocadas de forma recurrente (nombres según uso en código; el esquema exacto está en Supabase).

```mermaid
erDiagram
  bodegas ||--o{ pedidos : tiene
  bodegas ||--o{ sesiones : tiene
  bodegas }o--|| distribuidores : pertenece
  pedidos }o--|| distribuidores : ruteo
  catalogo_distribuidor }o--|| productos_circa : sku
  bodegas ||--o{ flow_sessions : opcional

  bodegas {
    uuid id
    string telefono_whatsapp
    string estado
    numeric linea_aprobada
    numeric linea_disponible
    uuid distribuidor_id
    string pin_hash
  }

  pedidos {
    uuid id
    uuid bodega_id
    uuid distribuidor_id
    string estado
    string items_json
    numeric monto_productos
    string numero
  }

  sesiones {
    string telefono
    string fase
    json datos
    uuid bodega_id
  }

  flow_sessions {
    uuid bodega_id
    json session_data
  }
```

**RPC**: `pin_flow.py` puede usar `db.sb.rpc("gen_numero_pedido")` según entorno.

---

## 6. Mapa de rutas HTTP (referencia rápida)

| Área | Rutas típicas |
|------|----------------|
| Salud / legales | `GET /api/health`, `/privacy`, `/terms`, `/data-deletion` |
| Twilio | `POST /webhook/twilio` |
| Meta | `GET|POST /webhook/meta` |
| Flows DDE | `POST /flows/onboarding`, `/flows/catalogo`, `/flows/pin` |
| Pedidos / bodegas / catálogo API | `GET/POST /api/pedidos*`, `/api/bodegas*`, `/api/catalogo*` |
| Cobranza | `POST /api/cobranza/*`, `GET /api/cobranza/*` |
| PIN web | `GET /pin`, `POST /api/pin/*` |
| Distribuidor | `/api/distribuidor/*` (header `X-API-Token`) |
| Estáticos | `GET /catalogo`, `/catalogo-v2`, `mount /static` |

---

## 7. Variables de entorno (agrupadas)

| Grupo | Variables (ejemplos en código) |
|-------|----------------------------------|
| Supabase | `SUPABASE_URL`, `SUPABASE_SERVICE_KEY` |
| Meta | `META_ACCESS_TOKEN`, `META_PHONE_NUMBER_ID`, `META_APP_SECRET`, `META_VERIFY_TOKEN`, `META_WABA_ID` |
| Flows | `FLOW_PRIVATE_KEY`, `FLOW_ONBOARDING_ID`, `FLOW_CATALOGO_ID`, `FLOW_PIN_ID` (PIN en `meta_client`) |
| App | `APP_BASE_URL` |
| Twilio | `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_WHATSAPP_FROM`, plantillas `TWILIO_TEMPLATE_*` |
| Identidad | `PERU_API_PROVIDER`, `PERU_API_TOKEN` |
| Pagos UX | `YAPE_PHONE`, `PLIN_PHONE`, `DISTRIBUIDOR_WA_NUMERO` |

Ver también `.env.example` (puede estar incompleto respecto a Meta/Flows; conviene alinearlo con `app/config.py`).

---

## 8. Despliegue y runtime

- **Proceso**: `Procfile` → `uvicorn app.main:app --host 0.0.0.0 --port $PORT`.
- **Contenedor**: `Dockerfile` (Python 3.12, mismo comando uvicorn).
- **Requisitos**: `requirements.txt` (FastAPI, uvicorn, supabase, httpx, cryptography, bcrypt, twilio, reportlab, etc.).

**Requisitos de red**: HTTPS público para webhooks Meta, Twilio (si aplica) y endpoints `/flows/*`.

---

## 9. Riesgos y duplicación conscientes

- **Dos clientes Supabase**: SDK en `db.py` vs REST en `routes/distribuidor.py` (mismos datos, distinta capa; revisar URLs y claves por entorno).
- **Meta + Twilio**: dos implementaciones del dominio conversacional; cambios de producto pueden requerir tocar ambos o priorizar solo Meta.
- **Catálogo**: Flow dinámico (`handle_catalogo`) vs página web (`catalogo-v2`); conviene documentar cuál es el canal oficial por entorno.

---

## 10. Referencias internas

- Planes de producto: `CIRCA_PLAN_MAESTRO_v2.md`, `CIRCA_PLAN_MAESTRO_WHATSAPP_FLOWS.md`.
- Definiciones JSON de Flow (referencia/import): `app/flows/flow_onboarding.json`, `app/flows/flow_catalogo.json`.

---

*Última actualización alineada con el árbol de código del repositorio Circa Production.*
