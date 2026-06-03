"""Auditoría de acciones del backoffice."""
from __future__ import annotations

import logging
from typing import Any

from app.services import db
from app.services.analytics import track_event

logger = logging.getLogger("circa.backoffice")


def log_action(
    *,
    user: dict,
    action: str,
    entity_type: str,
    entity_id: str | None = None,
    comment: str | None = None,
    before: dict | None = None,
    after: dict | None = None,
    bodega_id: str | None = None,
    pedido_id: str | None = None,
) -> None:
    metadata: dict[str, Any] = {
        "action": action,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "user_email": user.get("email"),
        "user_id": user.get("id"),
        "comment": comment,
    }
    if before is not None:
        metadata["before"] = before
    if after is not None:
        metadata["after"] = after

    track_event(
        f"backoffice_{action}",
        bodega_id=bodega_id,
        pedido_id=pedido_id,
        source="backoffice",
        channel="web",
        metadata=metadata,
    )

    row = {
        "user_id": user.get("id"),
        "user_email": user.get("email"),
        "action": action,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "comment": comment,
        "before_json": before,
        "after_json": after,
    }
    try:
        db.sb.table("backoffice_audit_log").insert(row).execute()
    except Exception as e:
        logger.debug("backoffice_audit_log insert skipped: %s", e)
