"""Tests simplificación flujo preventa (plazo fijo 7d)."""

import os

os.environ.setdefault("SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "test-key")

from app.services.meta_commerce_handlers import _is_draft_status


def test_draft_status_incluye_preventa_confirmada():
    assert _is_draft_status("preventa_confirmada") is True
    assert _is_draft_status("borrador") is True
    assert _is_draft_status("confirmado") is False
    assert _is_draft_status("recibido") is False


def test_hours_helper_importable():
    from app.flows.catalogo import _hours_since_last_inbound

    assert callable(_hours_since_last_inbound)
