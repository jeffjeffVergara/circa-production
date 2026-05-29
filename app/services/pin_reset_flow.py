"""Flujo de recuperación de clave Circa — «Me olvidé mi clave»."""
from __future__ import annotations

import json
import unicodedata
from typing import Any

from app.services import db
from app.services.identity import consultar_dni_sync, validate_dni_format

OLVIDE_TRIGGERS = frozenset({
    "OLVIDE",
    "OLVIDE MI CLAVE",
    "ME OLVIDE MI CLAVE",
    "OLVIDE MI CLAVE CIRCA",
    "OLVIDE_CLAVE",
    "RESET",
    "CAMBIAR CLAVE",
    "RECUPERAR CLAVE",
    "NO RECUERDO MI CLAVE",
    "PERDI MI CLAVE",
    "PERDI MI CLAVE CIRCA",
})


def is_olvide_trigger(body_n: str) -> bool:
    if not body_n:
        return False
    if body_n in OLVIDE_TRIGGERS:
        return True
    return "OLVID" in body_n and "CLAVE" in body_n


def es_solo_dni(bodega: dict) -> bool:
    return bool(bodega.get("solo_dni_sin_ruc"))


def _norm_name(s: str) -> str:
    s = unicodedata.normalize("NFKD", (s or "").upper())
    return "".join(c for c in s if not unicodedata.combining(c)).strip()


def _names_match(reniec_name: str, rep_legal: str) -> bool:
    norm_reniec = _norm_name(reniec_name)
    norm_rep = _norm_name(rep_legal)
    reniec_parts = set(norm_reniec.replace(",", "").split())
    rep_parts = set(norm_rep.replace(",", "").split())
    return len(reniec_parts & rep_parts) >= 2


def msg_reset_intro(bodega: dict) -> str:
    if es_solo_dni(bodega):
        return (
            "🔐 *Me olvidé mi clave*\n\n"
            "Para crear una clave nueva, confirma tu identidad con tu *DNI* (8 dígitos).\n\n"
            "✏️ Escríbelo aquí (solo números).\n\n"
            "_Escribe *MENU* para cancelar._"
        )
    rep = (bodega.get("representante_legal") or "representante legal").strip()
    ruc = (bodega.get("ruc") or "").strip()
    ruc_line = f"RUC *{ruc}*\n" if ruc else ""
    return (
        "🔐 *Me olvidé mi clave*\n\n"
        f"Tu negocio está registrado con RUC.\n{ruc_line}"
        f"Escribe el *DNI* (8 dígitos) del representante legal:\n"
        f"*{rep}*\n\n"
        "✏️ Envía solo los 8 números del DNI.\n\n"
        "_Escribe *MENU* para cancelar. Si tenías un pedido pendiente, lo guardamos._"
    )


def msg_reset_dni_invalid() -> str:
    return "❌ El DNI debe tener *8 dígitos*. Escríbelo de nuevo:"


def msg_reset_dni_no_match(rep_legal: str) -> str:
    return (
        "❌ *Ese DNI no coincide* con el representante legal registrado.\n\n"
        f"En SUNAT figura: *{rep_legal}*\n\n"
        "Escribe el DNI correcto del representante legal:"
    )


def msg_reset_dni_ok(nombre: str) -> str:
    return f"✅ *{nombre}*, identidad confirmada.\n\nAhora crea tu *nueva clave* de 4 dígitos:"


def msg_reset_reniec_fail() -> str:
    return (
        "⚠️ No pudimos verificar el DNI en este momento.\n\n"
        "Revisa que sean 8 dígitos y vuelve a intentarlo:"
    )


def msg_pin_pago_ayuda() -> str:
    return (
        "🔐 Estamos esperando tu *clave Circa* (4 dígitos) para confirmar el pedido.\n\n"
        "¿No la recuerdas? Escribe *Me olvidé mi clave*.\n"
        "Escribe *MENU* para volver al menú principal."
    )


def _session_datos(session: dict | None) -> dict:
    if not session:
        return {}
    raw = session.get("datos")
    if isinstance(raw, str):
        try:
            return json.loads(raw) or {}
        except json.JSONDecodeError:
            return {}
    return raw or {}


