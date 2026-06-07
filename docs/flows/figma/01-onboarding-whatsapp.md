# 01 — Onboarding WhatsApp (spec Figma)

| | |
|--|--|
| **Figma** | [Wireframes Onboarding](https://www.figma.com/design/8uXIOxgppRe67aNbThSyv6) → página `02 Conversacion completa` |
| **YAML** | [`onboarding-screens.yaml`](./onboarding-screens.yaml) |
| **Escenarios** | ONB-01 … ONB-11 |
| **Código** | `app/state_machine.py`, `app/services/meta_client.py` |
| **Actor** | Bodeguero |

## Progreso (4 pasos)

| Paso | Label | `sesiones.fase` |
|------|-------|-----------------|
| 1 | Verificar negocio | `welcome` → `reg_ruc` |
| 2 | Identidad | `reg_dni` → `reg_biometria` |
| 3 | Activación | `reg_linea_acepta` |
| 4 | Contrato y clave | `reg_contrato` → `reg_pin` → `menu` |

---

## Happy path — pantalla por pantalla

### 01 · Bienvenida (ONB-01)

| | |
|--|--|
| **Circa** | `button_reply` · `send_welcome` |
| **Mensaje** | Hola, **{nombre}**. Con Circa + **{distribuidor}** puedes: pedir por WhatsApp, ver promos, repetir pedidos, pagar después si te falta caja. ¿Activamos tu cuenta? |
| **Botones** | `SI` → «Activar Circa» |
| **Bodeguero** | Toca **Activar Circa** (equivale a escribir `SI`, `ACTIVAR`, `HOLA`) |
| **Siguiente** | 02 |

### 02 · Pedir RUC (ONB-02)

| | |
|--|--|
| **Circa** | `text` · `send_ruc_request` |
| **Mensaje** | Para activar, necesito verificar tu negocio. Escribe tu RUC (11 dígitos): |
| **Bodeguero** | Escribe RUC, ej. `20123456789` |
| **Siguiente** | 03 |

### 03 · Validando RUC

| | |
|--|--|
| **Circa** | `loading` — Verificando RUC en SUNAT… |
| **Bodeguero** | Espera |
| **Siguiente** | 04 |

### 04 · RUC verificado (ONB-02)

| | |
|--|--|
| **Circa** | `button_reply` · `send_ruc_verified` |
| **Mensaje** | RUC verificado en SUNAT: **{razon_social}**, RUC {ruc}, {direccion}, Rep. Legal {rep_legal}. ¿Los datos son correctos? |
| **Botones** | `SI` → Sí, correcto · `NO` → No, corregir |
| **Bodeguero** | Toca **Sí, correcto** |
| **Siguiente** | 05 (o 02 si No) |

### 05 · Pedir DNI (ONB-04)

| | |
|--|--|
| **Circa** | `text` · `send_dni_request` |
| **Mensaje** | Paso 2 de 4: verificar identidad (DNI + foto + selfie). Escribe DNI del representante legal (8 dígitos): |
| **Bodeguero** | Escribe DNI, ej. `45678901` |
| **Siguiente** | 06 |

### 06 · Validando DNI

| | |
|--|--|
| **Circa** | `loading` — Consultando RENIEC… |
| **Bodeguero** | Espera |
| **Siguiente** | 07 |

### 07 · DNI OK + pedir foto (ONB-04)

| | |
|--|--|
| **Circa** | `text` (éxito) + `text` |
| **Mensajes** | 1) Listo, **{nombre}**. Identidad verificada. 2) Envía foto del anverso del DNI físico (tip: vista única). |
| **Bodeguero** | Envía **imagen** del DNI |
| **Siguiente** | 08 |

### 08 · Verificando foto

| | |
|--|--|
| **Circa** | `loading` — Verificando documento… |
| **Bodeguero** | Espera |
| **Siguiente** | 09 |

### 09 · Documento OK + selfie (ONB-05)

| | |
|--|--|
| **Circa** | `text` (éxito) + `text` · `send_biometria_request` |
| **Mensajes** | 1) Documento verificado DNI {dni}. 2) {nombre}, tómate una selfie rápida. |
| **Bodeguero** | Envía **selfie** |
| **Siguiente** | 10 |

