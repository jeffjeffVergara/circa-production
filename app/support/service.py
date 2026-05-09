"""Support inbox application logic (WhatsApp + agent console orchestration)."""

from __future__ import annotations

import logging
import os
from typing import Any

from app.services.analytics import track_event, track_message

from app.support import repository as repo
from app.support.intents import detect_handover, detect_release_to_bot
from app.support.security import write_audit_log
from app.support.ws_hub import hub

logger = logging.getLogger("circa.support.service")


def _disabled() -> bool:
    return os.getenv("SUPPORT_INBOX_DISABLED", "").lower() in ("1", "true", "yes")


def _sla_minutes() -> int:
    try:
        return max(5, int(os.getenv("SUPPORT_SLA_MINUTES", "30")))
    except ValueError:
        return 30


async def apply_wa_status(update: dict[str, Any]) -> None:
    mid = update.get("message_id") or ""
    status = update.get("status") or ""
    if mid and status:
        repo.update_message_delivery(wa_message_id=mid, wa_status=status)


async def _broadcast(conversation_id: str | None, event: str, payload: dict[str, Any]) -> None:
    if conversation_id:
        payload = {**payload, "conversation_id": conversation_id}
    await hub.emit(event, payload)


async def _maybe_assign_round_robin(
    conversation_id: str,
    *,
    telefono_e164: str,
    bump_escalation: bool,
) -> dict[str, Any] | None:
    chosen = repo.pick_round_robin_agent()
    if not chosen:
        return None
    repo.bump_agent_assignment(chosen["id"])
    patch = {
        "assigned_agent_id": chosen["id"],
        "state": "HUMAN",
        "last_agent_activity_at": repo.utcnow_iso(),
    }
    if bump_escalation:
        patch["escalated_at"] = repo.utcnow_iso()
        patch["sla_due_at"] = repo.sla_deadline_iso(_sla_minutes())
    conv = repo.patch_conversation(conversation_id, patch)
    await _broadcast(
        conversation_id,
        "conversation_assigned",
        {"assigned_agent_id": chosen["id"], "telefono_e164": telefono_e164},
    )
    write_audit_log(
        actor_kind="system",
        action="assigned_round_robin",
        conversation_id=conversation_id,
        payload={"agent_id": chosen["id"]},
    )
    return conv


async def escalate_from_bot(
    *,
    conversation_row: dict[str, Any],
    customer_body: str,
    wa_message_id: str | None,
    meta_contact_name: str | None,
) -> None:
    cid = conversation_row["id"]
    tel = conversation_row["telefono_e164"]

    repo.insert_support_message(
        conversation_id=cid,
        direction="inbound",
        sender_kind="contact",
        body=customer_body,
        wa_message_id=wa_message_id,
        message_type="text",
        meta={"phase": "handover_trigger"},
    )
    repo.insert_support_message(
        conversation_id=cid,
        direction="outbound",
        sender_kind="system",
        body="Escalado a cola de soporte humano.",
        message_type="text",
        meta={"phase": "handover_system"},
    )

    now = repo.utcnow_iso()
    unread = int(conversation_row.get("unread_for_agents") or 0) + 1
    repo.patch_conversation(
        cid,
        {
            "state": "WAITING_AGENT",
            "escalated_at": now,
            "sla_due_at": repo.sla_deadline_iso(_sla_minutes()),
            "last_customer_activity_at": now,
            "unread_for_agents": unread,
            "contact_name": meta_contact_name or conversation_row.get("contact_name"),
            "first_customer_message_at": conversation_row.get("first_customer_message_at") or now,
        },
    )

    await _maybe_assign_round_robin(cid, telefono_e164=tel, bump_escalation=False)

    conv = repo.fetch_conversation(cid) or conversation_row
    state_after = conv.get("state")

    from app.services import meta_client

    if state_after == "HUMAN":
        msg = (
            "👋 Te estamos conectando con un asesor Circa.\n"
            "Continúa por este mismo WhatsApp; un agente te escribirá en breve.\n\n"
            "Cuando termines con el asesor, escribe *fin soporte* para volver al menú automático."
        )
    else:
        msg = (
            "👋 Recibimos tu solicitud de soporte.\n"
            "Un asesor Circa te escribirá pronto por este mismo número.\n\n"
            "Mientras tanto puedes seguir escribiendo aquí; tu mensaje quedará en cola."
        )
    await meta_client.send_text(tel.lstrip("+"), msg)

    track_event(
        "support_escalation",
        bodega_id=conv.get("bodega_id"),
        telefono=tel,
        source="whatsapp_webhook",
        metadata={
            "support_conversation_id": cid,
            "state_after": state_after,
            "had_online_agent": state_after == "HUMAN",
        },
    )

    await _broadcast(
        cid,
        "new_message",
        {
            "telefono_e164": tel,
            "snippet": (customer_body or "")[:280],
            "state": state_after,
            "unread_for_agents": int(conv.get("unread_for_agents") or unread),
        },
    )
    await _broadcast(
        cid,
        "unread_update",
        {"unread_for_agents": int(conv.get("unread_for_agents") or unread)},
    )

    write_audit_log(
        actor_kind="webhook",
        action="support_escalation",
        conversation_id=cid,
        payload={"customer_body": (customer_body or "")[:500]},
    )


