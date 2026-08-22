"""
Express Onboarding (piloto) — módulo aparte del onboarding clásico.

Flujo:
  express_welcome → express_foto (1 foto: DNI *o* selfie)
  → express_linea → express_tyc → activo sin PIN → menu

Entradas cubiertas (mismo gate):
  - de cero (sin bodega)
  - precarga
  - post-afiliar vendedor

No modifica state_machine reg_* / prospecto clásico.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import datetime

from app.services import db
from app.services.distribuidor_routing import ZOOM_DISTRIBUIDOR_ID
from app.services.express_onboarding_gate import (
    is_express_pilot_phone,
    normalize_phone_e164,
    should_use_express_onboarding,
)
from app.services.identity import consultar_dni_sync, validate_dni_format
from app.services import prospect_media as pm

logger = logging.getLogger("circa.express_onboarding")

# Re-export para callers
should_handle = should_use_express_onboarding

MSG_FOTO = (
    "📸 *Express Onboarding*\n\n"
    "Envía *una sola foto*: puede ser el *anverso de tu DNI* "
    "o una *selfie* clara de tu rostro.\n\n"
    "Con una alcanza — no hace falta mandar las dos."
)


def _session_datos(session: dict | None) -> dict:
    if not session:
        return {}
    raw = session.get("datos")
    if isinstance(raw, dict):
        return dict(raw)
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
            # Doble encode legacy
            if isinstance(parsed, str):
                parsed = json.loads(parsed)
            return dict(parsed) if isinstance(parsed, dict) else {}
        except Exception:
            return {}
    return {}


def _dist_nombre(bodega: dict | None) -> str:
    if not bodega or not bodega.get("distribuidor_id"):
        return "tu distribuidor"
    try:
        rows = (
            db.sb.table("distribuidores")
            .select("nombre_comercial")
            .eq("id", bodega["distribuidor_id"])
            .limit(1)
            .execute()
            .data
            or []
        )
        if rows:
            return rows[0].get("nombre_comercial") or "tu distribuidor"
    except Exception as e:
        logger.warning("express dist nombre: %s", e)
    return "tu distribuidor"


def _welcome_payload(bodega: dict) -> list:
    nombre = bodega.get("nombre_comercial") or bodega.get("razon_social") or ""
    linea = float(bodega.get("linea_aprobada") or 500)
    return [{
        "signal": "WELCOME",
        "nombre": nombre,
        "linea": linea,
        "distribuidor": _dist_nombre(bodega),
    }]


def _enter_welcome(telefono: str, bodega: dict) -> list:
    db.upsert_session(telefono, "express_welcome", {"bodega_id": bodega["id"]}, bodega["id"])
    return _welcome_payload(bodega)


def _enter_foto(telefono: str, bodega: dict, datos: dict) -> list:
    datos = {**datos, "bodega_id": bodega["id"]}
    db.upsert_session(telefono, "express_foto", datos, bodega["id"])
    return [MSG_FOTO]


def _enter_linea(telefono: str, bodega: dict, datos: dict) -> list:
    datos = {**datos, "bodega_id": bodega["id"]}
    db.upsert_session(telefono, "express_linea", datos, bodega["id"])
    return [{
        "signal": "LINEA_OFERTA",
        "nombre": bodega.get("nombre_comercial") or bodega.get("razon_social") or "",
        "linea": float(bodega.get("linea_aprobada") or 500),
        "distribuidor": _dist_nombre(bodega),
    }]


def _create_bodega_cold(telefono: str, *, dni: str | None, ruc: str | None, nombre: str) -> dict:
    tel = normalize_phone_e164(telefono)
    linea = 200.0
    payload = {
        "telefono_whatsapp": tel,
        "razon_social": nombre,
        "nombre_comercial": nombre,
        "representante_legal": nombre,
        "dni_representante": dni,
        "ruc": ruc,
        "solo_dni_sin_ruc": bool(dni and not ruc),
        "distribuidor_id": ZOOM_DISTRIBUIDOR_ID,
        "estado": "inactivo",
        "onboarding_fase": "express",
        "kyc_nivel": "ninguno",
        "linea_aprobada": linea,
        "linea_disponible": 0,
        "es_test": True,
        "en_piloto": True,
    }
    payload = {k: v for k, v in payload.items() if v is not None}
    res = db.sb.table("bodegas").insert(payload).execute()
    row = (res.data or [None])[0]
    if not row:
        row = db.get_bodega_by_phone(tel)
    if not row:
        raise RuntimeError("No se pudo crear bodega Express")
    return row


def _handle_cold(
    telefono: str,
    body_raw: str,
    body_n: str,
    media_url: str | None,
    session: dict | None,
) -> list:
    """Sin bodega: pedir DNI/RUC, crear bodega mínima, seguir Express."""
    datos = _session_datos(session) if session and (session.get("fase") or "").startswith("express_") else {}
    fase = (session or {}).get("fase") or ""

    if fase != "express_cold":
        db.upsert_session(telefono, "express_cold", {}, None)
        return [
            "⚡ *Express Onboarding*\n\n"
            "Para crear tu cuenta mándame tu *DNI* (8 dígitos) "
            "o *RUC* (11 dígitos) por escrito."
        ]

    digits = re.sub(r"\D", "", body_raw or "")
    if len(digits) == 8:
        ok, msg = validate_dni_format(digits)
        if not ok:
            return [f"❌ {msg}"]
        nombre = f"PENDIENTE VERIFICAR - DNI {digits}"
        try:
            persona = consultar_dni_sync(digits)
            if persona and persona.get("nombre_completo"):
                nombre = persona["nombre_completo"]
        except Exception as e:
            logger.warning("express RENIEC DNI %s: %s", digits, e)
        try:
            bodega = _create_bodega_cold(telefono, dni=digits, ruc=None, nombre=nombre)
        except Exception as e:
            logger.error("express create bodega: %s", e, exc_info=True)
            return ["❌ No pude crear tu cuenta. Intenta de nuevo en un momento."]
        return _enter_welcome(telefono, bodega)

    if len(digits) == 11:
        nombre = f"RUC {digits}"
        try:
            from app.services.identity import consultar_ruc_sync
            ruc_data = consultar_ruc_sync(digits)
            if ruc_data and ruc_data.get("razon_social"):
                nombre = ruc_data["razon_social"]
        except Exception as e:
            logger.warning("express SUNAT RUC %s: %s", digits, e)
        try:
            bodega = _create_bodega_cold(telefono, dni=None, ruc=digits, nombre=nombre)
        except Exception as e:
            logger.error("express create bodega ruc: %s", e, exc_info=True)
            return ["❌ No pude crear tu cuenta. Intenta de nuevo en un momento."]
        return _enter_welcome(telefono, bodega)

    if media_url:
        return ["Primero mándame tu *DNI* (8) o *RUC* (11) por escrito; después la foto."]

    return ["Escribe tu *DNI* (8 dígitos) o *RUC* (11 dígitos) para continuar."]


def handle(
    telefono: str,
    body_raw: str,
    body_n: str,
    media_url: str | None,
    session: dict | None,
    bodega: dict | None,
) -> list:
    if not is_express_pilot_phone(telefono):
        return ["❌ Este flujo no está disponible para tu número."]

    # De cero
    if not bodega:
        return _handle_cold(telefono, body_raw, body_n, media_url, session)

    fase = (session or {}).get("fase") or ""
    datos = _session_datos(session)

    # Entrada: sin sesión o fuera de express_* → welcome Express
    if not session or not fase.startswith("express_"):
        return _enter_welcome(telefono, bodega)

    # ── welcome ──
    if fase == "express_welcome":
        if body_n in ("SI", "ACTIVAR", "1", "HOLA", "HI", "MAS_INFO", "MAS INFO", "CONTINUAR"):
            return _enter_foto(telefono, bodega, datos)
        return _welcome_payload(bodega)

    # ── una sola foto (DNI o selfie) ──
    if fase == "express_foto":
        if media_url:
            saved = pm.persist_image_from_media_id(telefono, media_url, "dni")
            if not saved:
                return ["❌ No pude guardar la foto. Envía de nuevo una imagen nítida."]
            path = saved.get("path") or ""
            try:
                db.update_bodega(bodega["id"], {
                    "dni_foto_url": path,
                    "kyc_nivel": "express",
                    "onboarding_fase": "express_foto",
                })
            except Exception as e:
                logger.warning("express update foto bodega: %s", e)
            datos["express_foto_path"] = path
            datos["bodega_id"] = bodega["id"]
            # refrescar bodega para LINEA_OFERTA
            bodega = db.get_bodega_by_phone(telefono) or bodega
            return [
                "✅ Foto recibida. Seguimos.",
                *_enter_linea(telefono, bodega, datos),
            ]
        if body_n in ("HOLA", "HI", "MENU"):
            return [MSG_FOTO]
        return [MSG_FOTO]

    # ── aceptar línea (igual que clásico) ──
    if fase == "express_linea":
        bodega_id = datos.get("bodega_id") or bodega["id"]
        if body_n in ("SI", "ACEPTO", "ACEPTO_LINEA", "ACEPTO LINEA", "1", "CONTINUAR"):
            datos["bodega_id"] = bodega_id
            datos["contrato_shown"] = True
            db.upsert_session(telefono, "express_tyc", datos, bodega_id)
            linea = float(bodega.get("linea_aprobada") or 500)
            return [{"signal": "CONTRATO", "linea": linea}]
        if body_n in ("NO", "NO_GRACIAS", "NO GRACIAS"):
            db.upsert_session(telefono, "express_welcome", {"bodega_id": bodega_id}, bodega_id)
            return ["Entendido. Cuando quieras activar tu línea, escríbenos."]
        return ["Escribe *SI* para aceptar la línea o *NO* para rechazar."]

    # ── términos y condiciones (sin PIN) ──
    if fase == "express_tyc":
        bodega_id = datos.get("bodega_id") or bodega["id"]
        if body_n in ("ACEPTO", "SI", "1"):
            if not datos.get("contrato_shown"):
                datos["contrato_shown"] = True
                db.upsert_session(telefono, "express_tyc", datos, bodega_id)
                return [{"signal": "CONTRATO", "linea": float(bodega.get("linea_aprobada") or 500)}]

            contract_data = f"{bodega_id}|{telefono}|express|{datetime.utcnow().isoformat()}"
            contract_hash = hashlib.sha256(contract_data.encode()).hexdigest()
            db.sign_contract(bodega_id, contract_hash)
            # Activa sin crear clave
            db.update_bodega(bodega_id, {
                "estado": "activo",
                "onboarding_fase": "express_completo",
                "pin_hash": None,
                "pin_intentos": 0,
                "pin_bloqueado_hasta": None,
            })
            bodega_u = (
                db.sb.table("bodegas")
                .select("linea_disponible")
                .eq("id", bodega_id)
                .limit(1)
                .execute()
                .data
                or []
            )
            linea = float((bodega_u[0].get("linea_disponible") if bodega_u else None) or bodega.get("linea_aprobada") or 0)
            db.upsert_session(telefono, "menu", {}, bodega_id)
            return [{"signal": "CUENTA_ACTIVA", "linea": linea}]

        if datos.get("contrato_shown"):
            return ["Escribe *ACEPTO* para aceptar los términos y condiciones."]
        return [{"signal": "CONTRATO", "linea": float(bodega.get("linea_aprobada") or 500)}]

    # Fase express desconocida → reiniciar
    return _enter_welcome(telefono, bodega)
