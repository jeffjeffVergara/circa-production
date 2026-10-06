"""Tests del gate Express Onboarding (vendedores + teléfonos explícitos)."""

import pytest

from app.services import express_onboarding_gate as gate


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch):
    monkeypatch.delenv("EXPRESS_ONBOARDING_ENABLED", raising=False)
    monkeypatch.delenv("EXPRESS_ONBOARDING_PHONES", raising=False)
    monkeypatch.delenv("EXPRESS_ONBOARDING_VENDEDORES", raising=False)
    monkeypatch.setattr(gate, "_lookup_vendor_codes", lambda bodega_id: set())


def test_normalize_phone():
    assert gate.normalize_phone_e164("942616682") == "+51942616682"
    assert gate.normalize_phone_e164("51942616682") == "+51942616682"
    assert gate.normalize_phone_e164("+51942616682") == "+51942616682"


def test_no_default_phones_when_enabled(monkeypatch):
    monkeypatch.setenv("EXPRESS_ONBOARDING_ENABLED", "true")
    assert gate.express_pilot_phones() == set()
    assert not gate.is_express_allowlist_phone("942616682")
    assert not gate.should_use_express_onboarding("+51942616682", None, None)


def test_disabled_by_default(monkeypatch):
    monkeypatch.delenv("EXPRESS_ONBOARDING_ENABLED", raising=False)
    assert gate.express_onboarding_enabled() is False
    assert not gate.should_use_express_onboarding(
        "+51942616682",
        {"estado": "inactivo", "es_test": True, "vendedor_codigo": "V0034"},
        None,
    )
    assert not gate.should_use_express_onboarding(
        "+51942616682",
        {"estado": "activo", "es_test": True, "vendedor_codigo": "V0034"},
        {"fase": "express_foto"},
    )


def test_disabled_master_switch(monkeypatch):
    monkeypatch.setenv("EXPRESS_ONBOARDING_ENABLED", "false")
    monkeypatch.setenv("EXPRESS_ONBOARDING_VENDEDORES", "V0034")
    assert not gate.is_express_allowlist_phone("942616682")
    assert not gate.qualifies_for_express(
        "942616682", {"es_test": True, "vendedor_codigo": "V0034"}
    )
    assert not gate.should_use_express_onboarding(
        "942616682",
        {"estado": "inactivo", "es_test": True, "vendedor_codigo": "V0034"},
        {"fase": "express_welcome"},
    )


def test_custom_allowlist(monkeypatch):
    monkeypatch.setenv("EXPRESS_ONBOARDING_ENABLED", "true")
    monkeypatch.setenv("EXPRESS_ONBOARDING_PHONES", "999888777")
    assert gate.is_express_allowlist_phone("999888777")
    assert not gate.is_express_allowlist_phone("942616682")


def test_es_test_no_alcanza(monkeypatch):
    monkeypatch.setenv("EXPRESS_ONBOARDING_ENABLED", "true")
    monkeypatch.setenv("EXPRESS_ONBOARDING_VENDEDORES", "V0034")
    tel = "+51999888777"
    assert gate.qualifies_for_express(tel, {"es_test": True}) is False
    assert gate.qualifies_for_express(tel, {"es_test": True, "vendedor_codigo": "V0099"}) is False
    assert gate.qualifies_for_express(tel, {"es_test": False, "vendedor_codigo": "V0034"}) is True


def test_solo_vendedores_de_la_lista(monkeypatch):
    monkeypatch.setenv("EXPRESS_ONBOARDING_ENABLED", "true")
    monkeypatch.setenv("EXPRESS_ONBOARDING_VENDEDORES", "V0034, v0014")
    tel = "+51999888777"
    en_lista = {"id": "x", "estado": "inactivo", "es_test": False, "vendedor_codigo": "v0034"}
    fuera = {"id": "y", "estado": "inactivo", "es_test": True, "vendedor_codigo": "V0007"}
    assert gate.should_use_express_onboarding(tel, en_lista, None) is True
    assert gate.should_use_express_onboarding(tel, fuera, None) is False
    assert gate.should_use_express_onboarding(
        tel, {"estado": "activo", "vendedor_codigo": "V0034"}, None
    ) is False
    assert gate.should_use_express_onboarding(
        tel,
        {"estado": "activo", "vendedor_codigo": "V0034"},
        {"fase": "express_foto"},
    ) is True
    assert gate.should_use_express_onboarding(
        tel, fuera, {"fase": "express_welcome"}
    ) is False


def test_lookup_de_cartera(monkeypatch):
    monkeypatch.setenv("EXPRESS_ONBOARDING_ENABLED", "true")
    monkeypatch.setenv("EXPRESS_ONBOARDING_VENDEDORES", "V0014")
    monkeypatch.setattr(gate, "_lookup_vendor_codes", lambda bodega_id: {"V0014"} if bodega_id == "b1" else set())
    assert gate.qualifies_for_express("+51911111111", {"id": "b1", "estado": "preaprobada"}) is True
    assert gate.qualifies_for_express("+51911111111", {"id": "b2", "estado": "preaprobada"}) is False


def test_should_use_express_allowlist_without_bodega(monkeypatch):
    monkeypatch.setenv("EXPRESS_ONBOARDING_ENABLED", "true")
    monkeypatch.setenv("EXPRESS_ONBOARDING_PHONES", "+51942616682")
    assert gate.should_use_express_onboarding("+51942616682", None, None) is True
    assert gate.should_use_express_onboarding("+51999999999", None, None) is False
