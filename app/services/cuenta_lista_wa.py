"""Al precargar, escribirle al número que ya tenemos.

Ese envío hace que WhatsApp vuelva a incluir el teléfono en el webhook
durante 30 días. Así el próximo Hola entra a la bodega y no a un hilo
sin destinatario.

La plantilla ``circa_cuenta_lista`` tiene que estar aprobada en la cuenta
de WhatsApp (utilidad, sin variables). Si Meta la rechaza, el alta de la
bodega igual queda grabada.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone

logger = logging.getLogger("circa.cuenta_lista")

TEMPLATE_NAME = os.getenv("CUENTA_LISTA_TEMPLATE", "circa_cuenta_lista")
TEMPLATE_LANG = os.getenv("CUENTA_LISTA_TEMPLATE_LANG", "es")
_VENTANA = timedelta(days=25)
_LANG_CANDIDATOS = ("es", "es_MX", "es_ES", "es_AR")


def _ya_avisada(telefono_e164: str) -> bool:
    """True si en los últimos 25 días ya salió esta plantilla y Meta la aceptó."""
    desde = (datetime.now(timezone.utc) - _VENTANA).isoformat()
    try:
        from app.services import db

        rows = (
            db.sb.table("messages")
            .select("metadata,created_at")
            .eq("telefono", telefono_e164)
            .eq("direction", "outbound")
            .eq("template_name", TEMPLATE_NAME)
            .gte("created_at", desde)
            .order("created_at", desc=True)
            .limit(5)
            .execute()
            .data
            or []
        )
    except Exception as e:
        logger.warning("no se pudo revisar avisos previos de cuenta lista: %s", e)
        return False
    for row in rows:
        meta = row.get("metadata") or {}
        if isinstance(meta, str):
            continue
        if meta.get("envio_ok") is True:
            return True
    return False


def notificar_cuenta_lista(
    telefono: str,
    nombre: str = "",
    bodega_id: str | None = None,
) -> bool:
    """Manda la plantilla. No lanza: un fallo de WhatsApp no deshace la precarga."""
    from app.services.meta_client import send_template_sync
    from app.services.wa_identity import telefono_e164

    tel = telefono_e164(telefono)
    if not tel:
        logger.warning("cuenta lista sin teléfono válido")
        return False
    if _ya_avisada(tel):
        logger.info("cuenta lista ya avisada en la ventana %s", tel)
        return False

    idiomas = [TEMPLATE_LANG]
    for candidato in _LANG_CANDIDATOS:
        if candidato not in idiomas:
            idiomas.append(candidato)

    for lang in idiomas:
        ok, err = send_template_sync(
            tel,
            TEMPLATE_NAME,
            language=lang,
            contexto="cuenta_lista",
            bodega_id=bodega_id,
        )
        if ok:
            logger.info("cuenta lista enviada a %s (%s)", tel, lang)
            return True
        # 132001 = esa plantilla no existe en este idioma. Otro error no se arregla cambiando idioma.
        if "132001" not in (err or ""):
            break
    logger.warning(
        "cuenta lista no salió a %s bodega=%s nombre=%s",
        tel, bodega_id or "", (nombre or "")[:40],
    )
    return False


def avisar_cuenta_lista(telefono: str, nombre: str = "", bodega_id: str | None = None) -> None:
    """Igual que notificar, pero nunca interrumpe el alta."""
    try:
        notificar_cuenta_lista(telefono, nombre, bodega_id)
    except Exception as e:
        logger.warning("aviso cuenta lista: %s", e)
