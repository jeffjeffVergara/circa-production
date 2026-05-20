# CIRCA — Documento de Referencia Técnica

**Última actualización:** Abril 22, 2026 — 8:45am (sprint promociones DIMAX)
**Owner:** Paola Velarde (Pali SAC)
**Colaborador dev:** Jeff Vergara
**Estado del proyecto:** MVP en producción, 2 distribuidores activos, iteraciones constantes

> **PARA EL CLAUDE QUE LEA ESTO:** Este documento contiene el estado real verificado de la DB y arquitectura. Usa este documento como fuente de verdad antes de escribir SQL o código. NO asumas nombres de columnas ni relaciones — todo está verificado aquí contra Supabase real. Si algo cambió, actualiza esta sección antes de proceder.

---

## 1. CONTEXTO DEL NEGOCIO

**Circa** es una plataforma de crédito embebido para bodegas en Perú que opera 100% sobre WhatsApp. Conecta:

- **Bodegas** (clientes finales) que piden a crédito
- **Distribuidores** (Zoom Corp, DIMAX Corp) que despachan productos
- **Circa** (intermediario) que financia y gestiona el flujo

Flujo: bodeguero abre WhatsApp → catálogo → carrito → elige % financiamiento → confirma con PIN → distribuidor recibe → despacha → bodeguero paga → Circa verifica → línea revolving se restaura.

**Modelo de ingresos:** fee flat 3/5/7% según plazo (7/15/30 días), mínimo S/3 (antes era S/5, cambió sprint 16-20 abril).

---

## 2. STACK Y ACCESOS

| Componente | Detalle |
|---|---|
| Backend | FastAPI (Python 3.12) |
| DB | Supabase PostgreSQL (project `rhxqcoijzgqlecpdfhde`) |
| Hosting | Railway (Docker) — `circa-production-c517.up.railway.app` |
| Repo | GitHub `palisacpe-crypto/circa-production` |
| WhatsApp | Meta Cloud API (WABA `965950269106934`, phone_id `1076586305533033`, número +51 986 311 567) |
| Flows | Catálogo `1892378058074435`, PIN `3540248792797525` |
| Identidad | ApiInti (SUNAT + RENIEC) + Claude Vision |
| Tarjetas visuales | HCTI API (htmlcsstoimage.com) |

**Proyecto local:** `~/Projects/circa-deploy-temp`
**Deploy:** `git push origin main` + `railway up --detach`

---

## 3. ESQUEMAS REALES DE LA DB (VERIFICADOS)

### 3.1 `distribuidores`
```
id                    uuid PRIMARY KEY default uuid_generate_v4()
ruc                   varchar(11) UNIQUE NOT NULL
razon_social          varchar(200) NOT NULL
nombre_comercial      varchar(200) NOT NULL     ← usar este para identificar distribuidor
telefono              varchar(15)
email                 varchar(200)
zonas                 jsonb default '[]'
tiempo_entrega_hrs    integer default 24
estado                varchar(10) default 'activo'
api_token             text
serie_factura         text default 'F001'
created_at, updated_at
```

**⚠️ No existe columna `nombre`** — usar `nombre_comercial` o `razon_social`.

### 3.2 `productos_circa` (catálogo maestro universal)
```
id                uuid PRIMARY KEY default gen_random_uuid()
ean               text                    ← vacío en todos los registros
marca             text NOT NULL
categoria         text NOT NULL
nombre            text NOT NULL
descripcion       text                    ← vacío
presentacion      text                    ← vacío
unidad_base       text default 'UND'
contenido_caja    integer
contenido_pack    integer
imagen_url        text
activo            boolean default true
codigo            text                    ← vacío en todos
created_at, updated_at
UNIQUE(nombre, marca, presentacion)
```

**Total:** 295 productos. `codigo` y `ean` están vacíos en 100% de filas.

