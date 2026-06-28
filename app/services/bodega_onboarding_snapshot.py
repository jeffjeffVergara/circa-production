"""Snapshot de línea y score proxy al alta de bodega (modelo DIMAX / tier)."""

from __future__ import annotations

TIERS = [100, 200, 300, 400, 500]

# Proxy 0–100 para comparar en backoffice; deriva del tier, no del score operativo.
_SCORING_ALTA_BY_TIER: dict[int, int] = {
    100: 58,
    200: 68,
    300: 76,
    400: 84,
    500: 90,
}


def tier_from_linea(linea_aprobada: float) -> int:
    for t in TIERS:
        if linea_aprobada <= t:
            return t
    return 500


def scoring_alta_from_linea(linea_aprobada: float) -> int:
    return _SCORING_ALTA_BY_TIER.get(tier_from_linea(float(linea_aprobada)), 70)


def onboarding_alta_fields(linea_aprobada: float) -> dict[str, float | int]:
    linea = float(linea_aprobada)
    return {
        "linea_alta": linea,
        "scoring_alta": scoring_alta_from_linea(linea),
    }
