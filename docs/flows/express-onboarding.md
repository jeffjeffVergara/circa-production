# Express Onboarding (piloto WhatsApp)

| | |
|--|--|
| **Código** | `app/flows/express_onboarding.py`, `app/services/express_onboarding_gate.py` |
| **Gate** | Allowlist de teléfonos; onboarding clásico intacto |
| **Env** | `EXPRESS_ONBOARDING_ENABLED`, `EXPRESS_ONBOARDING_PHONES` |

## Qué es

Flujo corto de activación para el piloto:

1. Bienvenida  
2. **Una sola foto** (DNI *o* selfie, no ambas)  
3. Aceptación de línea (igual que hoy)  
4. Términos y condiciones  
5. Cuenta **activa sin crear PIN**

Cubre: creación de cero, precarga y post-afiliar vendedor (mismo gate al escribir por WhatsApp).

## Quién entra a Express

Si `EXPRESS_ONBOARDING_ENABLED=true`, entra quien cumpla **cualquiera**:

1. **Bodega de prueba** (`bodegas.es_test = true`) — al marcar una bodega como prueba (o cargarla como test), ese WhatsApp usa Express automáticamente  
2. **Allowlist de teléfonos** (`EXPRESS_ONBOARDING_PHONES` / default en código), útil para de-cero sin bodega aún  

El resto sigue el onboarding clásico (`reg_*` / `prospecto`).

### Allowlist default (además de `es_test`)

- `+51942616682` (942616682)
- `+51993557282` (993557282)
- `+51954712581` (954712581)

## Fases de sesión

`express_cold` → `express_welcome` → `express_foto` → `express_linea` → `express_tyc` → `menu`

## Apagar / cambiar lista

```env
EXPRESS_ONBOARDING_ENABLED=false
# o
EXPRESS_ONBOARDING_PHONES=+51942616682,+51993557282
```
