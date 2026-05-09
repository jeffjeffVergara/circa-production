"""REST + WebSocket API for the internal support console."""

from __future__ import annotations

import logging
import os
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from app.support import repository as repo
from app.support.security import (
    mint_agent_credentials,
    require_supervisor,
    resolve_support_agent_from_token,
    verify_support_agent,
    write_audit_log,
)
from app.support.service import assign_conversation_to_agent, close_conversation_public, send_agent_reply
from app.support.ws_hub import hub

logger = logging.getLogger("circa.support.api")

router = APIRouter(prefix="/api/support", tags=["support_inbox"])


class BootstrapAgentBody(BaseModel):
    display_name: str = Field(..., min_length=1, max_length=120)
    email: str | None = Field(None, max_length=200)
    role: str = Field(default="agent", pattern="^(agent|supervisor)$")
    accept_assignments: bool = True


class AgentStatusBody(BaseModel):
    status: str = Field(..., pattern="^(offline|online|busy)$")


class AssignBody(BaseModel):
    agent_id: str = Field(..., min_length=8)


class CloseBody(BaseModel):
    reason: str = Field(default="closed_by_agent", max_length=200)
    notify_customer: bool = True


class ReplyBody(BaseModel):
    text: str | None = Field(None, max_length=4000)
    image_url: str | None = None
    document_url: str | None = None
    document_filename: str | None = Field(None, max_length=200)
    template_name: str | None = Field(None, max_length=120)
    template_language: str = Field(default="es", max_length=16)
    template_components: list | None = None


class TypingBody(BaseModel):
    typing: bool = True


async def verify_bootstrap_secret(
    x_support_bootstrap_secret: str = Header(..., alias="X-Support-Bootstrap-Secret"),
) -> None:
    """Misma palabra que ``Bearer`` / consola: ``SUPPORT_BOOTSTRAP_SECRET`` (comparación estricta)."""
    from app.support.security import bootstrap_header_matches_secret

    if not bootstrap_header_matches_secret(x_support_bootstrap_secret):
        raise HTTPException(status_code=403, detail="Invalid bootstrap secret")


def _ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def _can_access_conversation(agent: dict[str, Any], conv: dict[str, Any]) -> bool:
    if agent.get("role") == "supervisor":
        return True
    aid = conv.get("assigned_agent_id")
    return aid is None or aid == agent.get("id")


@router.post("/bootstrap/agent")
async def bootstrap_agent(
    body: BootstrapAgentBody,
    _: None = Depends(verify_bootstrap_secret),
):
    """Alta de agentes adicionales (legacy). Header = misma palabra secreta que el acceso Bearer a la consola."""
    from app.services import db

    raw, sha, hashed = mint_agent_credentials()
    payload = {
        "display_name": body.display_name,
        "role": body.role,
        "accept_assignments": body.accept_assignments,
        "status": "offline",
        "api_token_sha256": sha,
        "api_token_hash": hashed,
    }
    if body.email:
        payload["email"] = body.email.strip().lower()
    ins = db.sb.table("support_agents").insert(payload).execute()
    row = ins.data[0] if ins.data else None
    if not row:
        raise HTTPException(status_code=500, detail="Insert failed")
    write_audit_log(
        actor_kind="system",
        action="bootstrap_agent_created",
        payload={"agent_id": row["id"], "role": body.role},
    )
    return {
        "agent_id": row["id"],
        "api_token": raw,
        "message": "Store api_token securely; it cannot be retrieved again.",
    }


@router.get("/agents/me")
async def support_agent_me(agent: dict = Depends(verify_support_agent)):
    """Perfil del agente autenticado (sin secretos)."""
    return {
        "id": agent["id"],
        "display_name": agent.get("display_name"),
        "email": agent.get("email"),
        "role": agent.get("role"),
        "status": agent.get("status"),
        "accept_assignments": agent.get("accept_assignments", True),
    }


@router.get("/agents")
async def list_support_agents(agent: dict = Depends(verify_support_agent)):
    require_supervisor(agent)
    return repo.list_agents()


@router.patch("/agents/me/status")
async def patch_my_status(
    body: AgentStatusBody,
    request: Request,
    agent: dict = Depends(verify_support_agent),
):
    from app.services import db

    now = repo.utcnow_iso()
    db.sb.table("support_agents").update({"status": body.status, "updated_at": now, "last_seen_at": now}).eq(
        "id", agent["id"]
    ).execute()
    write_audit_log(
        actor_kind="agent",
        action="agent_status",
        actor_agent_id=agent["id"],
        ip=_ip(request),
        payload={"status": body.status},
    )
    await hub.emit(
        "agent_online",
        {"agent_id": agent["id"], "status": body.status},
    )
    return {"ok": True, "status": body.status}


