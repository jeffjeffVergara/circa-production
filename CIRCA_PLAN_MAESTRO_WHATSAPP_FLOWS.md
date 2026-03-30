# CIRCA — PLAN MAESTRO DE IMPLEMENTACIÓN
## WhatsApp Flows + Catálogo Nativo + PIN Enmascarado
**Fecha:** 30 Marzo 2026
**Estado:** Bot en producción, migrando a WhatsApp Flows

---

## RESUMEN EJECUTIVO

Migrar la experiencia actual (botones simples de Twilio) a una experiencia nativa rica usando WhatsApp Flows con Dynamic Endpoint. Todo vive DENTRO de WhatsApp sin abrir navegador.

**Herramienta principal:** WhatsApp Flows (JSON v7 + Dynamic Endpoint)

**Componentes clave:**
- `NavigationList` → catálogo de productos con imágenes, precios, tags
- `RadioButtonsGroup` → selección de packs (6u/12u/24u), montos, plazos
- `Dropdown` → cantidades
- `TextInput type=PASSCODE` → PIN enmascarado (••••) con teclado numérico
- `Dynamic Endpoint` → FastAPI en Railway carga datos de Supabase en tiempo real

---

## ESTADO ACTUAL (LO QUE YA TENEMOS)

| Componente | Estado | Detalle |
|---|---|---|
| FastAPI en Railway | ✅ Online | circa-production-c517.up.railway.app |
| Supabase | ✅ Conectado | 11 tablas, JWT key funcionando |
| Twilio Sandbox | ✅ Bot responde | 12 Content Templates con botones |
| State Machine | ✅ 13 fases | handle_message() en state_machine.py |
| Catálogo HTML | ✅ Existe | static/catalogo.html (se reemplaza) |
| PIN HTML | ✅ Existe | static/pin.html (se reemplaza) |
| GitHub | ✅ Auto-deploy | palisacpe-crypto/circa-production → Railway |

---

## FASES DE IMPLEMENTACIÓN

### FASE 0: PREPARAR WABA EN PRODUCCIÓN
**Duración estimada:** 1-3 días (incluye aprobación de Meta)
**Bloqueador:** Sin WABA no podemos usar WhatsApp Flows

**Pasos:**
1. **Twilio Console → WhatsApp Senders → Self Sign-Up**
   - Registrar un número peruano dedicado para Circa
   - Necesitas un número que NO esté en WhatsApp personal
   - Puede ser un número Bitel/Entel/Claro prepago
2. **Verificación de negocio en Meta Business Manager**
   - Ir a business.facebook.com
   - Crear o verificar "Hermanas Gelato SAC" (o crear una entidad nueva para Circa)
   - Subir documentos: RUC, DNI del representante
   - Meta aprueba en 1-3 días laborales
3. **Conectar WABA a Twilio**
   - El Self Sign-Up guía este proceso
   - Al final tendrás un número WhatsApp propio
4. **Actualizar webhook en Twilio**
   - Apuntar el nuevo número a: `https://circa-production-c517.up.railway.app/webhook/twilio`
5. **Verificar que el bot responde** con el nuevo número

**Entregable:** Número WhatsApp propio funcionando con el bot actual (botones)

---

### FASE 1: FLOW DE ONBOARDING (PIN + REGISTRO)
**Duración estimada:** 2-3 días
**Prioridad:** Alta (el PIN enmascarado es crítico)

**Flow JSON — 6 pantallas:**

```
ONBOARDING_FLOW:
├─ Screen 1: WELCOME
│   - TextBody: "Tienes línea pre-aprobada de S/500"
│   - Footer: "Activar cuenta →"
│
├─ Screen 2: RUC_INPUT
│   - TextInput(name="ruc", inputType="number", maxLength=11)
│   - TextBody: "Ingresa tu RUC (11 dígitos)"
│   → Endpoint valida RUC contra Supabase
│   → Responde con razón social para confirmar
│
├─ Screen 3: RUC_CONFIRM
│   - TextBody: "{{razon_social}} - RUC {{ruc}}"
│   - TextBody: "¿Son correctos estos datos?"
│   - Footer: "Sí, continuar →"
│
├─ Screen 4: DNI_INPUT
│   - TextInput(name="dni", inputType="number", maxLength=8)
│   - TextBody: "DNI del representante legal"
│
├─ Screen 5: PIN_CREATE
│   - TextInput(name="pin", inputType="PASSCODE", maxLength=4)
│   - TextBody: "Crea tu clave Circa de 4 dígitos"
│   - TextBody: "Tu clave se muestra como ••••"
│
├─ Screen 6: PIN_CONFIRM
│   - TextInput(name="pin_confirm", inputType="PASSCODE", maxLength=4)
│   - TextBody: "Confirma tu clave Circa"
│   → Endpoint: hashea PIN, activa bodega en Supabase
│   → Flow termina, vuelve al chat con mensaje de bienvenida
```

