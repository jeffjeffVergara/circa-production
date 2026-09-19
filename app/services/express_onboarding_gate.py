"""
Gate para Express Onboarding (piloto).

Entran al flujo Express si:
  - el número está en EXPRESS_ONBOARDING_PHONES (allowlist), o
  - la bodega tiene es_test=true

El onboarding clásico no se modifica para el resto.
"""

from __future__ import annotations

import os
import re

# Allowlist opcional (además de bodegas es_test)
_DEFAULT_PILOT_PHONES = (
    "+51942616682",  # 942616682
    "+51993557282",  # 993557282
    "+51954712581",  # 954712581
)


def _env_flag(name: str, default: bool = False) -> bool:
    raw = (os.getenv(name) or "").strip().lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "on", "si", "sí")


def normalize_phone_e164(telefono: str | None) -> str:
    digits = re.sub(r"\D", "", telefono or "")
    if not digits:
        return ""
    if digits.startswith("51") and len(digits) == 11:
        return "+" + digits
    if len(digits) == 9:
        return "+51" + digits
    if (telefono or "").startswith("+") and digits:
        return "+" + digits
    return "+" + digits if digits else ""


def express_onboarding_enabled() -> bool:
    """Master switch. Default false: activar sin PIN dejaba bodegas test en bucle al pagar."""
    return _env_flag("EXPRESS_ONBOARDING_ENABLED", default=False)


def express_pilot_phones() -> set[str]:
    raw = (os.getenv("EXPRESS_ONBOARDING_PHONES") or "").strip()
    if raw:
        parts = re.split(r"[\s,;]+", raw)
        return {normalize_phone_e164(p) for p in parts if p.strip()}
    return {normalize_phone_e164(p) for p in _DEFAULT_PILOT_PHONES}


def is_express_allowlist_phone(telefono: str | None) -> bool:
    """Solo allowlist explícita (env / default). No mira es_test."""
    if not express_onboarding_enabled():
        return False
    norm = normalize_phone_e164(telefono)
    if not norm:
        return False
    allowed = express_pilot_phones()
    return norm in allowed or norm.lstrip("+") in {p.lstrip("+") for p in allowed}


# Alias legacy
is_express_pilot_phone = is_express_allowlist_phone


def qualifies_for_express(telefono: str | None, bodega: dict | None = None) -> bool:
    """
    True si el contacto debe usar Express:
    allowlist de teléfonos O bodega de prueba (es_test).
    """
    if not express_onboarding_enabled():
        return False
    if is_express_allowlist_phone(telefono):
        return True
    if bodega and bool(bodega.get("es_test")):
        return True
    return False


def should_use_express_onboarding(
    telefono: str | None,
    bodega: dict | None,
    session: dict | None,
) -> bool:
    """
    - Master off → nunca Express (tampoco si la sesión quedó en express_*)
    - Ya en fase express_* y master on → seguir
    - Bodega activa → menú (no Express)
    - Allowlist o es_test, sin bodega / inactiva → Express
    """
    if not express_onboarding_enabled():
        return False

    fase = (session or {}).get("fase") or ""
    if fase.startswith("express_"):
        return True

    if not qualifies_for_express(telefono, bodega):
        return False

    if bodega and (bodega.get("estado") or "") == "activo":
        return False

    # De cero (allowlist), precarga/test o post-afiliar (inactiva)
    return True
