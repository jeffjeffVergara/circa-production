"""URLs del catálogo web v2 (query params de sesión de carrito)."""

from __future__ import annotations

import os
from urllib.parse import urlencode


def _base_url() -> str:
    return os.getenv("APP_BASE_URL", "https://circa-production-c517.up.railway.app").rstrip("/")


def build_catalog_v2_url(
    bodega_id: str,
    *,
    tipo: str = "venta",
    fresh: bool = False,
    repeat: bool = False,
    edit: bool = False,
) -> str:
    """
    fresh=1  → pedido nuevo (carrito vacío; no rehidratar borrador anterior)
    repeat=1 → REPETIR último pedido confirmado
    edit=1   → continuar borrador (EDITAR carrito desde WhatsApp)
    """
    params: dict[str, str] = {
        "b": bodega_id,
        "t": "preventa" if tipo == "preventa" else "venta",
    }
    if fresh:
        params["fresh"] = "1"
    if repeat:
        params["repeat"] = "1"
    if edit:
        params["edit"] = "1"
    return f"{_base_url()}/catalogo-v2?{urlencode(params)}"