### 3.3 `catalogo_distribuidor` (tabla puente precios/stock por distribuidor)
```
id                  uuid PRIMARY KEY default gen_random_uuid()
producto_circa_id   uuid REFERENCES productos_circa(id)
distribuidor_id     uuid REFERENCES distribuidores(id)
sku_distribuidor    text                  ← ⭐ CÓDIGO INTERNO DEL DISTRIBUIDOR
precio_caja         numeric(10,2)
precio_pack         numeric(10,2)
precio_unitario     numeric(10,2)
unidad_venta        text default 'CJA'
stock_disponible    integer
activo              boolean default true
unidades            jsonb                 ← precios por formato
codigo              text                  ← vacío, no usar
created_at, updated_at
UNIQUE(producto_circa_id, distribuidor_id)
```

**Total:** 148 SKUs (todos DIMAX). `sku_distribuidor` poblado 100% con códigos tipo "1245", "786", "1663". Este es el puente con el brief de promociones.

### 3.4 `catalogo` (LEGACY — solo Zoom, se va a deprecar)
```
id            uuid
distribuidor_id uuid                      ← todos son Zoom (a1b2c3d4-0001-4000-8000-000000000001)
sku           text (null en todos)
nombre        text
marca         text
categoria     text
precio_6, precio_12, precio_24  (null en todos)
stock         integer
imagen_url    text
activo        boolean
presentacion  text (null)
codigo        integer                     ← 33, 36, 464... código tipo SKU Zoom
unidades      jsonb                       ← {"UND x 1": 8.81, "CJA x 48": 422.89}
descripcion   text
```

**Total:** 151 filas activas, 163 totales. **Todos los nombres matchean 1:1 contra productos_circa (verificado).**

### 3.5 `bodegas`
```
id                       uuid
ruc, razon_social, nombre_comercial, direccion_fiscal, direccion_despacho, distrito
telefono_whatsapp        varchar           ← NO es "telefono" a secas
representante_legal, dni_representante, dni_foto_url
pin_hash, pin_intentos, pin_bloqueado_hasta
linea_aprobada, linea_disponible          numeric
distribuidor_id          uuid FK
scoring                  numeric
estado                   USER-DEFINED (enum)
contrato_hash, contrato_firmado_at
ultimo_pedido_items      jsonb            ← para feature REPETIR
kyc_nivel, onboarding_fase, referencia    text
created_at, updated_at
```

**⚠️ No existe columna `telefono`** — es `telefono_whatsapp`.

### 3.6 `pedidos`
Campos clave: id, numero, bodega_id, distribuidor_id, estado (enum pedido_estado), monto_productos, monto_financiado, monto_contado, fee_tasa, fee_monto, monto_total_credito, plazo_dias, fecha_vencimiento, total, items_json, confirmado_at.

**Enum `pedido_estado`:** `borrador, confirmado, aprobado, despachado, en_camino, entregado, pago_reportado, pagado, rechazado, en_mora, recibido, en_preparacion` (12 estados — pendiente simplificar a 8, issue separado).

### 3.7 `items_pedido`
```
id              uuid PK
pedido_id       uuid FK → pedidos(id) ON DELETE CASCADE
catalogo_id     uuid FK → catalogo(id)   ← ⚠️ FK APUNTA A TABLA LEGACY, NO A catalogo_distribuidor
pack_size       integer NOT NULL
cantidad        integer NOT NULL
precio          numeric NOT NULL
subtotal        numeric NOT NULL
```

**⚠️ BUG ARQUITECTÓNICO:** el FK apunta a la tabla legacy `catalogo`. Esto significa:
- Pedidos de Zoom funcionan (porque Zoom vive en `catalogo`)
- Pedidos de DIMAX fallarían FK si intentaran insertar aquí
- Como resultado, `items_pedido` está vacía (0 filas) porque `catalogo.py` inserta directo en `pedidos.items_json` sin pasar por `items_pedido`

### 3.8 `pagos`
```
id, pedido_id, monto_esperado, monto_pagado
metodo (enum)
estado (enum pago_estado) default 'pendiente'
comprobante_url
fecha_vencimiento    DATE NOT NULL   ← ⚠️ NO NULL, no crear para contado
fecha_pago
created_at
```

### 3.9 `recordatorios`
```
id, pedido_id, tipo (enum recordatorio_tipo)
enviado boolean default false
fecha_envio
```

