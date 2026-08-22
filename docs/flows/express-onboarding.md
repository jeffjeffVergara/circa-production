# Express Onboarding (piloto WhatsApp)

| | |
|--|--|
| **Código** | `app/flows/express_onboarding.py`, `app/services/express_onboarding_gate.py` |
| **Gate** | Allowlist de teléfonos; onboarding clásico intacto |
| **Env** | `EXPRESS_ONBOARDING_ENABLED`, `EXPRESS_ONBOARDING_PHONES` |

## Qué es

Flujo corto de activación para números piloto:

1. Bienvenida  
2. **Una sola foto** (DNI *o* selfie, no ambas)  
3. Aceptación de línea (igual que hoy)  
4. Términos y condiciones  
5. Cuenta **activa sin crear PIN**

Cubre: creación de cero, precarga y post-afiliar vendedor (mismo gate al escribir por WhatsApp).

## Piloto (default en código)

- `+51942616682` (942616682)
- `+51993557282` (993557282)
- `+51954712581` (954712581)

Cualquier otro número sigue el onboarding clásico (`reg_*` / `prospecto`).

## Fases de sesión

`express_cold` → `express_welcome` → `express_foto` → `express_linea` → `express_tyc` → `menu`

## Apagar / cambiar lista

```env
EXPRESS_ONBOARDING_ENABLED=false
# o
EXPRESS_ONBOARDING_PHONES=+51942616682,+51993557282
```
