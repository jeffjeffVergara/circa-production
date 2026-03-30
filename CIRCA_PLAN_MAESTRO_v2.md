# CIRCA — PLAN MAESTRO v2 (COMPLETO)
## WhatsApp Flows + Catálogo + Crédito Embebido + Cobranza
**Fecha:** 30 Marzo 2026
**Última actualización:** 30 Marzo 2026

---

## LAS 3 CAPAS DEL PRODUCTO

| Capa | Qué resuelve |
|---|---|
| **Conversación** | WhatsApp como interfaz principal |
| **Comercio** | Catálogo, carrito, pedido, tracking |
| **Crédito embebido** | Línea, financiamiento parcial, fee, plazo, pago, renovación |

---

## MÁQUINA DE ESTADOS

### Cuenta / Onboarding
```
invited → activation_started → ruc_verified → dni_received →
terms_accepted → pin_set → active → (suspended)
```

### Carrito
```
open → quoted → awaiting_pin → confirmed → (expired | cancelled)
```

### Pedido
```
received → preparing → in_transit → delivered → completed → (cancelled)
```

### Crédito / Línea
```
available → partially_used → fully_used → due → (overdue) → paid → released
```

---

## FLUJO COMPLETO: 30 PASOS

### ONBOARDING (Pasos 1-11) → WhatsApp Flow "ONBOARDING"

| # | Paso | Componente WhatsApp | Endpoint |
|---|---|---|---|
| 1 | Mensaje de oferta pre-aprobada | Quick Reply: "Sí, activar" / "Más info" | — |
| 2 | Ingreso de RUC | Flow: TextInput(number, 11 chars) | Valida RUC en Supabase |
| 3 | Confirmación datos del negocio | Flow: TextBody con razón social, dirección, rep. legal | — |
| 4 | Foto del DNI | **Fuera del Flow**: upload imagen en chat WhatsApp | Guarda en Supabase Storage |
| 5 | Confirmación DNI recibido | Mensaje texto | Marca dni_received |
| 6 | Términos y condiciones | Flow: TextBody con bullets + EmbeddedLink(PDF) | — |
| 7 | Aceptación de términos | Flow: Footer "Acepto los términos" | Guarda timestamp + versión contrato |
| 8 | Crear PIN | Flow: TextInput(PASSCODE, 4 dígitos) | — |
| 9 | Confirmar PIN | Flow: TextInput(PASSCODE, 4 dígitos) | Hashea y guarda en Supabase |
| 10 | Cuenta activada | Mensaje: "✅ Cuenta activa. Línea: S/500" | Estado → active |
| 11 | Menú principal | Quick Reply: PEDIDO / MI LÍNEA / MIS PEDIDOS | — |

**NOTA sobre DNI:** WhatsApp Flows NO soporta upload de imágenes. El DNI se pide como paso intermedio en el chat regular (fuera del Flow). El bot recibe la imagen, la guarda, y luego abre el Flow de términos+PIN.

### PEDIDO (Pasos 12-22) → WhatsApp Flow "CATALOGO"

| # | Paso | Componente WhatsApp | Endpoint |
|---|---|---|---|
| 12 | Categorías | Flow: NavigationList con categorías | Carga de Supabase |
| 13 | Productos por categoría | Flow: NavigationList con productos, precios, distribuidor | Filtra por categoría |
| 14 | Detalle: Pack | Flow: RadioButtonsGroup (6u/12u/24u con precios) | — |
| 15 | Detalle: Cantidad | Flow: Dropdown (1-10) | — |
| 16 | Item agregado | Flow: TextBody resumen + RadioButtons("Agregar más" / "Revisar") | Guarda en carrito Supabase |
| 17 | Carrito completo | Flow: TextBody con items + total + info línea | Calcula totals |
| 18 | ¿Financiar? | Flow: RadioButtons("Financiar" / "Pagar todo") | — |
| 19 | Monto a financiar | Flow: RadioButtons(100% / 50% / 25%) + TextBody contado | Calcula montos |
| 20 | Plazo | Flow: RadioButtons(7d/15d/30d) con fee y total | Motor de fees |
| 21 | Resumen final + PIN | Flow: TextBody resumen + TextInput(PASSCODE) | — |
| 22 | Confirmar pedido | Flow termina → mensaje en chat "✅ Pedido #CRC-XXX" | Operación atómica (ver abajo) |