### 10 · Verificando selfie

| | |
|--|--|
| **Circa** | `loading` — Verificando identidad… |
| **Siguiente** | 11 |

### 11 · Oferta línea (ONB-06)

| | |
|--|--|
| **Circa** | `button_reply` · `send_linea_oferta` |
| **Mensaje** | Verificación completa. Cuenta Circa con {distribuidor}, hasta S/{linea}. ¿Continuamos? |
| **Botones** | `ACEPTO_LINEA` → Continuar · `NO_GRACIAS` → No, gracias |
| **Bodeguero** | Toca **Continuar** |
| **Siguiente** | 12 |

### 12 · Términos (ONB-07)

| | |
|--|--|
| **Circa** | `button_reply` · `send_contrato` |
| **Mensaje** | Términos de uso Circa (resumen: comprar hoy/pagar después, sin costo activación, etc.) |
| **Footer** | circa.pe/terminos |
| **Botones** | `ACEPTO` → Acepto |
| **Bodeguero** | Toca **Acepto** |
| **Siguiente** | 13 |

### 13 · Crear PIN Flow (ONB-08)

| | |
|--|--|
| **Circa** | `flow` · `send_pin_request(mode=create)` |
| **Mensaje** | Crea tu clave Circa de 4 dígitos… |
| **CTA Flow** | Crear clave · pantalla `PIN_CREATE` |
| **Bodeguero** | Abre Flow, ingresa PIN en UI nativa Meta |
| **Siguiente** | 14 |

### 14 · Activando cuenta

| | |
|--|--|
| **Sistema** | Clave creada correctamente |
| **Circa** | `loading` — Activando tu cuenta Circa… |
| **Siguiente** | 15 |

### 15 · Cuenta activa (ONB-09)

| | |
|--|--|
| **Circa** | `text` ×2 · `send_cuenta_activa` |
| **Mensajes** | 1) ¡Tu cuenta ya está lista! Hasta S/{linea} con pago después. 2) Puedes: pedir normal, pagar después, promos. |
| **Siguiente** | 16 |

### 16 · Menú principal (ONB-09)

| | |
|--|--|
| **Circa** | `list_reply` · `send_menu` |
| **Mensaje** | ¿Qué deseas hacer? |
| **Botón lista** | Ver opciones |
| **Filas** | Ver promos · Pedido/preventa · Repetir · Comprar y pagar luego · Ver pedidos · Olvidé clave · Hablar con Circa |
| **Bodeguero** | Abre lista y elige acción → [catálogo](./02-catalogo-whatsapp.md) |

---

## Ramas de error

| Frame | Trigger bodeguero | Mensaje Circa | Acción esperada |
|-------|-------------------|---------------|-----------------|
| **E01** | RUC formato inválido | RUC inválido. 11 dígitos, empieza 10 o 20. | Reenviar RUC |
| **E02** | RUC no preaprobado | Este RUC no tiene línea pre-aprobada en Circa. | Reintentar o contactar distribuidor |
| **E03** | DNI ≠ rep. legal SUNAT | Este DNI no coincide con el representante legal… | DNI correcto |
| **E04** | Foto DNI ilegible | No se pudo verificar el DNI. Foto clara del anverso. | Reenviar foto |
| **E05** | Selfie inválida | No es una selfie válida. Mira a la cámara. | Reenviar selfie |
| **E06** | PIN débil (1234) | No uses secuencias como 1234. | Otro PIN de 4 dígitos |

---

## Datos de ejemplo (wireframes)

| Variable | Valor demo |
|----------|------------|
| `{nombre}` | Bodega El Sol |
| `{distribuidor}` | DIMAX |
| `{linea}` | 500 |
| `{ruc}` | 20123456789 |
| `{razon_social}` | BODEGA EL SOL SAC |
| `{direccion}` | Av. Principal 123, Lima |
| `{rep_legal}` | Juan Pérez |
| `{dni}` | 45678901 |

[← Índice Figma](./README.md) · [Journey técnico](../01-onboarding.md)
