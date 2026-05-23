"""Tests for WhatsApp response latency tracking."""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from app.services import analytics


def test_normalize_telefono_adds_plus():
    assert analytics._normalize_telefono("51999111222") == "+51999111222"
    assert analytics._normalize_telefono("+51999111222") == "+51999111222"


def test_pending_consume_first_outbound_only():
    analytics._pending_inbound._at.clear()
    analytics._pending_inbound.register("+51999111222")
    ms1 = analytics._pending_inbound.consume("+51999111222")
    ms2 = analytics._pending_inbound.consume("+51999111222")
    assert ms1 is not None
    assert ms1 >= 0
    assert ms2 is None


def test_resolve_prefers_explicit():
    analytics._pending_inbound._at.clear()
    analytics._pending_inbound.register("+51999111222")
    assert analytics.resolve_outbound_response_time_ms("+51999111222", 1234) == 1234


@patch("app.services.analytics.db")
def test_response_time_from_db_when_no_pending(mock_db):
    analytics._pending_inbound._at.clear()
    inbound_at = "2026-05-20T12:00:00+00:00"
    now = datetime(2026, 5, 20, 12, 0, 2, tzinfo=timezone.utc)

    inbound_exec = MagicMock(data=[{"created_at": inbound_at}])
    outbound_exec = MagicMock(data=[])

    inbound_chain = MagicMock()
    inbound_chain.select.return_value.eq.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value = inbound_exec

    outbound_chain = MagicMock()
    outbound_chain.select.return_value.eq.return_value.eq.return_value.gte.return_value.limit.return_value.execute.return_value = outbound_exec

    mock_db.sb.table.side_effect = [inbound_chain, outbound_chain]

    with patch("app.services.analytics.datetime") as mock_dt:
        mock_dt.now.return_value = now
        mock_dt.fromisoformat = datetime.fromisoformat
        ms = analytics._response_time_ms_from_db("+51999111222")

    assert ms == 2000


@patch("app.services.analytics.db")
def test_response_time_from_db_skips_if_already_replied(mock_db):
    analytics._pending_inbound._at.clear()
    inbound_exec = MagicMock(data=[{"created_at": "2026-05-20T12:00:00+00:00"}])
    outbound_exec = MagicMock(data=[{"id": "existing"}])

    inbound_chain = MagicMock()
    inbound_chain.select.return_value.eq.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value = inbound_exec
    outbound_chain = MagicMock()
    outbound_chain.select.return_value.eq.return_value.eq.return_value.gte.return_value.limit.return_value.execute.return_value = outbound_exec

    mock_db.sb.table.side_effect = [inbound_chain, outbound_chain]
    assert analytics._response_time_ms_from_db("+51999111222") is None


@patch("app.services.analytics.track_event")
@patch("app.services.analytics.db")
def test_track_message_outbound_sets_latency(mock_db, _track_event):
    analytics._pending_inbound._at.clear()
    analytics._pending_inbound.register("+51999111222")

    table = MagicMock()
    mock_db.sb.table.return_value = table

    analytics.track_message(
        telefono="51999111222",
        direction="outbound",
        message_type="text",
        content="hola",
    )

    payload = table.insert.call_args[0][0]
    assert "response_time_ms" in payload
    assert payload["response_time_ms"] >= 0
