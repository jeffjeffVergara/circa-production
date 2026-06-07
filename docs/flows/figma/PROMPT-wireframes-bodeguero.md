# Prompt — Wireframes flujo bodeguero (WhatsApp Business real)

Copia el bloque **PROMPT** abajo en Figma Make, agente MCP o chat con contexto del repo.

---

## PROMPT (copiar desde aquí)

```
Eres un diseñador de producto especializado en WhatsApp Business (Meta Cloud API). Crea wireframes de ALTA FIDELIDAD del journey completo del BODEGUERO en Circa — no son sketches: deben verse como capturas reales de WhatsApp Business en iOS, con tipografía, colores, espaciado y componentes nativos de la app.

## Contexto del producto
Circa es crédito embebido para bodegas en Perú. El bodeguero opera casi todo por WhatsApp con la cuenta Business verificada "Circa". Canal: Meta WhatsApp Cloud API (NO Twilio).

## Fuente de verdad (obligatorio)
Lee y sigue al pie de la letra:
- docs/flows/figma/README.md (guía maestra)
- docs/flows/figma/onboarding-screens.yaml (onboarding pantalla por pantalla)
- docs/flows/figma/01-onboarding-whatsapp.md … 05-postventa-whatsapp.md
- Copy real en app/services/meta_client.py y app/state_machine.py

NO inventes textos, botones ni flujos. Si falta copy, usa el YAML/spec.

## Archivo Figma destino
Design file key: 8uXIOxgppRe67aNbThSyv6
Crea o mejora páginas:
- 02 Conversacion completa (onboarding 01→16 + E01→E06) — elevar fidelidad visual
- 03 Catalogo, 04 Pago, 05 Preventa, 06 Postventa — estilo WhatsApp Business real

## Estilo visual — WhatsApp Business (iOS)
Replica fielmente la UI oficial:

### Shell móvil
- Viewport: 390 × 844 px (iPhone 14 lógico)
- Status bar iOS (hora, señal, batería) opcional arriba
- NO uses wireframe gris/plano; usa colores reales de WhatsApp

### Header de chat (Business)
- Fondo: #075E54 (teal WhatsApp)
- Avatar circular izquierda (logo Circa o inicial "C")
- Título: "Circa" — Semibold 17px, blanco
- Subtítulo: "Cuenta comercial verificada" o "en línea" — 13px, #ECE5DD con opacidad
- Iconos derecha: videollamada, llamada (opcional, decorativos)

### Área de conversación
- Fondo chat: patrón sutil beige (#ECE5DD / #D1C7BC) o color sólido #ECE5DD
- Burbuja SALIENTE (Circa/bot): #D9FDD3, esquina inferior izquierda recta, radius 8px, sombra muy sutil
- Burbuja ENTRANTE (bodeguero): #FFFFFF, esquina inferior derecha recta, alineada a la derecha
- Texto mensaje: #111B21, 15px, line-height ~20px, fuente sistema (SF Pro / Roboto)
- Timestamp: 11px #667781, abajo derecha dentro de burbuja
- Doble check azul #53BDEB en mensajes leídos del bot (opcional)

### Componentes interactivos Meta (críticos — deben verse reales)

1. **button_reply** (hasta 3 botones)
   - Card blanca pegada bajo burbuja, full width del mensaje
   - Texto botón: #008069, 15px, centrado
   - Separador horizontal #E9EDEF 1px entre botones
   - Icono reply ↩ pequeño opcional

2. **list_reply**
   - Botón "Ver opciones" verde #008069 en card blanca
   - Al expandir (frame siguiente o estado): sheet blanco con filas
   - Cada fila: título 16px bold + descripción 14px #667781
   - Separadores entre filas

3. **cta_url**
   - Burbuja texto + botón full-width "Abrir catálogo" #008069
   - Icono link externo ↗

4. **flow** (WhatsApp Flow)
   - Botón "Crear clave" / "Ingresar clave" estilo CTA verde
   - Nota: el Flow nativo es pantalla Meta — indicar con badge "Flow nativo"

5. **image** inbound
   - Thumbnail 200×130 con radius 8, caption "Foto DNI" / "Selfie"

6. **loading / typing**
   - Burbuja gris con tres puntos animados o texto "··· Verificando RUC en SUNAT…"
   - Indicador "escribiendo..." en header (opcional)

### Capa de diseño (solo Figma, fuera del chat)
Debajo de cada frame de teléfono, NO dentro del mockup WhatsApp:
- Badge diseño: ID escenario (ej. CAT-01 · send_menu · reg_ruc)
- Caja azul claro #E7F3FF: "Respuesta esperada del bodeguero: [acción concreta]"
- Onboarding: barra progreso 4 pasos (#25D366 activo, #E0E0E0 inactivo)

## Journeys a wireframear (orden)

### 1. Onboarding (22 frames)
Happy path 01→16 + errores E01→E06. Ver onboarding-screens.yaml.
Progreso: 1 Verificar negocio · 2 Identidad · 3 Activación · 4 Contrato y clave

Datos demo fijos:
- Bodega: Bodega El Sol · DIMAX · línea S/500
- RUC 20123456789 · BODEGA EL SOL SAC · Juan Pérez · DNI 45678901

### 2. Catálogo (CAT-01, CAT-02, CAT-03, CAT-07)
Menú → Pedido/preventa → CTA catálogo → nota web catálogo v2 → repetir pedido

### 3. Pago (PAY-09, PAY-01, PAY-02, PAY-07, PAY-E01)
Delay 2s → resumen pedido + lista pago → PIN Flow → confirmación → error PIN

### 4. Preventa (PRV-01, PRV-02, PRV-03, PRV-05)
CTA preventa → confirmación sin pago → menú "Pagar mi preventa"

### 5. Postventa (POS-01 … POS-05)
ESTADO pedidos · LINEA crédito · PAGUE · recordatorio cron · pago verificado

## Component library (crear primero)
Antes de pantallas, define componentes reutilizables:
- Phone/Shell-iOS-390
- Chat/Bubble-Out (Circa)
- Chat/Bubble-In (Bodeguero)
- Chat/ButtonReply-1|2|3
- Chat/ListReply-Closed|Open
- Chat/CtaUrl
- Chat/FlowButton
- Chat/ImageInbound
- Chat/TypingIndicator
- Meta/ProgressBar-4steps
- Annotation/ScenarioBadge
- Annotation/ActionHint

## Reglas de entrega
1. Un frame = un momento del chat (estado UI concreto)
2. Nombre frame: "{ID} {Título}" — ej. "PAY-01 Opciones pago"
3. Layout horizontal en canvas: flujo izquierda → derecha por journey
4. NO conectar journeys distintos con flechas en un solo canvas
5. NO usar estilo wireframe low-fi (cajas grises X); debe parecer WhatsApp real
6. Emojis: incluir solo si están en meta_client.py (🛒 💵 etc. en menú y pago)
7. Accesibilidad: contraste WCAG en textos sobre #D9FDD3 y #075E54

## Prioridad
1. Crear component library WhatsApp Business
2. Refinar "02 Conversacion completa" a alta fidelidad
3. Refinar 03–06 con mismo sistema
4. Exportar variantes de lista de menú y opciones de pago expandidas

Empieza inspeccionando frames existentes en el file 8uXIOxgppRe67aNbThSyv6 y reemplázalos/mejóralos manteniendo IDs y copy del spec.

```

---

## Variante corta (un solo journey)

```
Crea wireframes ALTA FIDELIDAD estilo WhatsApp Business iOS para el journey [ONBOARDING | CATÁLOGO | PAGO | PREVENTA | POSTVENTA] del bodeguero Circa.

File Figma: 8uXIOxgppRe67aNbThSyv6
Spec: docs/flows/figma/0X-*-whatsapp.md + onboarding-screens.yaml si aplica
Copy: meta_client.py — no inventar

Estilo real WA Business: header #075E54, burbujas #D9FDD3/#FFFFFF, fondo #ECE5DD, botones reply #008069, list_reply con sheet, cta_url, Flow CTA.
390px ancho. Componentes reutilizables. Badge escenario + caja azul "Respuesta esperada" fuera del mockup.
Frames nombrados CAT-01, PAY-01, etc. Datos demo: Bodega El Sol, DIMAX, RUC 20123456789.
```
