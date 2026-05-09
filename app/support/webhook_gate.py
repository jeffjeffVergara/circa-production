"""Meta WhatsApp webhook integration — bot stand-down while human owns the thread."""

from __future__ import annotations

from dataclasses import dataclass

from app.support.service import handle_customer_whatsapp_message


@dataclass(frozen=True)
class MetaInboundDecision:
    """When ``skip_remaining_handlers`` is True, skip flows, commerce buttons, and state machine."""

    skip_remaining_handlers: bool


async def process_meta_inbound(
    *,
    telefono: str,
    body_text: str,
    msg: dict,
    bodega_id: str | None,
    contact_name: str | None,
) -> MetaInboundDecision:
    skip = await handle_customer_whatsapp_message(
        telefono=telefono,
        body_text=body_text,
        msg=msg,
        bodega_id=bodega_id,
        contact_name=contact_name,
    )
    return MetaInboundDecision(skip_remaining_handlers=skip)
