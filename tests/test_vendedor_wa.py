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


def test_bodega_identificacion_solo_dni():
    assert vw._bodega_identificacion({
        "ruc": None,
        "dni_representante": "46843088",
        "solo_dni_sin_ruc": True,
    }) == "DNI 46843088"


def test_bodega_identificacion_ruc_y_dni():
    text = vw._bodega_identificacion({
        "ruc": "20123456789",
        "dni_representante": "12345678",
    })
    assert "RUC 20123456789" in text
    assert "DNI 12345678" in text


def test_buscar_bodega_por_nombre_en_cartera(monkeypatch):
    vendedor = {"id": "v1", "es_admin": False, "distribuidor_id": "d1"}
    cartera = [{
        "id": "b1",
        "nombre_comercial": "Bodega Jeff",
        "razon_social": "Bodega Jeff SAC",
        "distrito": "Miraflores",
        "ruc": None,
        "dni_representante": "46843088",
        "solo_dni_sin_ruc": True,
        "linea_disponible": 500,
        "estado": "activo",
        "distribuidor_id": "d1",
    }]

    monkeypatch.setattr(vw, "_list_cartera", lambda v, limit=8: cartera)
    monkeypatch.setattr(vw, "_validar_bodega_para_vendedor", lambda v, b: None)

    bodega, err, matches = vw._buscar_bodega_por_nombre(vendedor, "Jeff")
    assert err is None
    assert matches == []
    assert bodega["nombre_comercial"] == "Bodega Jeff"
