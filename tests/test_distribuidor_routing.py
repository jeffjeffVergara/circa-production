"""Tests — enrutamiento Zoom (pedidos test) vs DIMAX (catálogo y pedidos reales)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.distribuidor_routing import (
    DIMAX_DISTRIBUIDOR_ID,
    ZOOM_DISTRIBUIDOR_ID,
    distribuidor_id_para_catalogo,
    distribuidor_id_para_pedido,
)


def test_catalogo_siempre_dimax():
    assert distribuidor_id_para_catalogo() == DIMAX_DISTRIBUIDOR_ID
    assert distribuidor_id_para_catalogo({"es_test": True}) == DIMAX_DISTRIBUIDOR_ID
    assert distribuidor_id_para_catalogo({"es_test": False, "en_piloto": True}) == DIMAX_DISTRIBUIDOR_ID


def test_pedido_test_zoom_real_dimax():
    assert distribuidor_id_para_pedido({"es_test": True}) == ZOOM_DISTRIBUIDOR_ID
    assert distribuidor_id_para_pedido({"es_test": False, "en_piloto": True}) == DIMAX_DISTRIBUIDOR_ID
    assert distribuidor_id_para_pedido({"es_test": False, "en_piloto": False}) == DIMAX_DISTRIBUIDOR_ID
