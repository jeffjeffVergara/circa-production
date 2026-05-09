"""Auth, audit, and lightweight rate limiting for the support console API."""

from __future__ import annotations

import bcrypt
import hashlib
import logging
import secrets
from time import monotonic
from typing import Any

from fastapi import Depends, Header, HTTPException, Request

logger = logging.getLogger("circa.support.security")

_RATE_BUCKETS: dict[str, list[float]] = {}
_RL_LIMIT = int(__import__("os").getenv("SUPPORT_API_RATE_LIMIT", "120"))
_RL_WINDOW_SEC = float(__import__("os").getenv("SUPPORT_API_RATE_WINDOW_SEC", "60"))


def token_sha256_hex(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def mint_agent_credentials() -> tuple[str, str, str]:
    """Returns (plaintext_token, sha256_hex, bcrypt_hash)."""
    raw = secrets.token_urlsafe(32)
    sha = token_sha256_hex(raw)
    hashed = bcrypt.hashpw(raw.encode("utf-8"), bcrypt.gensalt()).decode("ascii")
    return raw, sha, hashed


def verify_agent_api_token(raw_token: str, stored_sha256: str, stored_hash: str) -> bool:
    if token_sha256_hex(raw_token) != stored_sha256:
        return False
    try:
        return bcrypt.checkpw(raw_token.encode("utf-8"), stored_hash.encode("ascii"))
    except Exception:
        return False


def enforce_rate_limit(ip: str) -> None:
    now = monotonic()
    bucket = _RATE_BUCKETS.setdefault(ip, [])
    bucket[:] = [t for t in bucket if now - t < _RL_WINDOW_SEC]
    if len(bucket) >= _RL_LIMIT:
        raise HTTPException(status_code=429, detail="Rate limit exceeded")
    bucket.append(now)


async def support_rate_limit_dependency(request: Request) -> None:
    ip = request.client.host if request.client else "unknown"
    enforce_rate_limit(ip)


def write_audit_log(
    *,
    actor_kind: str,
    action: str,
    payload: dict[str, Any] | None = None,
    actor_agent_id: str | None = None,
    conversation_id: str | None = None,
    ip: str | None = None,
) -> None:
    try:
        from app.services import db

        db.sb.table("support_audit_logs").insert(
            {
                "actor_kind": actor_kind,
                "actor_agent_id": actor_agent_id,
                "conversation_id": conversation_id,
                "action": action,
                "ip": ip,
                "payload": payload or {},
            }
        ).execute()
    except Exception:
        logger.exception("support audit insert failed")


def resolve_support_agent_from_token(raw_token: str) -> dict[str, Any]:
    from app.services import db

    sha = token_sha256_hex(raw_token)
    r = (
        db.sb.table("support_agents")
        .select("*")
        .eq("api_token_sha256", sha)
        .limit(1)
        .execute()
    )
    if not r.data:
        raise HTTPException(status_code=401, detail="Invalid token")
    agent = r.data[0]
    if not verify_agent_api_token(raw_token, agent["api_token_sha256"], agent["api_token_hash"]):
        raise HTTPException(status_code=401, detail="Invalid token")
    return agent


async def verify_support_agent(
    request: Request,
    authorization: str | None = Header(None),
    x_support_token: str | None = Header(None, alias="X-Support-Token"),
    _: None = Depends(support_rate_limit_dependency),
) -> dict[str, Any]:
    raw: str | None = None
    if authorization and authorization.lower().startswith("bearer "):
        raw = authorization[7:].strip()
    elif x_support_token:
        raw = x_support_token.strip()
    if not raw:
        raise HTTPException(status_code=401, detail="Missing support credentials")

    agent = resolve_support_agent_from_token(raw)

    try:
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc).isoformat()
        db.sb.table("support_agents").update({"last_seen_at": now, "updated_at": now}).eq(
            "id", agent["id"]
        ).execute()
    except Exception:
        pass

    return agent


def require_supervisor(agent: dict[str, Any]) -> None:
    if agent.get("role") != "supervisor":
        raise HTTPException(status_code=403, detail="Supervisor role required")