async def close_conversation_public(
    *,
    conversation_row: dict[str, Any],
    reason: str,
    actor_agent_id: str | None,
    send_customer_notice: bool,
) -> dict[str, Any] | None:
    cid = conversation_row["id"]
    tel = conversation_row["telefono_e164"]
    now = repo.utcnow_iso()
    md = dict(conversation_row.get("metadata") or {})
    md["close_reason"] = reason
    patch = {
        "state": "CLOSED",
        "closed_at": now,
        "resolved_at": now,
        "assigned_agent_id": None,
        "unread_for_agents": 0,
        "metadata": md,
    }
    conv = repo.patch_conversation(cid, patch)

    if send_customer_notice:
        from app.services import meta_client

        await meta_client.send_text(
            tel.lstrip("+"),
            "✅ *Sesión de soporte cerrada*\n\n"
            "Volvimos al asistente automático de Circa.\n"
            "Escribe *MENU* cuando quieras ver opciones.",
        )

    await _broadcast(cid, "conversation_closed", {"reason": reason})
    write_audit_log(
        actor_kind="agent" if actor_agent_id else "system",
        action="conversation_closed",
        conversation_id=cid,
        actor_agent_id=actor_agent_id,
        payload={"reason": reason},
    )
    return conv


async def release_customer_to_bot(conversation_row: dict[str, Any]) -> None:
    await close_conversation_public(
        conversation_row=conversation_row,
        reason="customer_fin_soporte",
        actor_agent_id=None,
        send_customer_notice=True,
    )


async def ingest_human_queue_message(
    *,
    conversation_row: dict[str, Any],
    body_text: str,
    msg: dict[str, Any],
) -> None:
    cid = conversation_row["id"]
    tel = conversation_row["telefono_e164"]
    unread = int(conversation_row.get("unread_for_agents") or 0) + 1
    now = repo.utcnow_iso()

    repo.patch_conversation(
        cid,
        {
            "last_customer_activity_at": now,
            "unread_for_agents": unread,
            "updated_at": now,
        },
    )

    repo.insert_support_message(
        conversation_id=cid,
        direction="inbound",
        sender_kind="contact",
        body=body_text,
        wa_message_id=msg.get("message_id"),
        message_type=msg.get("type") or "text",
        media={
            "media_id": msg.get("media_id"),
            "mime_type": msg.get("mime_type"),
            "caption": msg.get("caption"),
            "filename": msg.get("filename"),
            "button_id": msg.get("button_id"),
            "list_id": msg.get("list_id"),
        },
        meta={"flow_data": bool(msg.get("flow_data"))},
    )

    await _broadcast(
        cid,
        "new_message",
        {
            "telefono_e164": tel,
            "snippet": (body_text or "")[:280],
            "state": conversation_row.get("state"),
            "unread_for_agents": unread,
        },
    )
    await _broadcast(cid, "unread_update", {"unread_for_agents": unread})


async def handle_customer_whatsapp_message(
    *,
    telefono: str,
    body_text: str,
    msg: dict[str, Any],
    bodega_id: str | None,
    contact_name: str | None,
) -> bool:
    """
    Returns True if Meta webhook should skip bot + commerce handlers for this message.
    """
    if _disabled():
        return False

    conv = repo.ensure_open_conversation(
        telefono_e164=telefono,
        bodega_id=bodega_id,
        contact_name=contact_name,
    )
    if not conv:
        logger.warning("support: could not ensure conversation for %s", telefono)
        return False

    state = conv.get("state") or "BOT"
    plain = (body_text or "").strip()

    if state in ("HUMAN", "PAUSED") and detect_release_to_bot(plain, allow_menu_keyword=True):
        await release_customer_to_bot(conv)
        return True

    if state == "WAITING_AGENT" and detect_release_to_bot(plain, allow_menu_keyword=False):
        await release_customer_to_bot(conv)
        return True

    if state in ("HUMAN", "WAITING_AGENT", "PAUSED"):
        await ingest_human_queue_message(conversation_row=conv, body_text=plain, msg=msg)
        return True

    if state == "BOT" and detect_handover(plain):
        await escalate_from_bot(
            conversation_row=conv,
            customer_body=plain,
            wa_message_id=msg.get("message_id"),
            meta_contact_name=contact_name,
        )
        return True

    return False