**Endpoint necesario en FastAPI:**
- `POST /flows/onboarding` — recibe datos de cada pantalla, valida, responde con siguiente pantalla
- Encriptación RSA requerida (Meta envía datos encriptados)

**Archivos a crear/modificar:**
- `app/flows/onboarding.py` — lógica del endpoint
- `app/flows/crypto.py` — encriptación/desencriptación RSA
- `app/main.py` — registrar ruta `/flows/onboarding`
- WhatsApp Manager — crear Flow con JSON

---

### FASE 2: FLOW DE CATÁLOGO (PEDIDO)
**Duración estimada:** 3-5 días
**Prioridad:** Alta (es la experiencia core)

**Flow JSON — 7+ pantallas:**

```
CATALOGO_FLOW:
├─ Screen 1: CATEGORIAS
│   - NavigationList(items=[
│       {title:"Bebidas", description:"Coca-Cola, Inca Kola...", image:"🥤"},
│       {title:"Lácteos", description:"Gloria, Laive...", image:"🥛"},
│       {title:"Abarrotes", description:"Ariel, Azúcar...", image:"🛒"},
│       {title:"Cuidado", description:"H&S, Pantene...", image:"🧴"},
│     ])
│   → Al tocar categoría → navega a PRODUCTOS con payload
│
├─ Screen 2: PRODUCTOS (dinámico por categoría)
│   - NavigationList(items=[
│       {title:"Coca-Cola 500ml", description:"DistribuMax",
│        end:{title:"S/9.60", description:"desde"}},
│       {title:"Inca Kola 500ml", ...},
│     ])
│   → Endpoint carga productos de Supabase filtrado por categoría
│   → Al tocar producto → navega a DETALLE
│
├─ Screen 3: DETALLE_PRODUCTO
│   - TextHeading: "{{nombre_producto}}"
│   - TextBody: "{{distribuidor}} · {{categoria}}"
│   - RadioButtonsGroup(name="pack", items=[
│       {id:"6", title:"Pack 6 — S/9.60"},
│       {id:"12", title:"Pack 12 — S/18.00"},
│       {id:"24", title:"Pack 24 — S/34.00"},
│     ])
│   - Dropdown(name="cantidad", items=["1","2","3","4","5"])
│   - Footer: "Agregar al carrito →"
│   → Endpoint agrega item al carrito en Supabase
│
├─ Screen 4: ITEM_AGREGADO
│   - TextBody: "✅ Agregado: {{qty}}x Pack {{pack}} {{nombre}}"
│   - TextBody: "Carrito: {{total_items}} packs · S/{{total}}"
│   - RadioButtonsGroup(name="accion", items=[
│       {id:"mas", title:"+ Agregar más productos"},
│       {id:"revisar", title:"🛒 Revisar carrito"},
│     ])
│   → "mas" → vuelve a CATEGORIAS
│   → "revisar" → navega a CARRITO
│
├─ Screen 5: CARRITO
│   - TextHeading: "Tu carrito"
│   - TextBody: "{{items_detalle}}"   ← generado por endpoint
│   - TextBody: "TOTAL: S/{{total}}"
│   - TextBody: "💚 Línea: S/{{linea}}. Financias hasta S/{{financiable}}"
│   - RadioButtonsGroup(name="accion", items=[
│       {id:"financiar", title:"💚 Financiar con Circa"},
│       {id:"agregar", title:"+ Agregar más"},
│       {id:"vaciar", title:"🗑 Vaciar carrito"},
│     ])
│
├─ Screen 6: MONTO_FINANCIAR
│   - RadioButtonsGroup(name="pct", items=[
│       {id:"100", title:"100% — S/{{financiable}}"},
│       {id:"50", title:"50% — S/{{mitad}}"},
│       {id:"25", title:"25% — S/{{cuarto}}"},
│     ])
│   - TextBody: "Resto S/{{contado}} al contado"
│   - Footer: "Continuar →"
│
├─ Screen 7: PLAZO
│   - RadioButtonsGroup(name="plazo", items=[
│       {id:"7", title:"7 días — Fee S/{{fee7}} — Total S/{{total7}}"},
│       {id:"15", title:"15 días — Fee S/{{fee15}} — Total S/{{total15}}"},
│       {id:"30", title:"30 días — Fee S/{{fee30}} — Total S/{{total30}}"},
│     ])
│   - Footer: "Confirmar →"
│
├─ Screen 8: PIN_CONFIRM
│   - TextBody: "Resumen: {{plazo}}d, Fee S/{{fee}}, Total S/{{total_credito}}"
│   - TextInput(name="pin", inputType="PASSCODE", maxLength=4)
│   - TextBody: "🔐 Ingresa tu clave Circa"
│   - TextBody: "⏱ 5 minutos para confirmar"
│   - Footer: "Confirmar pedido 🔐"
│   → Endpoint: valida PIN, crea pedido en Supabase
│   → Flow termina → mensaje de confirmación en chat
```

