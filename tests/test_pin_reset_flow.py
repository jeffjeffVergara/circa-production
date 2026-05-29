"""Flujo Me olvidé mi clave."""
from app.services.pin_reset_flow import (
    is_olvide_trigger,
    msg_reset_intro,
    es_solo_dni,
    after_pin_created_responses,
)


def test_is_olvide_trigger():
    assert is_olvide_trigger("ME OLVIDE MI CLAVE")
    assert is_olvide_trigger("OLVIDE_CLAVE")
    assert not is_olvide_trigger("PEDIDO")


def test_msg_reset_intro_solo_dni():
    text = msg_reset_intro({"solo_dni_sin_ruc": True})
    assert "DNI" in text
    assert "representante legal" not in text.lower() or "8 dígitos" in text


def test_msg_reset_intro_ruc():
    text = msg_reset_intro({
        "solo_dni_sin_ruc": False,
        "ruc": "20123456789",
        "representante_legal": "JUAN PEREZ LOPEZ",
    })
    assert "RUC" in text
    assert "JUAN PEREZ LOPEZ" in text


def test_es_solo_dni():
    assert es_solo_dni({"solo_dni_sin_ruc": True})
    assert not es_solo_dni({"solo_dni_sin_ruc": False})


def test_after_pin_created_without_preserve():
    from unittest.mock import patch
    with patch("app.services.pin_reset_flow.db") as mock_db:
        out = after_pin_created_responses("+51999", "b1", {}, 500.0)
    assert out[0]["signal"] == "CUENTA_ACTIVA"
    mock_db.upsert_session.assert_not_called()
