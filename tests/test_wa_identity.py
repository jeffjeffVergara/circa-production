"""Destino de WhatsApp: teléfono o identificador de usuario."""
from app.services.meta_client import send_template_sync, send_text_sync
from app.services.wa_identity import clave_conversacion, direccion_envio, telefono_para_log


def test_con_telefono_la_clave_sigue_siendo_el_numero():
    assert clave_conversacion("51933930934", "PE.1105797845152248") == "+51933930934"


def test_sin_telefono_la_clave_es_el_identificador():
    assert clave_conversacion("", "PE.1105797845152248") == "PE.1105797845152248"
    assert clave_conversacion(None, None) == ""


def test_direccion_de_telefono_va_en_to():
    assert direccion_envio("+51933930934") == {"to": "51933930934"}
    assert direccion_envio("") == {}
    assert direccion_envio("+") == {}


def test_direccion_de_usuario_va_en_recipient():
    assert direccion_envio("PE.1105797845152248") == {"recipient": "PE.1105797845152248"}
    assert telefono_para_log("PE.1105797845152248") == "PE.1105797845152248"
    assert telefono_para_log("51933930934") == "+51933930934"
    assert telefono_para_log("") == ""


class _Resp:
    def __init__(self, status, body="{}"):
        self.status_code = status
        self.text = body

    def json(self):
        return {"messages": [{"id": "wamid.x"}]}


def test_no_llama_a_meta_si_no_hay_destino(monkeypatch):
    def boom(*_a, **_k):
        raise AssertionError("no debe llamar a Graph")

    monkeypatch.setattr("app.services.meta_client.httpx.post", boom)
    monkeypatch.setattr("app.services.meta_client._access_token", lambda: "token")
    monkeypatch.setattr("app.services.meta_client._log_envio", lambda **_k: None)
    assert send_text_sync("+", "hola") is False


def test_usuario_de_whatsapp_se_envia_como_recipient(monkeypatch):
    seen = {}

    def fake_post(_url, headers=None, json=None, timeout=None):
        seen["json"] = json
        return _Resp(200)

    monkeypatch.setattr("app.services.meta_client.httpx.post", fake_post)
    monkeypatch.setattr("app.services.meta_client._access_token", lambda: "token")
    monkeypatch.setattr("app.services.meta_client._phone_number_id", lambda: "107")
    monkeypatch.setattr("app.services.meta_client._log_envio", lambda **_k: None)
    assert send_text_sync("PE.1105797845152248", "hola") is True
    assert seen["json"]["recipient"] == "PE.1105797845152248"
    assert "to" not in seen["json"]
    assert seen["json"]["text"]["body"] == "hola"


def test_telefono_sigue_yendo_en_to(monkeypatch):
    seen = {}

    def fake_post(_url, headers=None, json=None, timeout=None):
        seen["json"] = json
        return _Resp(200)

    monkeypatch.setattr("app.services.meta_client.httpx.post", fake_post)
    monkeypatch.setattr("app.services.meta_client._access_token", lambda: "token")
    monkeypatch.setattr("app.services.meta_client._phone_number_id", lambda: "107")
    monkeypatch.setattr("app.services.meta_client._log_envio", lambda **_k: None)
    assert send_text_sync("+51933930934", "hola") is True
    assert seen["json"]["to"] == "51933930934"
    assert "recipient" not in seen["json"]


def test_precarga_no_repite_el_aviso_en_la_ventana(monkeypatch):
    from app.services.cuenta_lista_wa import notificar_cuenta_lista

    monkeypatch.setattr("app.services.cuenta_lista_wa._ya_avisada", lambda _t: True)

    def boom(*_a, **_k):
        raise AssertionError("no debe reenviar la plantilla")

    monkeypatch.setattr("app.services.meta_client.send_template_sync", boom)
    assert notificar_cuenta_lista("+51933930934", "Richar", "bodega-1") is False


def test_plantilla_sin_destino_no_llama_a_meta(monkeypatch):
    def boom(*_a, **_k):
        raise AssertionError("no debe llamar a Graph")

    monkeypatch.setattr("app.services.meta_client.httpx.post", boom)
    monkeypatch.setattr("app.services.meta_client._log_envio", lambda **_k: None)
    ok, err = send_template_sync("", "circa_cuenta_lista")
    assert ok is False
    assert err == "sin destino"