### 3.10 `eventos` (auditoría)
```
id, pedido_id, bodega_id
accion           varchar NOT NULL    ← NO es "tipo"
estado_anterior, estado_nuevo
actor            varchar default 'sistema'
metadata         jsonb default '{}'
created_at
```

### 3.11 Otras tablas
`carritos`, `catalogo` (legacy), `contratos`, `financiamientos`, `flow_sessions`, `movimientos_linea`, `pin_tokens`, `sesiones`, `verificaciones_identidad`.

---

## 4. ARQUITECTURA ACTUAL (PROBLEMAS CONOCIDOS)

### 4.1 Dos tablas de catálogo paralelas (DEUDA TÉCNICA)

```
┌─────────────────────┐         ┌──────────────────────────┐
│   catalogo          │         │  catalogo_distribuidor   │
│   (LEGACY)          │         │   (NUEVA)                │
├─────────────────────┤         ├──────────────────────────┤
│ Zoom Corp (151)     │         │ DIMAX Corp (148)         │
│ Schema propio       │         │ Schema con FK            │
│ codigo (integer)    │         │ sku_distribuidor (text)  │
│ Sin FK a productos  │         │ FK → productos_circa ✓   │
└─────────────────────┘         └──────────────────────────┘
```

**Código activo que lee de `catalogo` (legacy):** CERO referencias después de archivar backups (22 abr 2026). Todo el código vivo lee de `catalogo_distribuidor`.

**Pero:** items_pedido.catalogo_id sigue apuntando a `catalogo` (FK). Bug crítico.

### 4.2 Pedidos huérfanos

`app/flows/catalogo.py:474` hace insert directo en `pedidos` con estado=`borrador` y guarda items en el campo `pedidos.items_json`. NO usa `db.create_pedido()`. Como resultado:
- `items_pedido`: 0 filas (nunca se inserta)
- `pagos`: 0 filas
- `recordatorios`: 0 filas (cobranza automática no opera)
- `eventos`: 1 fila (parcialmente logeado)

**Consecuencias:**
- REPETIR no funciona (no hay items para replicar)
- Cobranza no notifica (no hay recordatorios)
- Admin no puede verificar pagos contra monto esperado
- Facturación no tiene sustento detallado

---

## 5. ARQUITECTURA OBJETIVO

```
┌──────────────────────────────────────────────────────────┐
│                  productos_circa                          │
│            (catálogo maestro universal)                   │
└────────────────────────┬─────────────────────────────────┘
                         │ FK producto_circa_id
                         ▼
┌──────────────────────────────────────────────────────────┐
│              catalogo_distribuidor                        │
│  (precios, stock, sku_distribuidor por distribuidor)     │
│     Zoom + DIMAX + futuros distribuidores aquí           │
└────────────────────────┬─────────────────────────────────┘
                         │ FK catalogo_distribuidor_id (a migrar)
                         ▼
                  items_pedido
                  pedidos
                  
                  + promociones_distribuidor (NUEVA)
                    apunta por sku_distribuidor al catálogo
```

**Principios:**
1. Una sola tabla de catálogo por distribuidor (`catalogo_distribuidor`)
2. `productos_circa` es la única fuente de verdad de productos
3. `sku_distribuidor` es el puente con el mundo externo del distribuidor (brief, códigos internos, etc.)
4. Cada distribuidor puede tener sus propias promociones en `promociones_distribuidor`
5. El motor es agnóstico al distribuidor: lee reglas filtradas por `distribuidor_id`

---

## 6. DATOS REALES QUE EXISTEN

| Tabla | Filas | Notas |
|---|---|---|
| productos_circa | 295 | codigo, ean todos NULL |
| catalogo_distribuidor | 148 | todos DIMAX, sku_distribuidor 100% poblado |
| catalogo (legacy) | 151 activos / 163 total | todos Zoom, 100% matchean por nombre a productos_circa |
| distribuidores | 2 (Zoom + DIMAX) + probablemente 1 admin | |
| bodegas | 7 de testing | ver sección 9 |
| pedidos | 2 (ambos de Paola, ambos `pagado`) | |
| items_pedido | **0** | bug arquitectónico |
| pagos | **0** | bug derivado |
| recordatorios | **0** | bug derivado |
| eventos | 1 | bug derivado |

