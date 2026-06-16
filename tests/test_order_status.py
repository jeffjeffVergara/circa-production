"""Tests for unified order status module."""
from app.services.order_status import (
    can_transition,
    normalize_estado,
    next_estado,
)


def test_legacy_alias_preparando():
    assert normalize_estado("preparando") == "en_preparacion"


def test_portal_flow_chain():
    assert next_estado("confirmado") == "recibido"
    assert next_estado("recibido") == "en_preparacion"
    assert next_estado("en_camino") == "entregado"


def test_can_transition_full_path():
    assert can_transition("confirmado", "recibido")
    assert can_transition("recibido", "en_preparacion")
    assert can_transition("preparando", "despachado")  # alias → en_preparacion
    assert not can_transition("confirmado", "entregado")