**OPERACIÓN ATÓMICA al confirmar (Paso 22):**
1. Verificar PIN (hash)
2. Crear pedido en tabla `pedidos`
3. Crear items en tabla `items_pedido`
4. Crear financiamiento en tabla `financiamientos` (si aplica)
5. Descontar línea disponible
6. Registrar movimiento de línea
7. Notificar al distribuidor (WhatsApp o webhook)
8. Enviar confirmación al bodeguero
9. Crear schedule de recordatorios

### POST-COMPRA (Pasos 23-26) → Mensajes proactivos por WhatsApp

| # | Paso | Tipo mensaje | Trigger |
|---|---|---|---|
| 23 | Pedido recibido | Texto + botón "Ver estado" | Auto al confirmar |
| 24 | Armando pedido | Texto proactivo | Distribuidor cambia estado |
| 25 | En camino | Texto + "Llegada estimada X-Y pm" | Distribuidor cambia estado |
| 26 | Entregado | Texto + "Confirma entrega" | Distribuidor cambia estado |

### COBRANZA (Pasos 27-30) → Mensajes + Quick Replies

| # | Paso | Tipo mensaje | Endpoint |
|---|---|---|---|
| 27 | Instrucciones de pago | Texto: "Paga S/262.50 antes del 21 mar" + datos Yape | — |
| 28 | Recordatorios | Mensajes automáticos: D-5, D-3, D-1, D0, D+1, D+3, D+7 | Cron job |
| 29 | "Ya pagué" | Quick Reply → bot pide confirmación | Registra pago pendiente |
| 30 | Pago confirmado + línea renovada | "✅ Pago recibido. Línea renovada: S/500" | Cierra crédito, libera línea |

---

## REGLAS DE NEGOCIO CLAVE

1. **El carrito puede superar la línea** — no se bloquea, solo se financia hasta el máximo
2. **Financiamiento parcial** — 100%, 50%, 25% del monto financiable
3. **El dinero va al distribuidor** — la bodega nunca recibe efectivo
4. **PIN para toda operación financiada** — segundo factor obligatorio
5. **Línea revolving** — al pagar, la línea se restablece
6. **Múltiples distribuidores** — un carrito puede mezclar productos de varios
7. **Fee = interés simple** — fee = monto × tasa, pago único al vencimiento
8. **Monto financiable = min(total_pedido, línea_disponible)**
9. **Contado = total_pedido - monto_financiado**

---

## MODELO DE DATOS (Supabase)

### Tablas existentes (ya creadas)
- bodegas, distribuidores, catalogo, sesiones, carritos
- pedidos, items_pedido, pagos, eventos, recordatorios

### Tablas nuevas necesarias

**financiamientos**
```sql
CREATE TABLE financiamientos (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  pedido_id UUID REFERENCES pedidos(id),
  bodega_id UUID REFERENCES bodegas(id),
  monto_principal DECIMAL NOT NULL,
  tasa DECIMAL NOT NULL,
  fee DECIMAL NOT NULL,
  monto_total DECIMAL NOT NULL,
  plazo_dias INT NOT NULL,
  fecha_vencimiento DATE NOT NULL,
  estado TEXT DEFAULT 'activo', -- activo, vencido, pagado
  created_at TIMESTAMPTZ DEFAULT now()
);
```

**movimientos_linea**
```sql
CREATE TABLE movimientos_linea (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  bodega_id UUID REFERENCES bodegas(id),
  tipo TEXT NOT NULL, -- 'reserva', 'liberacion', 'pago'
  monto DECIMAL NOT NULL,
  financiamiento_id UUID REFERENCES financiamientos(id),
  disponible_antes DECIMAL,
  disponible_despues DECIMAL,
  created_at TIMESTAMPTZ DEFAULT now()
);
```

**contratos**
```sql
CREATE TABLE contratos (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  bodega_id UUID REFERENCES bodegas(id),
  version TEXT NOT NULL,
  aceptado_at TIMESTAMPTZ NOT NULL,
  canal TEXT DEFAULT 'whatsapp',
  metadata JSONB
);
```

---

## ENDPOINTS DE WhatsApp FLOWS

### Flow 1: ONBOARDING
**Endpoint:** `POST /flows/onboarding`
**Pantallas:** WELCOME → RUC → RUC_CONFIRM → TERMS → PIN_CREATE → PIN_CONFIRM

### Flow 2: CATALOGO
**Endpoint:** `POST /flows/catalogo`
**Pantallas:** CATEGORIAS → PRODUCTOS → DETALLE → AGREGADO → CARRITO → FINANCIAR → MONTO → PLAZO → RESUMEN_PIN

### Ambos endpoints requieren:
- Encriptación RSA (Meta envía datos encrypted)
- Llave privada RSA almacenada en Railway env var
- Respuesta con datos dinámicos para cada pantalla