def start_pin_reset(telefono: str, bodega: dict, session: dict | None = None) -> list:
    datos: dict[str, Any] = {"bodega_id": bodega["id"], "is_reset": True}
    if session:
        fase = session.get("fase") or ""
        ses_datos = _session_datos(session)
        if fase in ("pin_pago", "pin_confirm") and ses_datos.get("pedido_id"):
            datos["preserve_pin_pago"] = ses_datos

    db.update_bodega(bodega["id"], {
        "pin_intentos": 0,
        "pin_bloqueado_hasta": None,
    })
    db.upsert_session(telefono, "reset_clave", datos, bodega["id"])

    try:
        from app.services.analytics import track_event
        track_event(
            "pin_reset_started",
            bodega_id=bodega["id"],
            telefono=telefono,
            source="chat",
            metadata={"solo_dni": es_solo_dni(bodega)},
        )
    except Exception:
        pass

    return [msg_reset_intro(bodega)]


def _complete_reset_dni(
    telefono: str,
    bodega: dict,
    datos: dict,
    dni: str,
    nombre: str,
) -> list:
    db.update_bodega(bodega["id"], {
        "dni_representante": dni,
        "representante_legal": nombre or bodega.get("representante_legal", ""),
        "pin_hash": None,
        "pin_intentos": 0,
        "pin_bloqueado_hasta": None,
    })
    next_datos = {
        "bodega_id": bodega["id"],
        "is_reset": True,
        "dni_number": dni,
        "dni_nombre": nombre,
        "preserve_pin_pago": datos.get("preserve_pin_pago"),
    }
    db.upsert_session(telefono, "reg_pin", next_datos, bodega["id"])

    try:
        from app.services.analytics import track_event
        track_event(
            "pin_reset_dni_ok",
            bodega_id=bodega["id"],
            telefono=telefono,
            source="chat",
        )
    except Exception:
        pass

    return [
        msg_reset_dni_ok(nombre),
        {"signal": "PIN_ASK", "mode": "create", "bodega_id": bodega["id"]},
    ]


def handle_reset_clave(
    telefono: str,
    body_raw: str,
    body_n: str,
    bodega: dict,
    datos: dict,
    *,
    test_phones: set[str],
) -> list:
    if body_n in ("MENU", "CANCELAR", "VOLVER"):
        preserve = datos.get("preserve_pin_pago")
        if preserve:
            db.upsert_session(telefono, "pin_pago", preserve, bodega["id"])
            return [
                "↩️ Volviste a confirmar tu pedido.\n\n"
                "Te pediremos tu clave de 4 dígitos en un momento."
            ]
        db.upsert_session(telefono, "menu", {}, bodega["id"])
        return [{"signal": "MENU", "linea": bodega["linea_disponible"]}]

    if is_olvide_trigger(body_n):
        return [msg_reset_intro(bodega)]

    dni = body_raw.replace(" ", "")
    valid, _ = validate_dni_format(dni)
    if not valid:
        return [msg_reset_dni_invalid()]

    if telefono in test_phones:
        nombre = bodega.get("nombre_comercial") or bodega.get("representante_legal") or "Test"
        return _complete_reset_dni(telefono, bodega, datos, dni, nombre)

    reniec = consultar_dni_sync(dni)
    if not reniec:
        return [msg_reset_reniec_fail()]

    nombre = reniec.get("nombre_completo", "")
    if not es_solo_dni(bodega):
        rep = bodega.get("representante_legal", "")
        if rep and nombre and not _names_match(nombre, rep):
            return [msg_reset_dni_no_match(rep)]

    return _complete_reset_dni(telefono, bodega, datos, dni, nombre)


def after_pin_created_responses(telefono: str, bodega_id: str, datos: dict, linea: float) -> list:
    preserve = datos.get("preserve_pin_pago")
    if preserve:
        db.upsert_session(telefono, "pin_pago", preserve, bodega_id)
        try:
            from app.services.analytics import track_event
            track_event(
                "pin_reset_completed",
                bodega_id=bodega_id,
                telefono=telefono,
                source="chat",
                metadata={"restored_pedido": True},
            )
        except Exception:
            pass
        return [
            "✅ *Clave nueva lista.*\n\n"
            "Retomamos tu pedido pendiente. Confírmalo con tu clave nueva:",
            {"signal": "PIN_ASK", "mode": "verify", "bodega_id": bodega_id},
        ]
    try:
        from app.services.analytics import track_event
        track_event(
            "pin_reset_completed",
            bodega_id=bodega_id,
            telefono=telefono,
            source="chat",
            metadata={"restored_pedido": False},
        )
    except Exception:
        pass
    return [{"signal": "CUENTA_ACTIVA", "linea": linea}]
