"""Natural-language hints for human handover / release (Spanish)."""

from __future__ import annotations

import re


_WSPLIT = re.compile(r"[a-záéíóúñü]+", re.IGNORECASE)

# IDs de lista/botones Meta (body = id) y atajos equivalentes al menú "Hablar con Circa".
_MENU_HANDOVER_IDS = frozenset(
    {
        "contacto",
        "soporte",
        "help",
        "contactar",
        "6",  # compat: opción numérica antigua del menú
    }
)

# Frases alineadas con app.state_machine._TEXTO_PIDE_CONTACTO_CIRCA (normalizadas en minúsculas).
_LEGACY_CONTACT_PHRASES = frozenset(
    {
        "no entiendo",
        "no te entiendo",
        "no lo entiendo",
        "no entiendes",
    }
)


def detect_handover(text: str) -> bool:
    """
    Detect request for human support.
    Kept conservative on generic 'ayuda' — requires short message or explicit phrases.
    """
    raw = (text or "").strip().lower()
    if not raw:
        return False

    # Menú Circa (ids de filas) y frases que antes derivaban a wa.me: van al inbox interno.
    if raw in _MENU_HANDOVER_IDS:
        return True
    if "hablar con circa" in raw:
        return True
    if raw in _LEGACY_CONTACT_PHRASES:
        return True

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