---

## ARCHIVOS A CREAR

```
app/
├── flows/
│   ├── __init__.py
│   ├── crypto.py           ← RSA encrypt/decrypt para Meta
│   ├── onboarding.py       ← Endpoint Flow onboarding (6 pantallas)
│   ├── catalogo.py          ← Endpoint Flow catálogo (9 pantallas)
│   └── cobranza.py          ← Lógica de pagos y renovación línea
├── services/
│   ├── tracking.py          ← Estados del pedido + notificaciones
│   ├── financing.py         ← Motor de financiamiento (fee, plazo, vencimiento)
│   └── reminders.py         ← Scheduler de recordatorios de pago
```

---

## FASES DE EJECUCIÓN

### FASE 0: WABA Producción (1-3 días)
- [ ] Número peruano dedicado
- [ ] Twilio Self Sign-Up → WABA
- [ ] Meta Business verification
- [ ] Conectar webhook

### FASE 1: Infraestructura Flows (1 día)
- [ ] Generar llaves RSA
- [ ] Crear `crypto.py` para encrypt/decrypt
- [ ] Crear endpoint base `/flows/onboarding` y `/flows/catalogo`
- [ ] Registrar rutas en `main.py`
- [ ] Push + deploy

### FASE 2: Flow Onboarding (2-3 días)
- [ ] JSON del Flow (6 pantallas)
- [ ] Endpoint dinámico: validar RUC, hashear PIN
- [ ] Manejo de foto DNI (fuera del flow, en chat)
- [ ] Términos con link a PDF + timestamp
- [ ] Tabla `contratos`
- [ ] Subir Flow a WhatsApp Manager
- [ ] Content Template en Twilio
- [ ] Test end-to-end

### FASE 3: Flow Catálogo (3-5 días)
- [ ] JSON del Flow (9 pantallas)
- [ ] Endpoint dinámico: cargar productos, manejar carrito, calcular fees
- [ ] NavigationList con datos de Supabase
- [ ] Motor de financiamiento (`financing.py`)
- [ ] Operación atómica de confirmación
- [ ] Tabla `financiamientos` + `movimientos_linea`
- [ ] Subir Flow a WhatsApp Manager
- [ ] Content Template en Twilio
- [ ] Test end-to-end

### FASE 4: Post-compra y Cobranza (2-3 días)
- [ ] Estados del pedido + notificaciones proactivas
- [ ] Instrucciones de pago (Yape)
- [ ] Botón "Ya pagué" + confirmación
- [ ] Renovación de línea al pagar
- [ ] Recordatorios automáticos (D-5, D-3, D-1, D0, D+1, D+3, D+7)
- [ ] `tracking.py`, `cobranza.py`, `reminders.py`

### FASE 5: Integración (1-2 días)
- [ ] Actualizar `state_machine.py` para enviar Flows
- [ ] Actualizar `twilio_client.py`
- [ ] Eliminar templates viejos de botones
- [ ] Eliminar `static/catalogo.html` y `static/pin.html`

### FASE 6: Cleanup (1 día)
- [ ] Eliminar `/api/debug`
- [ ] Actualizar documentación
- [ ] Test completo de regresión

---

## TIMELINE ESTIMADO

| Fase | Días | Acumulado |
|---|---|---|
| Fase 0: WABA | 1-3 | 1-3 |
| Fase 1: Infra | 1 | 2-4 |
| Fase 2: Onboarding | 2-3 | 4-7 |
| Fase 3: Catálogo | 3-5 | 7-12 |
| Fase 4: Post-compra | 2-3 | 9-15 |
| Fase 5: Integración | 1-2 | 10-17 |
| Fase 6: Cleanup | 1 | 11-18 |

**Total estimado: 2-3 semanas**

---

## VARIABLES DE ENTORNO (Railway)

### Existentes
```
SUPABASE_URL, SUPABASE_SERVICE_KEY, APP_BASE_URL
TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_WHATSAPP_FROM
TWILIO_TEMPLATE_* (12 templates actuales)
PORT
```

### Nuevas
```
FLOW_ONBOARDING_ID=<Flow ID de WhatsApp Manager>
FLOW_CATALOGO_ID=<Flow ID de WhatsApp Manager>
FLOW_PRIVATE_KEY=<RSA private key PEM>
META_APP_SECRET=<Meta app secret>
WABA_ID=<WhatsApp Business Account ID>
YAPE_PHONE=<número para cobros>
YAPE_NAME=<nombre asociado a Yape>
```
