# 01 — Onboarding y activación

| | |
|--|--|
| **Figma** | *[pendiente — página «01 Onboarding»]* |
| **Escenarios** | ONB-01 … ONB-11 |
| **Código** | `app/state_machine.py` (`welcome`, `reg_*`), `app/flows/onboarding.py`, `app/flows/flow_onboarding.json` |
| **Endpoint Flow** | `POST /flows/onboarding` |

## Objetivo

Registrar una bodega preaprobada, validar identidad, firmar contrato, crear PIN y dejar `estado=activo` con línea disponible.

## Flujo (chat + Flow Meta)

```mermaid
stateDiagram-v2
  [*] --> welcome
  welcome --> reg_ruc: nuevo
  reg_ruc --> reg_dni: RUC OK
  reg_dni --> reg_biometria: DNI OK
  reg_biometria --> reg_linea_acepta
  reg_linea_acepta --> reg_contrato: acepta línea
  reg_contrato --> reg_pin: ACEPTO contrato
  reg_pin --> menu: PIN creado
  menu --> [*]: CUENTA_ACTIVA
```

Detalle pantallas Flow: ver diagrama en [`arquitectura.md` §4.7](../../arquitectura.md).

## Wireframes (placeholder)

| Pantalla | ID escenario | Notas |
|----------|--------------|-------|
| Bienvenida + pedir RUC | ONB-01, ONB-02 | Texto o Flow `RUC_INPUT` |
| Verificación DNI foto | ONB-04 | Chat imagen → Vision |
| Oferta línea S/XXX | ONB-06 | Botones aceptar |
| Contrato PDF + ACEPTO | ONB-07 | Botón lista `ACEPTO` |
| Crear PIN (Flow) | ONB-08 | `/flows/pin` mode create |

## Checklist por escenario

| ID | Verificación |
|----|----------------|
| ONB-02 | RUC en lista preaprobada → continúa |
| ONB-03 | RUC desconocido → mensaje rechazo |
| ONB-07 | PDF generado, hash guardado |
| ONB-09 | Tras PIN, menú con línea correcta |
| ONB-11 | OLVIDE → flujo DNI reset, PIN nuevo |

## Estados BD relevantes

- `bodegas.estado`: → `activo`
- `bodegas.pin_hash`, `linea_aprobada`, `linea_disponible`
- `sesiones.fase`: transiciones `reg_*` → `menu`

[← Índice](./README.md)
