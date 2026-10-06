# Express Onboarding (piloto WhatsApp)

| | |
|--|--|
| **Código** | `app/flows/express_onboarding.py`, `app/services/express_onboarding_gate.py` |
| **Gate** | Lista de vendedores; onboarding clásico para el resto |
| **Env** | `EXPRESS_ONBOARDING_ENABLED`, `EXPRESS_ONBOARDING_VENDEDORES`, `EXPRESS_ONBOARDING_PHONES` |

# Qué es

Flujo corto de activación para el piloto:

1. Bienvenida  
2. **Una sola foto** (DNI *o* selfie, no ambas)  
3. Aceptación de línea (igual que hoy)  
4. Términos y condiciones  
5. Crear PIN → cuenta activa

> **Estado:** apagado por defecto (`EXPRESS_ONBOARDING_ENABLED` default `false`).  
> Si se reactiva, Express **pide PIN** tras T&C. `es_test` ya no abre el flujo.

## Quién entra a Express

Hacen falta las dos cosas:

1. `EXPRESS_ONBOARDING_ENABLED=true`
2. El vendedor activo de la bodega (`bodega_vendedores`) está en `EXPRESS_ONBOARDING_VENDEDORES` (códigos `V0034`, separados por coma)

Opcional: un teléfono en `EXPRESS_ONBOARDING_PHONES`. Si esa variable no está, no hay teléfonos de piloto.

Una bodega de otro vendedor, aunque sea `es_test`, sigue el onboarding clásico (`reg_*` / `prospecto`). Una sesión que haya quedado en `express_*` también sale si su vendedor ya no está en la lista.

## Fases de sesión

`express_cold` → `express_welcome` → `express_foto` → `express_linea` → `express_tyc` → `reg_pin` → `menu`

## Apagar / cambiar lista

```env
EXPRESS_ONBOARDING_ENABLED=true
EXPRESS_ONBOARDING_VENDEDORES=V0034
```

Con el master en `false`, o sin el código del vendedor en la lista, las sesiones `express_*` salen del flujo Express.
