"""Tests flujo WhatsApp vendedor."""
import os

os.environ["SUPABASE_URL"] = "http://localhost"
os.environ["SUPABASE_SERVICE_KEY"] = "test-key"

from app.services import vendedor_wa as vw


def test_should_route_vendedor_solo_telefono():
    v = {"id": "v1", "activo": True}
    assert vw.should_route_to_vendedor(v, None, None) is True


def test_should_route_vendedor_fase_vend():
    v = {"id": "v1", "activo": True}
    session = {"fase": "vend_menu", "datos": "{}"}
    assert vw.should_route_to_vendedor(v, {"id": "b1"}, session) is True


def test_no_route_dual_sin_sesion():
    v = {"id": "v1", "activo": True}
    b = {"id": "b1"}
    assert vw.should_route_to_vendedor(v, b, None) is False
    assert vw.should_show_actor_chooser(v, b, None) is True


def test_no_route_bodeguero_en_sesion():
    v = {"id": "v1", "activo": True}
    b = {"id": "b1"}
    session = {"fase": "menu", "datos": "{}"}
    assert vw.should_route_to_vendedor(v, b, session) is False


def test_catalog_url_includes_vt():
    url = vw._catalog_url_vendedor("tok123", "bodega-uuid")
    assert "vt=tok123" in url
    assert "t=preventa" in url
    assert "bodega-uuid" in url


def test_wa_pedido_link():
    link = vw._wa_pedido_link("abc123def456")
    assert "Pedido%20abc123def456" in link
