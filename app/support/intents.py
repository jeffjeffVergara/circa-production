"""Natural-language hints for human handover / release (Spanish)."""

from __future__ import annotations

import re


_WSPLIT = re.compile(r"[a-záéíóúñü]+", re.IGNORECASE)


def detect_handover(text: str) -> bool:
    """
    Detect request for human support.
    Kept conservative on generic 'ayuda' — requires short message or explicit phrases.
    """
    raw = (text or "").strip().lower()
    if not raw:
        return False

    tokens = {t.lower() for t in _WSPLIT.findall(raw)}

    if {"asesor", "humano", "soporte"} & tokens:
        return True

    needles = (
        "hablar con un asesor",
        "hablar con alguien",
        "soporte humano",
        "atención humana",
        "atencion humana",
        "persona real",
        "quiero un operador",
    )
    if any(n in raw for n in needles):
        return True

    if "ayuda" in tokens:
        if len(raw) <= 56:
            return True
        if "humana" in tokens or "humano" in tokens:
            return True

    return False


def detect_release_to_bot(text: str, *, allow_menu_keyword: bool = True) -> bool:
    """Customer ends human session and returns to automation."""
    raw = (text or "").strip().lower()
    if not raw:
        return False

    compact = re.sub(r"\s+", " ", raw)
    phrases = (
        "fin soporte",
        "cerrar soporte",
        "cerrar chat",
        "volver al bot",
        "terminar soporte",
        "#finchat",
        "menu circa",
    )
    if any(p in compact for p in phrases):
        return True

    if not allow_menu_keyword:
        return False

    tokens = {t.lower() for t in _WSPLIT.findall(raw)}
    return compact == "menu" or tokens == {"menu", "circa"}