@router.get("/metrics/summary")
async def metrics_summary(agent: dict = Depends(verify_support_agent)):
    _ = agent
    snap = repo.metrics_snapshot()
    return {"metrics": snap}


@router.get("/conversations")
async def list_conv(
    request: Request,
    agent: dict = Depends(verify_support_agent),
    state: str | None = Query(None),
    scope: str = Query("mine", pattern="^(mine|all)$"),
    limit: int = Query(40, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    assigned_filter: str | None = None
    queue_agent: str | None = None
    if scope == "all":
        if agent.get("role") != "supervisor":
            raise HTTPException(status_code=403, detail="Supervisor role required for scope=all")
    else:
        assigned_filter = None
        queue_agent = agent["id"]

    rows = repo.list_conversations(
        state=state,
        limit=limit,
        offset=offset,
        assigned_to=assigned_filter,
        include_unassigned_waiting_for_agent=queue_agent,
    )
    write_audit_log(
        actor_kind="agent",
        action="list_conversations",
        actor_agent_id=agent["id"],
        ip=_ip(request),
        payload={"state": state or "", "scope": scope, "limit": limit},
    )
    return {"conversations": rows}


@router.get("/conversations/{conversation_id}")
async def get_conv(conversation_id: str, request: Request, agent: dict = Depends(verify_support_agent)):
    conv = repo.fetch_conversation(conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Not found")
    if not _can_access_conversation(agent, conv):
        raise HTTPException(status_code=403, detail="Forbidden")
    write_audit_log(
        actor_kind="agent",
        action="get_conversation",
        actor_agent_id=agent["id"],
        conversation_id=conversation_id,
        ip=_ip(request),
        payload={},
    )
    return {"conversation": conv}


@router.get("/conversations/{conversation_id}/messages")
async def get_messages(conversation_id: str, agent: dict = Depends(verify_support_agent)):
    conv = repo.fetch_conversation(conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Not found")
    if not _can_access_conversation(agent, conv):
        raise HTTPException(status_code=403, detail="Forbidden")
    return {"messages": repo.list_messages(conversation_id)}


@router.post("/conversations/{conversation_id}/read")
async def mark_read(conversation_id: str, request: Request, agent: dict = Depends(verify_support_agent)):
    conv = repo.fetch_conversation(conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Not found")
    if not _can_access_conversation(agent, conv):
        raise HTTPException(status_code=403, detail="Forbidden")
    repo.patch_conversation(conversation_id, {"unread_for_agents": 0})
    await hub.emit(
        "unread_update",
        {"conversation_id": conversation_id, "unread_for_agents": 0},
    )
    write_audit_log(
        actor_kind="agent",
        action="conversation_mark_read",
        actor_agent_id=agent["id"],
        conversation_id=conversation_id,
        ip=_ip(request),
        payload={},
    )
    return {"ok": True}


@router.post("/conversations/{conversation_id}/typing")
async def post_typing(
    conversation_id: str,
    body: TypingBody,
    request: Request,
    agent: dict = Depends(verify_support_agent),
):
    conv = repo.fetch_conversation(conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Not found")
    if not _can_access_conversation(agent, conv):
        raise HTTPException(status_code=403, detail="Forbidden")
    await hub.emit(
        "typing",
        {
            "conversation_id": conversation_id,
            "agent_id": agent["id"],
            "typing": body.typing,
        },
    )
    write_audit_log(
        actor_kind="agent",
        action="typing_indicator",
        actor_agent_id=agent["id"],
        conversation_id=conversation_id,
        ip=_ip(request),
        payload={"typing": body.typing},
    )
    return {"ok": True}


@router.post("/conversations/{conversation_id}/claim")
async def claim_conversation(conversation_id: str, request: Request, agent: dict = Depends(verify_support_agent)):
    conv = repo.fetch_conversation(conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Not found")
    if conv.get("state") != "WAITING_AGENT":
        raise HTTPException(status_code=409, detail="Conversation is not waiting")
    if agent.get("role") != "supervisor" and not agent.get("accept_assignments", True):
        raise HTTPException(status_code=403, detail="Cannot claim assignments")
    await assign_conversation_to_agent(
        conversation_row=conv,
        target_agent_id=agent["id"],
        supervisor_agent=None,
        ip=_ip(request),
    )
    write_audit_log(
        actor_kind="agent",
        action="conversation_claimed",
        actor_agent_id=agent["id"],
        conversation_id=conversation_id,
        ip=_ip(request),
        payload={},
    )
    return {"ok": True, "conversation_id": conversation_id, "assigned_agent_id": agent["id"]}


@router.post("/conversations/{conversation_id}/assign")
async def assign_conversation(
    conversation_id: str,
    body: AssignBody,
    request: Request,
    agent: dict = Depends(verify_support_agent),
):
    conv = repo.fetch_conversation(conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Not found")
    if agent.get("role") != "supervisor":
        if agent["id"] != body.agent_id:
            raise HTTPException(status_code=403, detail="Only supervisors can assign other agents")
        if conv.get("state") != "WAITING_AGENT":
            raise HTTPException(
                status_code=403,
                detail="Agents may only self-assign conversations that are waiting",
            )
    from app.services import db

    ok = db.sb.table("support_agents").select("id").eq("id", body.agent_id).limit(1).execute()
    if not ok.data:
        raise HTTPException(status_code=404, detail="Agent not found")

    await assign_conversation_to_agent(
        conversation_row=conv,
        target_agent_id=body.agent_id,
        supervisor_agent=agent if agent.get("role") == "supervisor" else None,
        ip=_ip(request),
    )
    return {"ok": True}


@router.post("/conversations/{conversation_id}/pause")
async def pause_conversation(conversation_id: str, request: Request, agent: dict = Depends(verify_support_agent)):
    conv = repo.fetch_conversation(conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Not found")
    if agent.get("role") != "supervisor":
        raise HTTPException(status_code=403, detail="Supervisor only")
    repo.patch_conversation(conversation_id, {"state": "PAUSED"})
    await hub.emit("conversation_updated", {"conversation_id": conversation_id, "state": "PAUSED"})
    write_audit_log(
        actor_kind="agent",
        action="conversation_paused",
        actor_agent_id=agent["id"],
        conversation_id=conversation_id,
        ip=_ip(request),
        payload={},
    )
    return {"ok": True}


@router.post("/conversations/{conversation_id}/resume")
async def resume_conversation(conversation_id: str, request: Request, agent: dict = Depends(verify_support_agent)):
    conv = repo.fetch_conversation(conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Not found")
    if agent.get("role") != "supervisor":
        raise HTTPException(status_code=403, detail="Supervisor only")
    nxt = "HUMAN" if conv.get("assigned_agent_id") else "WAITING_AGENT"
    repo.patch_conversation(conversation_id, {"state": nxt})
    await hub.emit("conversation_updated", {"conversation_id": conversation_id, "state": nxt})
    write_audit_log(
        actor_kind="agent",
        action="conversation_resumed",
        actor_agent_id=agent["id"],
        conversation_id=conversation_id,
        ip=_ip(request),
        payload={"state": nxt},
    )
    return {"ok": True, "state": nxt}


@router.post("/conversations/{conversation_id}/close")
async def close_conv(
    conversation_id: str,
    body: CloseBody,
    request: Request,
    agent: dict = Depends(verify_support_agent),
):
    conv = repo.fetch_conversation(conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Not found")
    if agent.get("role") != "supervisor":
        aid = conv.get("assigned_agent_id")
        if aid is None:
            raise HTTPException(
                status_code=403,
                detail="Claim or assign this conversation before closing",
            )
        if aid != agent.get("id"):
            raise HTTPException(status_code=403, detail="Forbidden")
    await close_conversation_public(
        conversation_row=conv,
        reason=body.reason,
        actor_agent_id=agent["id"],
        send_customer_notice=body.notify_customer,
    )
    return {"ok": True}


@router.post("/conversations/{conversation_id}/reply")
async def reply_conv(
    conversation_id: str,
    body: ReplyBody,
    request: Request,
    agent: dict = Depends(verify_support_agent),
):
    conv = repo.fetch_conversation(conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Not found")
    if conv.get("state") not in ("HUMAN", "WAITING_AGENT", "PAUSED"):
        raise HTTPException(status_code=409, detail="Conversation not in an agent-handled state")
    if not _can_access_conversation(agent, conv):
        raise HTTPException(status_code=403, detail="Forbidden")

    try:
        result = await send_agent_reply(
            conversation_row=conv,
            agent_row=agent,
            text=body.text,
            image_url=body.image_url,
            document_url=body.document_url,
            document_filename=body.document_filename,
            template_name=body.template_name,
            template_language=body.template_language,
            template_components=body.template_components,
            ip=_ip(request),
        )
    except ValueError:
        raise HTTPException(status_code=400, detail="Provide text, image_url, document_url, or template_name")

    if conv.get("state") == "WAITING_AGENT":
        repo.patch_conversation(conversation_id, {"state": "HUMAN", "assigned_agent_id": agent["id"]})

    return {"ok": True, **result}


@router.websocket("/ws")
async def support_ws(websocket: WebSocket, token: str | None = Query(None)):
    if not token:
        await websocket.close(code=4401)
        return
    try:
        resolve_support_agent_from_token(token)
    except HTTPException:
        await websocket.close(code=4401)
        return

    await websocket.accept()
    await hub.register(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        await hub.unregister(websocket)
