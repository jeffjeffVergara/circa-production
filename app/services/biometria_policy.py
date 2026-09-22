"""Política de biometría KYC: bypass para demos en bodegas es_test."""
from __future__ import annotations

from typing import Any


def biometria_demo_relaxed(bodega: dict[str, Any] | None) -> bool:
    """True si la bodega es de prueba y el flag permite saltar validación biométrica."""
    from app.config import BIOMETRIA_RELAX_FOR_TEST_BODEGAS

    if not BIOMETRIA_RELAX_FOR_TEST_BODEGAS:
        return False
    return bool(bodega and bodega.get("es_test"))


def skip_biometria_checks(
    telefono: str,
    bodega: dict[str, Any] | None,
    *,
    test_phones: set[str],
) -> bool:
    """Bypass RENIEC/visión: teléfonos QA hardcodeados o bodega es_test con flag demo."""
    if telefono in test_phones:
        return True
    if bodega and bodega.get("biometria_bypass"):
        # Bypass manual por bodega (backoffice/SQL), p.ej. proveedor de visión caído.
        return True
    return biometria_demo_relaxed(bodega)


# Códigos de vision.py que indican falla del proveedor (Anthropic), no un rechazo de la foto.
PROVIDER_FAIL_CODES = frozenset({"no_api_key", "provider_error", "invalid_response", "exception"})


def es_falla_proveedor(check: dict | None) -> bool:
    """True si la validación no se pudo hacer por el proveedor (no por la foto)."""
    return bool(check) and not check.get("valid", False) and check.get("reason_code") in PROVIDER_FAIL_CODES


def marcar_revalidar_biometria(bodega_id: str | None, etapa: str) -> None:
    """Marca la bodega para revalidar KYC cuando vuelva el proveedor. Nunca bloquea el flujo."""
    if not bodega_id:
        return
    try:
        from app.services import db
        db.update_bodega(bodega_id, {
            "biometria_revalidar": True,
            "biometria_revalidar_motivo": f"{etapa}: proveedor de visión no disponible",
        })
    except Exception as e:
        import logging
        logging.getLogger("circa").warning("No se pudo marcar biometria_revalidar %s: %s", bodega_id, e)