**Endpoint necesario en FastAPI:**
- `POST /flows/catalogo` — maneja TODAS las pantallas del catálogo
  - Recibe: screen_id + datos del usuario
  - Responde: datos para la siguiente pantalla
  - Operaciones: leer catálogo, manejar carrito, calcular fees, validar PIN, crear pedido

**Archivos a crear/modificar:**
- `app/flows/catalogo.py` — lógica completa del catálogo
- `app/main.py` — registrar ruta `/flows/catalogo`
- WhatsApp Manager — crear Flow con JSON

---

### FASE 3: INTEGRACIÓN Y ENVÍO DE FLOWS
**Duración estimada:** 1-2 días

**Pasos:**
1. Crear Content Templates en Twilio que apunten a los Flows
2. Modificar `state_machine.py` para enviar Flows en vez de botones
3. Modificar `twilio_client.py` para enviar mensajes con Flow
4. Testing end-to-end

**Mapeo de señales actuales → Flows:**

| Señal actual | Acción nueva |
|---|---|
| MENU (quick-reply) | Mantener como quick-reply (PEDIDO/LINEA/ESTADO) |
| PEDIDO → CATEGORIAS → PRODUCTOS... | Enviar CATALOGO_FLOW |
| welcome → reg_ruc → reg_dni → pin... | Enviar ONBOARDING_FLOW |

---

### FASE 4: CLEANUP Y PRODUCCIÓN
**Duración estimada:** 1 día

1. Eliminar `/api/debug` endpoint
2. Eliminar `static/catalogo.html` y `static/pin.html`
3. Eliminar Content Templates viejos de Twilio (los 12 de botones)
4. Actualizar `CIRCA_CONTEXTO_COMPLETO.md` con nuevo estado

---

## ARQUITECTURA FINAL

```
Usuario WhatsApp
     │
     ├── Mensaje de texto → Twilio Webhook → Railway/FastAPI
     │                                            │
     │                                     state_machine.py
     │                                            │
     │                                   ┌────────┴────────┐
     │                                   │                  │
     │                            "PEDIDO"            "Texto libre"
     │                                   │                  │
     │                         Envía Flow            Respuesta texto
     │                         (Content API)
     │
     ├── WhatsApp Flow (overlay nativo)
     │        │
     │        ├── Pantalla 1,2,3... ←→ /flows/catalogo (FastAPI)
     │        │                              │
     │        │                         Supabase
     │        │                    (productos, carrito,
     │        │                     sesiones, pedidos)
     │        │
     │        └── Flow termina → datos enviados al webhook
     │
     └── Confirmación en chat
```

---

## VARIABLES DE ENTORNO NUEVAS (a agregar en Railway)

```
FLOW_ONBOARDING_ID=<ID del Flow en WhatsApp Manager>
FLOW_CATALOGO_ID=<ID del Flow en WhatsApp Manager>
FLOW_PRIVATE_KEY=<RSA private key para encriptación>
META_APP_SECRET=<App secret de Meta>
```

---

## ARCHIVOS NUEVOS A CREAR

```
app/
├── flows/
│   ├── __init__.py
│   ├── crypto.py          ← Encriptación RSA para Dynamic Endpoint
│   ├── onboarding.py      ← Endpoint para Flow de onboarding
│   └── catalogo.py        ← Endpoint para Flow de catálogo
```

---

## COSTO MENSUAL ESTIMADO

| Servicio | Costo |
|---|---|
| Railway (FastAPI) | ~$5/mes |
| Supabase Pro | $25/mes |
| Twilio WhatsApp | ~$15-25/mes (por mensaje) |
| **Total** | **~$45-55/mes** |

---

## ORDEN DE EJECUCIÓN (HOY)

1. ☐ Registrar número WhatsApp en Twilio (Self Sign-Up)
2. ☐ Iniciar verificación Meta Business Manager
3. ☐ Mientras Meta aprueba: construir endpoints en FastAPI
4. ☐ Crear Flow JSON para onboarding
5. ☐ Crear Flow JSON para catálogo
6. ☐ Generar llaves RSA para encriptación
7. ☐ Subir Flows a WhatsApp Manager
8. ☐ Crear Content Templates en Twilio
9. ☐ Actualizar state_machine.py
10. ☐ Testing completo
11. ☐ Cleanup y documentación
