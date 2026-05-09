"""Support inbox domain constants."""

from __future__ import annotations

from typing import Literal

ConversationState = Literal["BOT", "WAITING_AGENT", "HUMAN", "PAUSED", "CLOSED"]

AgentRole = Literal["agent", "supervisor"]

AgentPresence = Literal["offline", "online", "busy"]
