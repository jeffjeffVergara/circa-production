"""Tests — enrutamiento DIMAX/ZOOM (multi-distribuidor desde jun-2026)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.distribuidor_routing import (
    DIMAX_DISTRIBUIDOR_ID,
    distribuidor_id_para_catalogo,
    distribuidor_id_para_pedido,
)


def test_catalogo_legacy_default_dimax():
    assert distribuidor_id_para_catalogo() == DIMAX_DISTRIBUIDOR_ID
    assert distribuidor_id_para_catalogo({"es_test": True}) == DIMAX_DISTRIBUIDOR_ID


def test_pedido_legacy_default_dimax():
    """Desde jun-2026 el default legacy ya no rutea test → ZOOM."""
    assert distribuidor_id_para_pedido({"es_test": True}) == DIMAX_DISTRIBUIDOR_ID
    assert distribuidor_id_para_pedido({"es_test": False}) == DIMAX_DISTRIBUIDOR_ID


def test_get_distribuidor_de_bodega_multi(monkeypatch):
    import os

    os.environ.setdefault("SUPABASE_URL", "http://localhost")
    os.environ.setdefault("SUPABASE_SERVICE_KEY", "test-key")
    from app.services import db

    monkeypatch.setattr(
        db,
        "get_distribuidores_de_bodega",
        lambda _bid: ["zoom-id", DIMAX_DISTRIBUIDOR_ID],
    )
    assert db.get_distribuidor_de_bodega("bodega-1") == DIMAX_DISTRIBUIDOR_ID

    monkeypatch.setattr(db, "get_distribuidores_de_bodega", lambda _bid: ["zoom-id"])
    assert db.get_distribuidor_de_bodega("bodega-1") == "zoom-id"

    monkeypatch.setattr(db, "get_distribuidores_de_bodega", lambda _bid: [])
    assert db.get_distribuidor_de_bodega("bodega-1") == DIMAX_DISTRIBUIDOR_ID
