"""
Estados de pedido — fuente única para portal distribuidor y API tracking.

Flujo operativo (venta confirmada):
  confirmado → recibido → en_preparacion → despachado → en_camino → entregado
"""
from __future__ import annotations

# Portal distribuidor (canónico)
STATUS_FLOW: dict[str, str] = {
    "preventa_aceptada": "recibido",
    "confirmado": "recibido",
    "recibido": "en_preparacion",
    "en_preparacion": "despachado",
    "despachado": "en_camino",
    "en_camino": "entregado",
}

STATUS_LABELS: dict[str, str] = {
    "confirmado": "Nuevo",
    "recibido": "Recibido",
    "en_preparacion": "En Preparacion",
    "despachado": "Despachado",
    "en_camino": "En Camino",
    "entregado": "Entregado",
    "pagado": "Pagado",
}

# Alias legacy (API tracking / mensajes viejos)
LEGACY_ESTADO_ALIASES: dict[str, str] = {
    "preparando": "en_preparacion",
    "aprobado": "confirmado",
}

VALID_TRANSITIONS: dict[str, list[str]] = {
    "confirmado": ["recibido", "cancelado"],
    "recibido": ["en_preparacion", "cancelado"],
    "en_preparacion": ["despachado", "cancelado"],
    "despachado": ["en_camino", "cancelado"],
    "en_camino": ["entregado", "cancelado"],
    "entregado": ["completed"],
    "completed": [],
    "cancelado": [],
}

STATUS_MESSAGES: dict[str, str] = {
    "confirmado": "Tu pedido ha sido recibido y confirmado.",
    "recibido": "El distribuidor confirmó que recibió tu pedido.",
    "en_preparacion": "En preparación en el almacén del distribuidor.",
    "despachado": "Despachado — salió del almacén.",
    "en_camino": "En camino a tu bodega.",
    "entregado": "Entregado en tu bodega.",
    "cancelado": "Tu pedido ha sido cancelado.",
}


def normalize_estado(estado: str) -> str:
    """Normaliza alias legacy al vocabulario del portal."""
    e = (estado or "").strip()
    return LEGACY_ESTADO_ALIASES.get(e, e)


def next_estado(current: str) -> str | None:
    return STATUS_FLOW.get(normalize_estado(current))


def can_transition(from_estado: str, to_estado: str) -> bool:
    cur = normalize_estado(from_estado)
    nxt = normalize_estado(to_estado)
    allowed = VALID_TRANSITIONS.get(cur, [])
    return nxt in allowed
