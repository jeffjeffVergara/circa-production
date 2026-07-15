"""Tests onboarding Fast Track: saltar RUC/DNI precargado + atajo parcial sin foto."""

import os
from unittest.mock import patch

os.environ.setdefault("SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "test-key")
os.environ.setdefault("SUPABASE_KEY", "test-key")

from app.state_machine import (
    _bodega_dni_precargado,
    _bodega_dni_sin_foto,
    _bodega_tiene_ruc,
    _enter_reg_dni,
    normalize,
)


def test_bodega_tiene_ruc():
    assert _bodega_tiene_ruc({"ruc": "20123456789"}) is True
    assert _bodega_tiene_ruc({"ruc": "  "}) is False
    assert _bodega_tiene_ruc({}) is False
    assert _bodega_tiene_ruc(None) is False


def test_bodega_dni_precargado_requiere_tres_condiciones():
    base = {
        "kyc_nivel": "dni",
        "dni_representante": "42868000",
        "dni_foto_url": "prospecto/+51/dni.jpg",
    }
    assert _bodega_dni_precargado(base) is True
    assert _bodega_dni_precargado({**base, "kyc_nivel": "ninguno"}) is False
    assert _bodega_dni_precargado({**base, "dni_representante": ""}) is False
    assert _bodega_dni_precargado({**base, "dni_foto_url": None}) is False


def test_bodega_dni_sin_foto():
    assert _bodega_dni_sin_foto({
        "dni_representante": "70366741",
        "dni_foto_url": None,
        "kyc_nivel": "ninguno",
    }) is True
    assert _bodega_dni_sin_foto({
        "dni_representante": "70366741",
        "dni_foto_url": "prospecto/x.jpg",
    }) is False
    assert _bodega_dni_sin_foto({"dni_representante": "", "dni_foto_url": None}) is False


def test_enter_reg_dni_parcial_pide_solo_foto():
    bodega = {
        "id": "b1",
        "dni_representante": "70366741",
        "dni_foto_url": None,
        "kyc_nivel": "ninguno",
        "representante_legal": "ZAPLER LABARTHE, TIAGO",
        "solo_dni_sin_ruc": True,
    }
    with patch("app.state_machine.db.upsert_session"):
        resp = _enter_reg_dni("+51949260527", bodega, {})
    assert resp[0]["signal"] == "DNI_FOTO_ASK"
    assert resp[0]["dni"] == "70366741"


def test_enter_reg_dni_completo_confirma():
    bodega = {
        "id": "b1",
        "dni_representante": "70366741",
        "dni_foto_url": "prospecto/dni.jpg",
        "kyc_nivel": "dni",
        "representante_legal": "ZAPLER",
    }
    with patch("app.state_machine.db.upsert_session"):
        resp = _enter_reg_dni("+51949260527", bodega, {})
    assert resp[0]["signal"] == "DNI_PREFILL_CONFIRM"


def test_normalize_button_ids():
    assert normalize("DNI_SOY_YO") == "DNI_SOY_YO"
    assert normalize("sí, soy yo") == "SI, SOY YO"