### IDs de distribuidores
- **Zoom Corp:** `a1b2c3d4-0001-4000-8000-000000000001`
- **DIMAX Corp SAC:** `d1a2b3c4-0001-4000-8000-000000000002`

---

## 7. BODEGAS DE TESTING

| Bodega | ID | Teléfono | Distribuidor | Bypass |
|---|---|---|---|---|
| Paola | `b1b2c3d4-0001-4000-8000-000000000001` | +51993557282 | Zoom | NO |
| Cynthia | `b1b2c3d4-0002-4000-8000-000000000002` | +51954712581 | Zoom | SI |
| George | `b1b2c3d4-0003-4000-8000-000000000003` | +51977652871 | Zoom | SI |
| Charlie | `b1b2c3d4-0004-4000-8000-000000000004` | +56991291415 | Zoom | SI |
| Jose | `b1b2c3d4-0005-4000-8000-000000000005` | +51955755308 | DIMAX | SI |
| Jeff | `b1b2c3d4-0006-4000-8000-000000000006` | +51942616682 | Zoom | SI |
| Washington | `b1b2c3d4-0007-4000-8000-000000000007` | +51981254477 | Zoom | SI |

---

## 8. BUGS Y FIXES (22 ABRIL 2026)

### Aplicados hoy ✅
1. **"Ya pagué" mostraba S/0.00**
   Archivo: `app/state_machine.py` ~línea 464
   Fix: fallback chain para `total_pagar` (monto_total_credito → total → monto_financiado+fee → monto_contado → 0)
   Commit: pendiente

2. **Trigger SQL `trg_snapshot_ultimo_pedido`**
   Instalado en Supabase. Se dispara cuando un pedido pasa a `recibido`.
   Lee items de `items_pedido` y los guarda en `bodegas.ultimo_pedido_items`.
   ⚠️ **Hoy no tiene utilidad práctica porque `items_pedido` nunca se puebla** — pero quedará útil cuando arreglemos el bug de pedidos huérfanos.

3. **Backups archivados**
   Movidos a `~/Projects/circa-deploy-temp/.archive/`:
   - main_BACKUP.py, main_BACKUP_DEMO.py
   - catalogo_STABLE.py, catalogo_BACKUP.py, catalogo_BACKUP_DEMO.py
   - catalogo_v1_backup.py, catalogo_OLD.py, catalogo_SESSIONS.py
   - catalog_flow.py (probable legacy)
   `.archive/` agregado a `.gitignore`

### Pendientes de hoy (plan del día)
1. 🔴 Migración Zoom → `catalogo_distribuidor`
2. 🔴 Repuntar FK `items_pedido.catalogo_id` a `catalogo_distribuidor`
3. 🔴 Crear tabla `promociones_distribuidor` + 6 reglas piloto DIMAX
4. 🔴 Backend: motor evaluador + endpoint
5. 🔴 Frontend: pill naranja en carrito
6. 🔴 Testing E2E con Paola

### Pendientes post-demo
- **Contrato PDF dice S/5** (debería decir S/3). Necesita localizar el generador.
- **Items huérfanos (`items_pedido` vacía)**: `catalogo.py:474` debe usar `db.create_pedido()` o en `pin_flow.py` al confirmar, poblar items_pedido + pagos + recordatorios + eventos manualmente desde `pedidos.items_json`.
- **Simplificar enum de estados** de 12 a 8 (issue separado). Propuesta:
  - Eliminar: `aprobado` (no se usa), `recibido` (merge con `en_preparacion`), `despachado` (merge con `en_camino`)
  - Mantener: borrador, confirmado, en_preparacion, en_camino, entregado, pago_reportado, pagado, rechazado, en_mora

---

## 9. MAPEO BRIEF DIMAX → DB

**Archivo fuente:** `BRIEF_DIMAX_ABRIL_2026.xlsx`, hoja "BRIEF ABRIL 14.04"

