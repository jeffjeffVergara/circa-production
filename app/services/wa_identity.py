"""Teléfono de WhatsApp o identificador de usuario (BSUID).

Cuando la persona usa un nombre de usuario y Circa no le escribió en los
últimos 30 días, el webhook llega sin teléfono. Meta acepta ese identificador
en el campo ``recipient``. El teléfono, si viene, sigue yendo en ``to``.
"""
from __future__ import annotations


def es_telefono(value: str | None) -> bool:
    compact = (value or "").strip().lstrip("+").replace(" ", "")
    return compact.isdigit() and len(compact) >= 8


def telefono_e164(value: str | None) -> str:
    """+ y dígitos. Vacío si el valor no es un teléfono."""
    if not es_telefono(value):
        return ""
    return "+" + (value or "").strip().lstrip("+").replace(" ", "")


def clave_conversacion(phone: str | None, user_id: str | None) -> str:
    """Clave de sesión y de búsqueda de bodega.

    Con teléfono, la misma clave de siempre (+51...). Sin teléfono, el
    identificador de usuario, para que la conversación siga en el mismo hilo.
    """
    tel = telefono_e164(phone)
    if tel:
        return tel
    uid = (user_id or "").strip().lstrip("+")
    if uid and not es_telefono(uid):
        return uid
    return ""


def direccion_envio(dest: str | None) -> dict:
    """Campos de destino para POST /messages.

    Teléfono → ``to`` (solo dígitos). Identificador → ``recipient``.
    Vacío si no hay a quién escribir: no se llama a Meta con ``to`` vacío.
    """
    raw = (dest or "").strip()
    if not raw or raw == "+":
        return {}
    compact = raw.lstrip("+").replace(" ", "")
    if not compact:
        return {}
    if compact.isdigit():
        return {"to": compact}
    return {"recipient": compact}


def telefono_para_log(dest: str | None) -> str:
    """Cómo guardamos el destino en ``messages``. El identificador no lleva +."""
    raw = (dest or "").strip()
    compact = raw.lstrip("+").replace(" ", "")
    if not compact:
        return ""
    if compact.isdigit():
        return "+" + compact
    return compact
