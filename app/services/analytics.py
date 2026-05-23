"""Lightweight analytics/event tracking helpers."""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any

from app.services import db

logger = logging.getLogger(__name__)

# Máximo tiempo para atribuir una respuesta al último inbound (evita proactivos viejos).
MAX_RESPONSE_LATENCY_MS = 600_000  # 10 min


def _as_json(value: dict[str, Any] | None) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _normalize_telefono(telefono: str) -> str:
    t = (telefono or "").strip().replace(" ", "")
    if t and not t.startswith("+"):
        t = f"+{t}"
    return t


def _parse_ts(val: Any) -> datetime:
    if isinstance(val, datetime):
        dt = val
    else:
        dt = datetime.fromisoformat(str(val).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


class _PendingInboundClock:
    """Marca de tiempo (monotonic) del último inbound por teléfono en este proceso."""

    def __init__(self) -> None:
        self._at: dict[str, float] = {}

    def register(self, telefono: str) -> None:
        self._at[_normalize_telefono(telefono)] = time.monotonic()

    def consume(self, telefono: str) -> int | None:
        key = _normalize_telefono(telefono)
        t0 = self._at.pop(key, None)
        if t0 is None:
            return None
        ms = int((time.monotonic() - t0) * 1000)
        if ms < 0:
            return 0
        if ms > MAX_RESPONSE_LATENCY_MS:
            return None
        return ms


_pending_inbound = _PendingInboundClock()


def _response_time_ms_from_db(telefono: str) -> int | None:
    """Fallback si el outbound corre en otro worker o tras reinicio."""
    tel = _normalize_telefono(telefono)
    try:
        inbound_r = (
            db.sb.table("messages")
            .select("created_at")
            .eq("telefono", tel)
            .eq("direction", "inbound")
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        if not inbound_r.data:
            return None
        inbound_at = _parse_ts(inbound_r.data[0]["created_at"])
        since = inbound_at.isoformat()

        out_r = (
            db.sb.table("messages")
            .select("id")
            .eq("telefono", tel)
            .eq("direction", "outbound")
            .gte("created_at", since)
            .limit(1)
            .execute()
        )
        if out_r.data:
            return None

        now = datetime.now(timezone.utc)
        ms = int((now - inbound_at).total_seconds() * 1000)
        if ms < 0 or ms > MAX_RESPONSE_LATENCY_MS:
            return None
        return ms
    except Exception:
        return None


def resolve_outbound_response_time_ms(
    telefono: str,
    explicit_ms: int | None = None,
    *,
    measure: bool = True,
) -> int | None:
    """Primera respuesta outbound tras inbound: ms hasta el envío."""
    if not measure:
        return explicit_ms
    if explicit_ms is not None:
        return int(explicit_ms)
    ms = _pending_inbound.consume(telefono)
    if ms is not None:
        return ms
    return _response_time_ms_from_db(telefono)


def track_event(
    event_type: str,
    *,
    bodega_id: str | None = None,
    pedido_id: str | None = None,
    telefono: str | None = None,
    source: str = "system",
    channel: str = "whatsapp",
    metadata: dict[str, Any] | None = None,
) -> None:
    """Insert an event without breaking business flow on failure."""
    try:
        payload = {
            "event_type": event_type,
            "source": source,
            "channel": channel,
            "metadata": _as_json(metadata),
        }
        if bodega_id:
            payload["bodega_id"] = bodega_id
        if pedido_id:
            payload["pedido_id"] = pedido_id
        if telefono:
            payload["telefono"] = telefono
        db.sb.table("events").insert(payload).execute()
    except Exception:
        # Never fail runtime path because analytics write failed
        return


def track_message(
    *,
    telefono: str,
    direction: str,
    bodega_id: str | None = None,
    message_id: str | None = None,
    message_type: str | None = None,
    content: str | None = None,
    template_name: str | None = None,
    reply_to_message_id: str | None = None,
    response_time_ms: int | None = None,
    metadata: dict[str, Any] | None = None,
    measure_response_latency: bool = True,
) -> None:
    """Insert message and mirrored message event."""
    tel = _normalize_telefono(telefono)
    rt_ms: int | None = None

    if direction == "inbound":
        _pending_inbound.register(tel)
        rt_ms = response_time_ms
    elif direction == "outbound":
        rt_ms = resolve_outbound_response_time_ms(
            tel, response_time_ms, measure=measure_response_latency
        )
    else:
        rt_ms = response_time_ms

    try:
        payload = {
            "telefono": tel,
            "direction": direction,
            "message_type": message_type or "",
            "content": (content or "")[:4000],
            "template_name": template_name or "",
            "reply_to_message_id": reply_to_message_id or "",
            "metadata": _as_json(metadata),
        }
        if bodega_id:
            payload["bodega_id"] = bodega_id
        if message_id:
            payload["message_id"] = message_id
        if rt_ms is not None:
            payload["response_time_ms"] = int(rt_ms)
        db.sb.table("messages").insert(payload).execute()
        if direction == "outbound" and rt_ms is not None:
            logger.info("response_time_ms telefono=%s ms=%s type=%s", tel, rt_ms, message_type or "")
    except Exception:
        return

    ev_meta: dict[str, Any] = {
        "message_id": message_id or "",
        "message_type": message_type or "",
        "template_name": template_name or "",
    }
    if rt_ms is not None and direction == "outbound":
        ev_meta["response_time_ms"] = rt_ms

    ev = "message_replied" if direction == "inbound" else "message_sent"
    track_event(
        ev,
        bodega_id=bodega_id,
        telefono=tel,
        source="whatsapp_webhook" if direction == "inbound" else "meta_client",
        metadata=ev_meta,
    )


def get_bodega_features(bodega_id: str) -> dict[str, Any]:
    """Read precomputed feature row from SQL view."""
    row = (
        db.sb.table("bodega_features_v1")
        .select("*")
        .eq("bodega_id", bodega_id)
        .limit(1)
        .execute()
    )
    if row.data:
        return row.data[0]
    return {"bodega_id": bodega_id}
