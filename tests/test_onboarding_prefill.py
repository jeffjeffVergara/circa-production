"""Tests onboarding Fast Track: saltar RUC/DNI precargado."""

import os

os.environ.setdefault("SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "test-key")

from app.state_machine import (
    _bodega_dni_precargado,
    _bodega_tiene_ruc,
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


def test_normalize_button_ids():
    assert normalize("DNI_SOY_YO") == "DNI_SOY_YO"
    assert normalize("sí, soy yo") == "SI, SOY YO"
