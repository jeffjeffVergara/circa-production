"""Tests del gate Express Onboarding (allowlist)."""

import os

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


def test_default_pilot_phones_when_enabled(monkeypatch):
    monkeypatch.setenv("EXPRESS_ONBOARDING_ENABLED", "true")
    assert gate.is_express_pilot_phone("942616682")
    assert gate.is_express_pilot_phone("+51993557282")
    assert gate.is_express_pilot_phone("954712581")
    assert not gate.is_express_pilot_phone("999999999")


def test_disabled_master_switch(monkeypatch):
    monkeypatch.setenv("EXPRESS_ONBOARDING_ENABLED", "false")
    assert not gate.is_express_pilot_phone("942616682")


def test_custom_allowlist(monkeypatch):
    monkeypatch.setenv("EXPRESS_ONBOARDING_ENABLED", "true")
    monkeypatch.setenv("EXPRESS_ONBOARDING_PHONES", "999888777")
    assert gate.is_express_pilot_phone("999888777")
    assert not gate.is_express_pilot_phone("942616682")


def test_should_use_express_inactive_bodega(monkeypatch):
    monkeypatch.setenv("EXPRESS_ONBOARDING_ENABLED", "true")
    tel = "+51942616682"
    bodega = {"id": "x", "estado": "inactivo"}
    assert gate.should_use_express_onboarding(tel, bodega, None) is True
    assert gate.should_use_express_onboarding(tel, {"estado": "activo"}, None) is False
    assert gate.should_use_express_onboarding(
        tel, {"estado": "activo"}, {"fase": "express_foto"}
    ) is True
    assert gate.should_use_express_onboarding(tel, None, None) is True
    assert gate.should_use_express_onboarding("+51999999999", bodega, None) is False
