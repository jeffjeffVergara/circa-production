"""
Allowlist para Express Onboarding (piloto).

Por defecto OFF para todos; solo números en EXPRESS_ONBOARDING_PHONES
entran al flujo nuevo. El onboarding clásico no se modifica.
"""

from __future__ import annotations

import os
import re

# Piloto inicial (sobreescribible por env)
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
    """Master switch. Default true so the pilot list works once deployed."""
    return _env_flag("EXPRESS_ONBOARDING_ENABLED", default=True)


def express_pilot_phones() -> set[str]:
    raw = (os.getenv("EXPRESS_ONBOARDING_PHONES") or "").strip()
    if raw:
        parts = re.split(r"[\s,;]+", raw)
        return {normalize_phone_e164(p) for p in parts if p.strip()}
    return {normalize_phone_e164(p) for p in _DEFAULT_PILOT_PHONES}


def is_express_pilot_phone(telefono: str | None) -> bool:
    if not express_onboarding_enabled():
        return False
    norm = normalize_phone_e164(telefono)
    if not norm:
        return False
    allowed = express_pilot_phones()
    return norm in allowed or norm.lstrip("+") in {p.lstrip("+") for p in allowed}


def should_use_express_onboarding(
    telefono: str | None,
    bodega: dict | None,
    session: dict | None,
) -> bool:
    """
    True solo para piloto Express.
    - Ya en fase express_* → seguir
    - Bodega activa → menú/clásico (no Express)
    - Sin bodega o inactiva → Express
    """
    if not is_express_pilot_phone(telefono):
        return False

    fase = (session or {}).get("fase") or ""
    if fase.startswith("express_"):
        return True

    if bodega and (bodega.get("estado") or "") == "activo":
        return False

    # De cero (sin bodega), precarga o post-afiliar (inactiva)
    return True