### Estructura del brief
83 reglas con columnas: CATEGORIA, PRODUCTO PARTICIPANTE, POR CADA, UNID, BONIFICA, UNID, DESCRIPCION, CONDICION, PRODUCTO REGALO, COSTO BONIF, % TASA DSCTO, COD BONIF, FFVV, OBSERVACION.

### 6 tipos de promociones identificados
| Tipo | Descripción | Ejemplo |
|---|---|---|
| A | Descuento escalonado por unidades de un SKU | CREMOSITA 6/12/72 UND → 6.5%/7.5%/8.5% |
| B | Descuento escalonado por monto en categoría | TODO ECCO S/30/60/100 → 2.69%/4.03%/5.65% |
| C | Bonificación física por unidades | 10 UND TOPPING + 1 gratis |
| D | Bonificación física por monto | S/45 LEP + 1 ANCHOR |
| E | Bundle cruzado | 144 CREMOSITA + 6 COMPLEJO B → 2.2% |
| F | POSM no vendible | S/30 ECCO + 1 TAPER ECCO |

**Fase 1 (hoy):** solo tipos A y B (descuentos puros). Cubre ~50% de las reglas.

### Mapeo de matching
El brief usa nombres tipo "CREMOSITA", "AMANECER", "NESCAFE TRADICION 14 GR". El catálogo tiene nombres largos tipo "IDEAL CREMOSITA Mzc Lac 24x390g PE".

**Estrategia:** usar `sku_distribuidor` (ej: "1245", "1305") como clave. Las reglas guardan un array de `sku_distribuidor` que aplican. Es determinístico, no depende de parsing de nombres.

### Condiciones de aplicación
- `ACUMULATIVO` → se aplica además de otras reglas acumulativas
- `UNA REGLA ANULA A LA OTRA` → mutuamente excluyente (solo aplica la más alta de un grupo)
- `SOLO UNO POR PEDIDO` → una sola vez por carrito
- `SOLO UNO POR CLIENTE` → una sola vez en la vida del cliente (requiere historial)

### Filtros especiales
- `CARTERA COMPRA CERO MAR 26`: solo bodegas que NO compraron ese SKU en marzo. **Fase 3** (requiere historial de compras que hoy no existe)
- `CLIENTES REGULARES`: definición ambigua, por resolver con DIMAX
- `FFVV: BODEGAS | MERCADOS | BODEGAS/MERCADOS`: Circa solo aplica las que incluyen `BODEGAS`

---

## 10. TABLA `promociones_distribuidor` (A CREAR)

```sql
CREATE TABLE promociones_distribuidor (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  distribuidor_id UUID NOT NULL REFERENCES distribuidores(id),

  -- Identificación
  nombre TEXT NOT NULL,
  tipo TEXT NOT NULL CHECK (tipo IN (
    'descuento_unidades',
    'descuento_monto_categoria'
    -- fases futuras: 'bonificacion_unidades', 'bonificacion_monto', 'bundle_cruzado', 'posm'
  )),

  -- Qué productos aplican (uno u otro según tipo)
  skus_aplica TEXT[],           -- array de sku_distribuidor (tipo A)
  categoria TEXT,               -- matchea productos_circa.categoria (tipo B)
  marca_aplica TEXT,            -- matchea productos_circa.marca (refinamiento tipo B)

  -- Umbrales
  umbral_cantidad INT,          -- ej: 6 (para "POR 6 UND")
  umbral_unidad TEXT,           -- 'UND' | 'TIRA' | 'DSP' | 'CJA'
  umbral_monto NUMERIC(10,2),   -- ej: 30.00 (para "POR S/30")

  -- Beneficio
  porcentaje_descuento NUMERIC(5,4) NOT NULL,   -- 0.065 = 6.5%

  -- Lógica de anulación
  grupo_anulacion TEXT,         -- reglas con el mismo grupo se anulan entre sí

  -- Vigencia y control
  vigente_desde DATE DEFAULT CURRENT_DATE,
  vigente_hasta DATE,
  activa BOOLEAN DEFAULT true,
  observacion TEXT,

  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_promo_dist_activa ON promociones_distribuidor(distribuidor_id, activa);
```

