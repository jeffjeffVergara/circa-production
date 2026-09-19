"""Tests del gate Express Onboarding (allowlist + es_test)."""

import pytest

from app.services import express_onboarding_gate as gate


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch):
    monkeypatch.delenv("EXPRESS_ONBOARDING_ENABLED", raising=False)
    monkeypatch.delenv("EXPRESS_ONBOARDING_PHONES", raising=False)


def test_normalize_phone():
    assert gate.normalize_phone_e164("942616682") == "+51942616682"
    assert gate.normalize_phone_e164("51942616682") == "+51942616682"
    assert gate.normalize_phone_e164("+51942616682") == "+51942616682"


def test_default_allowlist_when_enabled(monkeypatch):
    monkeypatch.setenv("EXPRESS_ONBOARDING_ENABLED", "true")
    assert gate.is_express_allowlist_phone("942616682")
    assert gate.is_express_allowlist_phone("+51993557282")
    assert gate.is_express_allowlist_phone("954712581")
    assert not gate.is_express_allowlist_phone("999999999")


def test_disabled_by_default(monkeypatch):
    monkeypatch.delenv("EXPRESS_ONBOARDING_ENABLED", raising=False)
    assert gate.express_onboarding_enabled() is False
    assert not gate.should_use_express_onboarding(
        "+51942616682", {"estado": "inactivo", "es_test": True}, None
    )
    # Sesiones express_* no quedan atrapadas si el master está off
    assert not gate.should_use_express_onboarding(
        "+51942616682",
        {"estado": "activo", "es_test": True},
        {"fase": "express_foto"},
    )


def test_disabled_master_switch(monkeypatch):
    monkeypatch.setenv("EXPRESS_ONBOARDING_ENABLED", "false")
    assert not gate.is_express_allowlist_phone("942616682")
    assert not gate.qualifies_for_express("942616682", {"es_test": True})
    assert not gate.should_use_express_onboarding(
        "942616682",
        {"estado": "inactivo", "es_test": True},
        {"fase": "express_welcome"},
    )


def test_custom_allowlist(monkeypatch):
    monkeypatch.setenv("EXPRESS_ONBOARDING_ENABLED", "true")
    monkeypatch.setenv("EXPRESS_ONBOARDING_PHONES", "999888777")
    assert gate.is_express_allowlist_phone("999888777")
    assert not gate.is_express_allowlist_phone("942616682")


def test_es_test_bodega_qualifies_without_allowlist(monkeypatch):
    monkeypatch.setenv("EXPRESS_ONBOARDING_ENABLED", "true")
    monkeypatch.setenv("EXPRESS_ONBOARDING_PHONES", "111111111")
    tel = "+51999888777"
    assert not gate.is_express_allowlist_phone(tel)
    assert gate.qualifies_for_express(tel, {"es_test": True}) is True
    assert gate.qualifies_for_express(tel, {"es_test": False}) is False
    assert gate.qualifies_for_express(tel, None) is False


def test_should_use_express_inactive_test_bodega(monkeypatch):
    monkeypatch.setenv("EXPRESS_ONBOARDING_ENABLED", "true")
    monkeypatch.setenv("EXPRESS_ONBOARDING_PHONES", "111111111")
    tel = "+51999888777"
    bodega_test = {"id": "x", "estado": "inactivo", "es_test": True}
    assert gate.should_use_express_onboarding(tel, bodega_test, None) is True
    assert gate.should_use_express_onboarding(
        tel, {"estado": "activo", "es_test": True}, None
    ) is False
    assert gate.should_use_express_onboarding(
        tel, {"estado": "activo", "es_test": True}, {"fase": "express_foto"}
    ) is True
    assert gate.should_use_express_onboarding(
        tel, {"estado": "inactivo", "es_test": False}, None
    ) is False


def test_should_use_express_allowlist_without_bodega(monkeypatch):
    monkeypatch.setenv("EXPRESS_ONBOARDING_ENABLED", "true")
    tel = "+51942616682"
    assert gate.should_use_express_onboarding(tel, None, None) is True
    assert gate.should_use_express_onboarding("+51999999999", None, None) is False
