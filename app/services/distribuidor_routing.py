"""
Enrutamiento Zoom vs DIMAX (piloto Circa).

Reglas de negocio:
- Catálogo y promociones: siempre DIMAX (todos los bodegueros ven el mismo catálogo piloto).
- Pedidos (portal distribuidor):
  - es_test=true  → Zoom (pruebas internas sin mezclar con operación DIMAX).
  - es_test=false → DIMAX (reales, con en_piloto true o false).
"""

from __future__ import annotations

ZOOM_DISTRIBUIDOR_ID = "a1b2c3d4-0001-4000-8000-000000000001"
DIMAX_DISTRIBUIDOR_ID = "d1a2b3c4-0001-4000-8000-000000000002"


def distribuidor_id_para_catalogo(_bodega: dict | None = None) -> str:
    """Catálogo web, Flow y motor de promociones."""
    return DIMAX_DISTRIBUIDOR_ID


def distribuidor_id_para_pedido(bodega: dict | None) -> str:
    """Portal del distribuidor que recibe el pedido."""
    if bodega and bodega.get("es_test"):
        return ZOOM_DISTRIBUIDOR_ID
    return DIMAX_DISTRIBUIDOR_ID