async def send_agent_reply(
    *,
    conversation_row: dict[str, Any],
    agent_row: dict[str, Any],
    text: str | None,
    image_url: str | None,
    document_url: str | None,
    document_filename: str | None,
    template_name: str | None,
    template_language: str,
    template_components: list | None,
    ip: str | None,
) -> dict[str, Any]:
    from app.services import meta_client

    cid = conversation_row["id"]
    tel = conversation_row["telefono_e164"].lstrip("+")
    wa_mid: str | None = None

    if template_name:
        data = await meta_client.send_template(
            tel, template_name, language=template_language, components=template_components
        )
        if data and data.get("messages"):
            wa_mid = data["messages"][0].get("id")
        repo.insert_support_message(
            conversation_id=cid,
            direction="outbound",
            sender_kind="agent",
            body=f"[template:{template_name}]",
            wa_message_id=wa_mid,
            message_type="template",
            agent_id=agent_row["id"],
            meta={"template_name": template_name, "language": template_language},
        )
    elif document_url:
        fn = document_filename or "documento.pdf"
        data = await meta_client.send_document(tel, document_url, fn, caption=text)
        if data and data.get("messages"):
            wa_mid = data["messages"][0].get("id")
        repo.insert_support_message(
            conversation_id=cid,
            direction="outbound",
            sender_kind="agent",
            body=text,
            wa_message_id=wa_mid,
            message_type="document",
            agent_id=agent_row["id"],
            media={"link": document_url, "filename": fn},
        )
    elif image_url:
        data = await meta_client.send_image(tel, image_url, caption=text)
        if data and data.get("messages"):
            wa_mid = data["messages"][0].get("id")
        repo.insert_support_message(
            conversation_id=cid,
            direction="outbound",
            sender_kind="agent",
            body=text,
            wa_message_id=wa_mid,
            message_type="image",
            agent_id=agent_row["id"],
            media={"link": image_url},
        )
    elif text:
        data = await meta_client.send_text(tel, text)
        if data and data.get("messages"):
            wa_mid = data["messages"][0].get("id")
        repo.insert_support_message(
            conversation_id=cid,
            direction="outbound",
            sender_kind="agent",
            body=text,
            wa_message_id=wa_mid,
            message_type="text",
            agent_id=agent_row["id"],
        )
    else:
        raise ValueError("empty_reply")

    now = repo.utcnow_iso()
    patch: dict[str, Any] = {
        "last_agent_activity_at": now,
        "last_customer_activity_at": conversation_row.get("last_customer_activity_at"),
    }
    if conversation_row.get("first_human_response_at") is None:
        patch["first_human_response_at"] = now
    repo.patch_conversation(cid, patch)

    track_message(
        telefono=conversation_row["telefono_e164"],
        direction="outbound",
        bodega_id=conversation_row.get("bodega_id"),
        message_id=wa_mid or "",
        message_type="support_agent",
        content=(text or "")[:4000],
        metadata={
            "support_conversation_id": cid,
            "sender_kind": "agent",
            "support_agent_id": agent_row["id"],
        },
    )

    await _broadcast(
        cid,
        "new_message",
        {"telefono_e164": conversation_row["telefono_e164"], "direction": "outbound"},
    )

    write_audit_log(
        actor_kind="agent",
        action="agent_reply",
        actor_agent_id=agent_row["id"],
        conversation_id=cid,
        ip=ip,
        payload={"wa_message_id": wa_mid or ""},
    )

    return {"wa_message_id": wa_mid}


async def assign_conversation_to_agent(
    *,
    conversation_row: dict[str, Any],
    target_agent_id: str,
    supervisor_agent: dict[str, Any] | None,
    ip: str | None,
) -> dict[str, Any] | None:
    cid = conversation_row["id"]
    now = repo.utcnow_iso()
    patch = {
        "assigned_agent_id": target_agent_id,
        "state": "HUMAN",
        "last_agent_activity_at": now,
        "sla_due_at": conversation_row.get("sla_due_at") or repo.sla_deadline_iso(_sla_minutes()),
        "escalated_at": conversation_row.get("escalated_at") or now,
    }
    conv = repo.patch_conversation(cid, patch)
    repo.bump_agent_assignment(target_agent_id)

    await _broadcast(
        cid,
        "conversation_assigned",
        {
            "assigned_agent_id": target_agent_id,
            "telefono_e164": conversation_row["telefono_e164"],
            "manual": True,
        },
    )

    write_audit_log(
        actor_kind="agent",
        action="manual_assign",
        actor_agent_id=(supervisor_agent or {}).get("id"),
        conversation_id=cid,
        ip=ip,
        payload={"target_agent_id": target_agent_id},
    )
    return conv