### Motor evaluador (pseudocódigo)
```python
def evaluar_promociones(cart, distribuidor_id):
    """
    cart: lista de items con {sku_distribuidor, cantidad, unidad, subtotal, categoria, marca}
    Returns: (descuentos_aplicados, sugerencias_para_ui)
    """
    reglas = db.get_promociones_activas(distribuidor_id)
    
    # 1. Agrupar reglas por grupo_anulacion
    # 2. Por cada regla, calcular si el carrito la cumple
    # 3. Para reglas tipo UNA REGLA ANULA OTRA: quedarse con la más alta
    # 4. Para reglas ACUMULATIVO: sumar
    # 5. Calcular "próximo escalón" para sugerencias en pill naranja
    
    return {
        "descuentos": [...],   # a aplicar en el pedido
        "sugerencias": [...]   # "Llevas X, agrega Y para Z%"
    }
```

---

## 11. ERRORES COMUNES A EVITAR

Durante esta sesión cometí varios errores de asunción de nombres. Evitar:

| ❌ Asumí | ✅ Correcto |
|---|---|
| `bodegas.telefono` | `bodegas.telefono_whatsapp` |
| `distribuidores.nombre` | `distribuidores.nombre_comercial` |
| `catalogo_distribuidor.producto_id` | `catalogo_distribuidor.producto_circa_id` |
| `items_pedido.tipo` | `items_pedido` no tiene "tipo"; `eventos.accion` sí (no `eventos.tipo`) |
| Estado `confirmado` se usa al primer insert | Los pedidos se crean en `borrador`, luego pasan a `confirmado` tras PIN |
| `UPDATE ... LIMIT 1` | PostgreSQL no lo soporta; usar `WHERE id IN (SELECT ... LIMIT 1)` |
| `pagos.fecha_vencimiento` es nullable | Es `NOT NULL` — para contado no crear fila |

**Regla de oro:** antes de cualquier SQL con nombres de columnas, verificar contra la sección 3 de este documento.

---

## 12. ARCHIVOS CLAVE DEL PROYECTO

### Activos (producción)
- `app/main.py` (55K) — FastAPI app, webhooks Meta, endpoints API
- `app/state_machine.py` (42K) — máquina de estados del flujo WhatsApp
- `app/flows/catalogo.py` (23K) — Flow del catálogo WhatsApp
- `app/flows/pin_flow.py` (21K) — Flow del PIN
- `app/flows/onboarding.py` (9K)
- `app/flows/crypto.py` (4K) — RSA encryption Flows
- `app/services/db.py` — helpers Supabase
- `app/services/meta_client.py` — cliente Meta Graph API
- `app/services/fees.py` — comisión por plan (7d 1.4%, 15d 3%, 30d 6%, mín. S/1) + mora 0.03%/día post-vencimiento; `pedidos.fee_regimen` (`legacy_v20260428` | `plan_fijo_v20260520`)
- `app/services/financing.py`
- `app/services/identity.py` — ApiInti
- `app/services/vision.py` — Claude Vision
- `app/services/cobranza.py`
- `app/services/cards.py` — HCTI
- `app/routes/distribuidor.py` — portal distribuidor + admin
- `app/contracts.py` — contratos PDF (⚠️ **verificar si existe** — puede estar en otro lado)
- `static/catalogo_v2.html` — catálogo web
- `static/distribuidor.html` — portal distribuidor
- `static/admin.html` — panel admin

### Archivados (NO tocar, solo referencia histórica)
- `.archive/main_BACKUP.py, main_BACKUP_DEMO.py`
- `.archive/catalogo_STABLE.py, catalogo_BACKUP.py, catalogo_BACKUP_DEMO.py`
- `.archive/catalogo_v1_backup.py, catalogo_OLD.py, catalogo_SESSIONS.py`
- `.archive/catalog_flow.py`

---

## 13. PREGUNTAS ABIERTAS

