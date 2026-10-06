"""
Gate para Express Onboarding (piloto).

Entra al flujo Express solo si el master está encendido y, además:
  - el vendedor activo de la bodega está en EXPRESS_ONBOARDING_VENDEDORES, o
  - el teléfono está en EXPRESS_ONBOARDING_PHONES (si esa variable está puesta)

es_test ya no abre Express. Sin vendedor en la lista, el onboarding clásico sigue.
"""

from __future__ import annotations

import logging
import os
import re

logger = logging.getLogger("circa.express_onboarding_gate")


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
    """Solo los teléfonos escritos en EXPRESS_ONBOARDING_PHONES. Vacío = ninguno."""
    raw = (os.getenv("EXPRESS_ONBOARDING_PHONES") or "").strip()
    if not raw:
        return set()
    parts = re.split(r"[\s,;]+", raw)
    return {normalize_phone_e164(p) for p in parts if p.strip()}


def express_vendor_codes() -> set[str]:
    """Códigos de vendedor (V0034) que pueden enrolar por Express. Vacío = ninguno."""
    raw = (os.getenv("EXPRESS_ONBOARDING_VENDEDORES") or "").strip()
    if not raw:
        return set()
    return {p.strip().upper() for p in re.split(r"[\s,;]+", raw) if p.strip()}


def _lookup_vendor_codes(bodega_id: str) -> set[str]:
    """Códigos de vendedores con mapeo activo en esta bodega."""
    try:
        from app.services import db

        maps = (
            db.sb.table("bodega_vendedores")
            .select("vendedor_id")
            .eq("bodega_id", str(bodega_id))
            .eq("activo", True)
            .limit(5)
            .execute()
        )
        ids = [r["vendedor_id"] for r in (maps.data or []) if r.get("vendedor_id")]
        if not ids:
            return set()
        vends = (
            db.sb.table("vendedores")
            .select("codigo")
            .in_("id", ids)
            .limit(5)
            .execute()
        )
        return {
            (r.get("codigo") or "").strip().upper()
            for r in (vends.data or [])
            if (r.get("codigo") or "").strip()
        }
    except Exception:
        logger.warning("express: no se pudo leer vendedor de bodega %s", bodega_id, exc_info=True)
        return set()


def vendedor_codigos_de_bodega(bodega: dict | None) -> set[str]:
    if not bodega:
        return set()
    explicit = (bodega.get("vendedor_codigo") or "").strip().upper()
    if explicit:
        return {explicit}
    bid = bodega.get("id")
    if not bid:
        return set()
    return _lookup_vendor_codes(str(bid))


def is_express_allowlist_phone(telefono: str | None) -> bool:
    """Solo teléfonos en EXPRESS_ONBOARDING_PHONES. Vacío = ninguno."""
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
    teléfono en allowlist explícita, o vendedor activo de la bodega en la lista.
    es_test no alcanza.
    """
    if not express_onboarding_enabled():
        return False
    if is_express_allowlist_phone(telefono):
        return True
    allowed = express_vendor_codes()
    if not allowed:
        return False
    return bool(vendedor_codigos_de_bodega(bodega) & allowed)


def should_use_express_onboarding(
    telefono: str | None,
    bodega: dict | None,
    session: dict | None,
) -> bool:
    """
    - Master off → nunca Express (tampoco si la sesión quedó en express_*)
    - Sin vendedor de la lista ni teléfono allowlist → clásico, aunque la fase sea express_*
    - Ya en fase express_* y sigue calificando → seguir
    - Bodega activa → menú (no Express)
    """
    if not express_onboarding_enabled():
        return False

    if not qualifies_for_express(telefono, bodega):
        return False

    fase = (session or {}).get("fase") or ""
    if fase.startswith("express_"):
        return True

    if bodega and (bodega.get("estado") or "") == "activo":
        return False

    # De cero (allowlist), precarga/test o post-afiliar (inactiva)
    return True
