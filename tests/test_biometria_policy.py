"""Tests política biometría demo para bodegas es_test."""
import os

os.environ.setdefault("BIOMETRIA_RELAX_FOR_TEST_BODEGAS", "true")

from app.services import biometria_policy as pol


def test_relaxed_for_es_test_bodega():
    assert pol.biometria_demo_relaxed({"es_test": True}) is True
    assert pol.biometria_demo_relaxed({"es_test": False}) is False
    assert pol.biometria_demo_relaxed(None) is False


def test_relaxed_disabled_by_flag(monkeypatch):
    monkeypatch.setenv("BIOMETRIA_RELAX_FOR_TEST_BODEGAS", "false")
    from importlib import reload
    from app import config

    reload(config)
    try:
        assert pol.biometria_demo_relaxed({"es_test": True}) is False
    finally:
        monkeypatch.setenv("BIOMETRIA_RELAX_FOR_TEST_BODEGAS", "true")
        reload(config)


def test_skip_via_test_phone():
    bodega = {"es_test": False}
    assert pol.skip_biometria_checks("+51999999999", bodega, test_phones={"+51999999999"}) is True


def test_skip_via_es_test_not_phone():
    bodega = {"es_test": True}
    assert pol.skip_biometria_checks("+51000000000", bodega, test_phones=set()) is True
