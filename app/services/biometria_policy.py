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
    return biometria_demo_relaxed(bodega)
