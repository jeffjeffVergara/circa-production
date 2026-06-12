"""
Enrutamiento de distribuidores (DIMAX + ZOOM).

Historial:
- Piloto (hasta jun-2026): catálogo siempre DIMAX; los pedidos de bodegas
  test se ruteaban a ZOOM como balde de pruebas para no ensuciar el portal
  de DIMAX.
- Desde 12-jun-2026: ZOOM CORP S.A.C. (RUC 20524821860) es un distribuidor
  REAL — segunda razón social de la misma operación del distribuidor del
  piloto. La separación test/real ya NO usa el distribuidor: usa
  bodegas.es_test (filtro modo real/test del portal).

Reglas vigentes:
- Catálogo: multi-distribuidor vía tabla bodega_distribuidores
  (ver db.get_distribuidores_de_bodega). Default legacy: DIMAX.
- Pedidos (catálogo web): el distribuidor se resuelve desde los productos
  del carrito (catalogo_distribuidor.distribuidor_id), no desde la bodega.
  Ver submit_cart en app/main.py.
- Carritos que mezclan distribuidores: rechazados temporalmente hasta que
  exista el split por grupo de compra (pedidos.grupo_compra_id).
"""

from __future__ import annotations

ZOOM_DISTRIBUIDOR_ID = "a1b2c3d4-0001-4000-8000-000000000001"
DIMAX_DISTRIBUIDOR_ID = "d1a2b3c4-0001-4000-8000-000000000002"


def distribuidor_id_para_catalogo(_bodega: dict | None = None) -> str:
    """Default legacy para callers que aún no son multi-distribuidor."""
    return DIMAX_DISTRIBUIDOR_ID


def distribuidor_id_para_pedido(bodega: dict | None) -> str:
    """
    Default legacy. Desde 12-jun-2026 las bodegas test ya NO rutean a ZOOM
    (ZOOM es un distribuidor real con conciliación propia); la separación
    test/real es responsabilidad del filtro es_test del portal.
    """
    return DIMAX_DISTRIBUIDOR_ID
