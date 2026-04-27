"""Lightweight analytics/event tracking helpers."""

from __future__ import annotations

from typing import Any

from app.services import db


def _as_json(value: dict[str, Any] | None) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


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
) -> None:
    """Insert message and mirrored message event."""
    try:
        payload = {
            "telefono": telefono,
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
        if response_time_ms is not None:
            payload["response_time_ms"] = int(response_time_ms)
        db.sb.table("messages").insert(payload).execute()
    except Exception:
        return

    ev = "message_replied" if direction == "inbound" else "message_sent"
    track_event(
        ev,
        bodega_id=bodega_id,
        telefono=telefono,
        source="whatsapp_webhook" if direction == "inbound" else "meta_client",
        metadata={
            "message_id": message_id or "",
            "message_type": message_type or "",
            "template_name": template_name or "",
        },
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