1. **¿Qué es `contrato_hash` de bodegas?** Se genera al firmar contrato. ¿Dónde se valida?
2. **¿El generador de contratos PDF vive dónde?** No existe `app/contracts.py` confirmado, puede estar embedded en `main.py` o en un servicio aparte.
3. **Definición de "CLIENTES REGULARES"** — ambiguo en el brief DIMAX. Pendiente con contacto DIMAX.
4. **Bypass `TEST_PHONES`** — ¿cómo afecta al motor de promociones? Si una bodega está en bypass, ¿recibe las mismas promos?
5. **Enum de estados simplificado** — decisión pendiente sobre los 12 → 8 estados.

---

## 14. PLAN DEL DÍA 22 ABRIL 2026 (DEADLINE: NOCHE)

| Hora | Bloque | Estado |
|---|---|---|
| 7:00 - 8:30 | Diagnóstico de catálogos + decisión arquitectura | ✅ |
| 8:30 - 10:00 | Migración Zoom → catalogo_distribuidor | 🔴 en curso |
| 10:00 - 11:00 | Repunte FK items_pedido | 🔴 |
| 11:00 - 12:00 | CREATE TABLE promociones + 6 reglas piloto | 🔴 |
| 12:00 - 14:00 | Motor evaluador + endpoint API | 🔴 |
| 14:00 - 16:30 | Frontend pill naranja + descuento | 🔴 |
| 16:30 - 18:00 | Testing E2E | 🔴 |
| 18:00 - 19:00 | Deploy + buffer | 🔴 |

### 6 Reglas piloto propuestas (por confirmar sku_distribuidor real)
1. IDEAL CREMOSITA: 6/12/72 UND → 6.5/7.5/8.5% (grupo: CREMOSITA)
2. IDEAL AMANECER: 6/12/48/72 UND → 3/3.5/5/6% (grupo: AMANECER)
3. NESCAFE TRADICION 14g: 1/3/5/8 TIRA → 5/6/8/10% (grupo: NESCAFE_TRAD_14)
4. NESCAFE KIRMA 14g: 1/2/4/8 TIRA → 5/6/8/10% (grupo: KIRMA_14)
5. TODO ECCO: S/30/60/100 → 2.69/4.03/5.65% (categoria: ECCO, grupo: ECCO_MONTO)
6. TODO CHOCOLATES: S/150/300 → 6/8% (marca: SUBLIME, grupo: CHOCO_MONTO)

---

## 15. CREDENCIALES Y TOKENS (referencias, no los valores reales)

**⚠️ Los valores reales viven SOLO en Railway Environment Variables. Nunca en código, nunca en chats.**

- `META_ACCESS_TOKEN` — token System User Meta
- `META_APP_SECRET` — para validar webhooks
- `META_VERIFY_TOKEN` — webhook verification
- `FLOW_PRIVATE_KEY` — RSA key para encriptación de Flows
- `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`
- `APIINTI_TOKEN` — SUNAT/RENIEC
- `ANTHROPIC_API_KEY` — Claude Vision
- `HCTI_USER_ID`, `HCTI_API_KEY` — tarjetas visuales
- Tokens internos: `circa-admin-2026`, `zoom-circa-2026`, `dimax-circa-2026`

Para compartir accesos con Jeff: invitarlo a Railway (Settings → Members → Developer role).

---

## 16. URLS IMPORTANTES

- **Producción:** https://circa-production-c517.up.railway.app
- **Admin panel:** https://circa-production-c517.up.railway.app/static/admin.html
- **Portal distribuidor:** https://circa-production-c517.up.railway.app/static/distribuidor.html
- **Catálogo (por bodega):** https://circa-production-c517.up.railway.app/catalogo-v2?b={bodega_id}
- **Supabase dashboard:** https://supabase.com/dashboard/project/rhxqcoijzgqlecpdfhde
- **Railway dashboard:** https://railway.app/project/[id]
- **GitHub:** https://github.com/palisacpe-crypto/circa-production
- **Meta Flow Builder:** https://business.facebook.com/wa/manage/flows/

---

## FIN DEL DOCUMENTO

**Para mantenerlo vigente:**
- Cada cambio de schema → actualizar sección 3
- Cada bug arreglado → mover de "Pendientes" a "Aplicados" en sección 8
- Cada nueva tabla → agregar en sección 3 y 4
- Cuando cambia la arquitectura → actualizar sección 5
