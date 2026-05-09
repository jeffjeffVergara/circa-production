"""Persistence helpers for support inbox (Supabase / PostgREST)."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from app.services import db

logger = logging.getLogger("circa.support.repo")
sb = db.sb


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_queue_id_by_slug(slug: str) -> str | None:
    try:
        r = sb.table("support_queues").select("id").eq("slug", slug).limit(1).execute()
        return r.data[0]["id"] if r.data else None
    except Exception:
        logger.exception("get_queue_id_by_slug")
        return None


def fetch_open_conversation(telefono_e164: str) -> dict[str, Any] | None:
    try:
        r = (
            sb.table("support_conversations")
            .select("*")
            .eq("telefono_e164", telefono_e164)
            .neq("state", "CLOSED")
            .limit(1)
            .execute()
        )
        return r.data[0] if r.data else None
    except Exception:
        logger.exception("fetch_open_conversation")
        return None


def fetch_conversation(conversation_id: str) -> dict[str, Any] | None:
    try:
        r = sb.table("support_conversations").select("*").eq("id", conversation_id).limit(1).execute()
        return r.data[0] if r.data else None
    except Exception:
        logger.exception("fetch_conversation")
        return None


def ensure_open_conversation(
    *,
    telefono_e164: str,
    bodega_id: str | None,
    contact_name: str | None,
    queue_slug: str = "general",
) -> dict[str, Any] | None:
    existing = fetch_open_conversation(telefono_e164)
    now = utcnow_iso()
    if existing:
        patch: dict[str, Any] = {"updated_at": now}
        if contact_name and not existing.get("contact_name"):
            patch["contact_name"] = contact_name
        if bodega_id and not existing.get("bodega_id"):
            patch["bodega_id"] = bodega_id
        try:
            sb.table("support_conversations").update(patch).eq("id", existing["id"]).execute()
            return fetch_conversation(existing["id"])
        except Exception:
            logger.exception("ensure_open_conversation update")
            return existing

    qid = get_queue_id_by_slug(queue_slug)
    payload: dict[str, Any] = {
        "telefono_e164": telefono_e164,
        "state": "BOT",
        "updated_at": now,
        "created_at": now,
        "tags": [],
    }
    if bodega_id:
        payload["bodega_id"] = bodega_id
    if contact_name:
        payload["contact_name"] = contact_name
    if qid:
        payload["queue_id"] = qid

    try:
        ins = sb.table("support_conversations").insert(payload).execute()
        if ins.data:
            return ins.data[0]
    except Exception as e:
        logger.warning("ensure_open_conversation insert conflict/retry: %s", e)
        existing = fetch_open_conversation(telefono_e164)
        if existing:
            return existing
    return fetch_open_conversation(telefono_e164)


def patch_conversation(conversation_id: str, fields: dict[str, Any]) -> dict[str, Any] | None:
    fields = {**fields, "updated_at": utcnow_iso()}
    try:
        r = sb.table("support_conversations").update(fields).eq("id", conversation_id).execute()
        return r.data[0] if r.data else fetch_conversation(conversation_id)
    except Exception:
        logger.exception("patch_conversation")
        return fetch_conversation(conversation_id)


def insert_support_message(
    *,
    conversation_id: str,
    direction: str,
    sender_kind: str,
    body: str | None,
    message_type: str = "text",
    wa_message_id: str | None = None,
    wa_status: str | None = None,
    agent_id: str | None = None,
    media: dict[str, Any] | None = None,
    meta: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    payload = {
        "conversation_id": conversation_id,
        "direction": direction,
        "sender_kind": sender_kind,
        "message_type": message_type,
        "body": body,
        "wa_message_id": wa_message_id,
        "wa_status": wa_status,
        "agent_id": agent_id,
        "media": media or {},
        "metadata": meta or {},
    }
    try:
        r = sb.table("support_messages").insert(payload).execute()
        return r.data[0] if r.data else None
    except Exception as e:
        logger.debug("insert_support_message skip dup?: %s", e)
        return None


def update_message_delivery(*, wa_message_id: str, wa_status: str) -> None:
    if not wa_message_id:
        return
    try:
        sb.table("support_messages").update({"wa_status": wa_status}).eq(
            "wa_message_id", wa_message_id
        ).execute()
    except Exception:
        logger.exception("update_message_delivery")


def pick_round_robin_agent() -> dict[str, Any] | None:
    try:
        r = (
            sb.table("support_agents")
            .select("*")
            .eq("status", "online")
            .eq("accept_assignments", True)
            .execute()
        )
        agents = r.data or []
        if not agents:
            return None
        agents.sort(
            key=lambda a: (
                0 if a.get("last_assignment_at") is None else 1,
                a.get("last_assignment_at") or "",
            )
        )
        return agents[0]
    except Exception:
        logger.exception("pick_round_robin_agent")
        return None


def bump_agent_assignment(agent_id: str) -> None:
    try:
        row = sb.table("support_agents").select("assignments_total").eq("id", agent_id).limit(1).execute()
        n = int(row.data[0].get("assignments_total") or 0) + 1 if row.data else 1
        now = utcnow_iso()
        sb.table("support_agents").update(
            {"assignments_total": n, "last_assignment_at": now, "updated_at": now}
        ).eq("id", agent_id).execute()
    except Exception:
        logger.exception("bump_agent_assignment")


def list_conversations(
    *,
    state: str | None,
    limit: int,
    offset: int,
    assigned_to: str | None,
    include_unassigned_waiting_for_agent: str | None = None,
) -> list[dict[str, Any]]:
    """
    ``include_unassigned_waiting_for_agent`` merges:
    rows assigned to that agent plus unassigned ``WAITING_AGENT`` (shared inbox queue).
    """
    try:
        if include_unassigned_waiting_for_agent:
            aid = include_unassigned_waiting_for_agent
            qa = sb.table("support_conversations").select("*").eq("assigned_agent_id", aid)
            qb = (
                sb.table("support_conversations")
                .select("*")
                .eq("state", "WAITING_AGENT")
                .is_("assigned_agent_id", "null")
            )
            if state:
                qa = qa.eq("state", state)
                qb = qb.eq("state", state)
            ra = qa.order("updated_at", desc=True).execute().data or []
            rb = qb.order("updated_at", desc=True).execute().data or []
            merged: dict[str, dict[str, Any]] = {}
            for row in ra + rb:
                merged[row["id"]] = row
            rows = sorted(merged.values(), key=lambda r: r.get("updated_at") or "", reverse=True)
            return rows[offset : offset + limit]

        q = sb.table("support_conversations").select("*").order("updated_at", desc=True)
        if state:
            q = q.eq("state", state)
        if assigned_to:
            q = q.eq("assigned_agent_id", assigned_to)
        r = q.range(offset, offset + limit - 1).execute()
        return r.data or []
    except Exception:
        logger.exception("list_conversations")
        return []


def list_messages(conversation_id: str, limit: int = 200, offset: int = 0) -> list[dict[str, Any]]:
    try:
        lim = min(max(1, limit), 500)
        off = max(0, offset)
        r = (
            sb.table("support_messages")
            .select("*")
            .eq("conversation_id", conversation_id)
            .order("created_at", desc=False)
            .range(off, off + lim - 1)
            .execute()
        )
        return r.data or []
    except Exception:
        logger.exception("list_messages")
        return []


def list_agents() -> list[dict[str, Any]]:
    try:
        r = (
            sb.table("support_agents")
            .select("id,email,display_name,role,status,accept_assignments,last_seen_at,created_at")
            .order("display_name")
            .execute()
        )
        return r.data or []
    except Exception:
        logger.exception("list_agents")
        return []


def sla_deadline_iso(minutes: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(minutes=minutes)).isoformat()


def metrics_snapshot() -> dict[str, Any]:
    """Lightweight aggregates for dashboard cards (MVP; refine with SQL views later)."""
    try:
        today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        iso_start = today_start.isoformat()
        closed = (
            sb.table("support_conversations")
            .select(
                "id,assigned_agent_id,closed_at,first_human_response_at,"
                "escalated_at,created_at,state"
            )
            .gte("closed_at", iso_start)
            .execute()
        )
        rows = closed.data or []
        ft_buckets: list[float] = []
        abandoned = 0
        per_agent: dict[str, int] = {}
        for row in rows:
            aid = row.get("assigned_agent_id")
            if aid:
                per_agent[aid] = per_agent.get(aid, 0) + 1
            fhr = row.get("first_human_response_at")
            esc = row.get("escalated_at") or row.get("created_at")
            if esc and fhr:
                try:
                    t0 = datetime.fromisoformat(esc.replace("Z", "+00:00"))
                    t1 = datetime.fromisoformat(fhr.replace("Z", "+00:00"))
                    ft_buckets.append((t1 - t0).total_seconds())
                except Exception:
                    pass
            if row.get("first_human_response_at") is None:
                abandoned += 1

        active_human = (
            sb.table("support_conversations")
            .select("id")
            .in_("state", ["WAITING_AGENT", "HUMAN", "PAUSED"])
            .execute()
        )
        waiting = (
            sb.table("support_conversations").select("id").eq("state", "WAITING_AGENT").execute()
        )

        return {
            "closed_today_count": len(rows),
            "avg_first_response_sec": round(sum(ft_buckets) / len(ft_buckets), 2)
            if ft_buckets
            else None,
            "conversations_per_agent": per_agent,
            "abandoned_without_human_reply_estimate": abandoned,
            "active_panel_count": len(active_human.data or []),
            "waiting_agent_count": len(waiting.data or []),
        }
    except Exception:
        logger.exception("metrics_snapshot")
        return {}
