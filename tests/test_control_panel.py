"""Tests Control Panel (lookup / PIN status)."""

import os
from datetime import datetime, timedelta, timezone

os.environ.setdefault("SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "test-key")

from app.services.control_panel import _parse_session_datos, _pin_status


def test_parse_session_datos_dict():
    assert _parse_session_datos({"cart": []}) == {"cart": []}


def test_parse_session_datos_json_string():
    assert _parse_session_datos('{"step": 1}') == {"step": 1}


def test_pin_status_no_pin():
    st = _pin_status({"pin_hash": None, "pin_intentos": 0})
    assert st["has_pin"] is False
    assert st["bloqueado"] is False


def test_pin_status_blocked_future():
    future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    st = _pin_status({"pin_hash": "x", "pin_intentos": 3, "pin_bloqueado_hasta": future})
    assert st["has_pin"] is True
    assert st["bloqueado"] is True
    assert st["intentos"] == 3
