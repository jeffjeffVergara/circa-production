"""Tests módulo observabilidad cliente."""

import os

os.environ.setdefault("SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "test-key")

from app.services.client_observability import (
    _analytics_title,
    _digits_only,
    _phone_e164,
    _timeline_for_claude,
    _wa_message_title,
)


def test_digits_only():
    assert _digits_only("43 868-000") == "43868000"
    assert _digits_only("+51 956 277 521") == "51956277521"


def test_phone_e164():
    assert _phone_e164("956277521") == "+51956277521"
    assert _phone_e164("51956277521") == "+51956277521"


def test_wa_message_title_inbound():
    title = _wa_message_title({"direction": "inbound", "message_type": "text"})
    assert "entrada" in title
    assert "text" in title


def test_analytics_title_message_replied():
    assert "cliente respondió" in _analytics_title("message_replied")


def test_timeline_for_claude_includes_errors():
    timeline = {
        "bodega": {"razon_social": "Test", "telefono_whatsapp": "+51999999999"},
        "events": [
            {
                "at": "2026-07-03T12:00:00Z",
                "status": "error",
                "kind": "biometria",
                "title": "Selfie",
                "detail": "No es selfie valida",
            }
        ],
        "summary": {
            "last_error": {
                "title": "Selfie",
                "detail": "No es selfie valida",
            }
        },
    }
    text = _timeline_for_claude(timeline)
    assert "Test" in text
    assert "Selfie" in text
    assert "Último error" in text
