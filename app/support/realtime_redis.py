"""
Redis Pub/Sub opcional para fan-out de eventos de soporte entre réplicas (multi-pod).

Variables:
  REDIS_URL           — si está definida, ``hub.emit`` publica aquí y cada proceso
                        escucha el mismo canal y reenvía solo a sus WebSockets locales.
  SUPPORT_REDIS_CHANNEL — default ``circa:support:events``

Sin REDIS_URL el comportamiento sigue siendo fan-out en memoria en un solo proceso.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any, Awaitable, Callable

logger = logging.getLogger("circa.support.redis")

REDIS_URL = os.getenv("REDIS_URL", "").strip()
CHANNEL = os.getenv("SUPPORT_REDIS_CHANNEL", "circa:support:events").strip() or "circa:support:events"

_pub_client: Any = None


def redis_pubsub_enabled() -> bool:
    return bool(REDIS_URL)


async def publish_support_event(envelope: dict[str, Any]) -> None:
    """Publica JSON ``{"event","payload"}``. No-op si no hay cliente Redis."""
    global _pub_client
    if not REDIS_URL:
        return
    try:
        import redis.asyncio as aioredis
    except ImportError:
        logger.warning("redis package not installed; pip install redis")
        return
    if _pub_client is None:
        _pub_client = aioredis.from_url(REDIS_URL, decode_responses=True)
    await _pub_client.publish(CHANNEL, json.dumps(envelope, separators=(",", ":")))


async def shutdown_publish_client() -> None:
    global _pub_client
    if _pub_client is not None:
        try:
            await _pub_client.aclose()
        except Exception:
            logger.exception("redis publish client close")
        _pub_client = None


async def _subscriber_loop(deliver_local: Callable[[dict[str, Any]], Awaitable[None]]) -> None:
    import redis.asyncio as aioredis

    r = aioredis.from_url(REDIS_URL, decode_responses=True)
    pubsub = r.pubsub()
    await pubsub.subscribe(CHANNEL)
    logger.info("Support realtime: subscribed to Redis channel %s", CHANNEL)
    try:
        while True:
            raw = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
            if raw is None:
                continue
            if raw.get("type") != "message":
                continue
            try:
                env = json.loads(raw["data"])
                await deliver_local(env)
            except Exception:
                logger.exception("support redis deliver_local")
    except asyncio.CancelledError:
        logger.info("Support realtime: Redis subscriber cancelled")
        raise
    finally:
        try:
            await pubsub.unsubscribe(CHANNEL)
            closer = getattr(pubsub, "aclose", None)
            if closer:
                await closer()
            else:
                await pubsub.close()
            await r.aclose()
        except Exception:
            logger.exception("redis subscriber cleanup")


def spawn_subscriber_if_needed(
    deliver_local: Callable[[dict[str, Any]], Awaitable[None]],
) -> asyncio.Task | None:
    """
    Arranca la tarea de escucha si ``REDIS_URL`` está definido.
    ``deliver_local`` debe ser p.ej. ``hub.deliver_local``.
    """
    if not REDIS_URL:
        logger.debug("Support realtime: REDIS_URL unset, using in-process hub only")
        return None
    try:
        import redis.asyncio as aioredis  # noqa: F401
    except ImportError:
        logger.warning("REDIS_URL set but redis not installed; WS scaling disabled")
        return None
    return asyncio.create_task(_subscriber_loop(deliver_local))


async def stop_subscriber(task: asyncio.Task | None) -> None:
    if task is None:
        return
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    except Exception:
        logger.exception("subscriber task join")


async def shutdown_redis_async(task: asyncio.Task | None) -> None:
    await stop_subscriber(task)
    await shutdown_publish_client()
