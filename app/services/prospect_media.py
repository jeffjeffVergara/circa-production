"""
Persistencia de fotos de prospectos (números sin bodega).

Meta purga media_id en ~2–3 semanas; hay que bajar con download_media /
download_whatsapp_media_sync y subir a Storage antes de que se pierdan.

Buckets (mismo layout que /v/{token}/api/afiliar):
  - dni_fotos  → prospecto/{tel}/dni_*.jpg
  - sustentos  → prospecto/{tel}/local_*.jpg
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

from app.services import db

logger = logging.getLogger("circa.prospect_media")

BUCKET_DNI = "dni_fotos"
BUCKET_LOCAL = "sustentos"

# Copy provisional — la redacción final la define producto.
MSG_BIENVENIDA = """¡Hola, Bienvenido a Circa! 👋 Qué bueno que nos escribes.

Te cuento rapidito cómo funciona Circa Lab:

Somos el sistema que ayuda a tu negocio a crecer. Te damos una línea de crédito para que compres tu mercadería sin descapitalizarte — compras hoy, pagas cuando vendes. Sin ir al banco, sin papeleos, sin demoras.

Para afiliarte vamos *paso a paso*:

1️⃣ Tu RUC (11 dígitos) y/o DNI del representante (8 dígitos)
2️⃣ Foto de tu DNI
3️⃣ Foto de tu local

¿Empezamos? Mándame tu *RUC* o *DNI* por escrito."""

MSG_PEDIR_DNI_FOTO = (
    "✅ Datos recibidos.\n\n"
    "2️⃣ Ahora mándame una *foto de tu DNI* (por el frente; si puedes, también el reverso)."
)

MSG_PEDIR_LOCAL_FOTO = (
    "✅ DNI recibido.\n\n"
    "3️⃣ Ahora mándame una *foto de tu local* (fachada o interior)."
)

MSG_COMPLETO = (
    "✅ ¡Listo! Recibimos tus datos y fotos.\n\n"
    "En menos de 24 horas validamos tu solicitud y te escribimos "
    "para activar tu línea. ¡Gracias! 🚀"
)

MSG_REENVIA_FOTO = "❌ No pude guardar la foto. Intenta enviarlas de nuevo, por favor."
MSG_ESPERA_TEXTO = "Primero mándame tu *RUC* (11 dígitos) o *DNI* (8 dígitos) por escrito."
MSG_ESPERA_DNI_FOTO = "Ahora necesito la *foto de tu DNI* (envíala como imagen en este chat)."
MSG_ESPERA_LOCAL_FOTO = "Ahora necesito la *foto de tu local* (envíala como imagen en este chat)."


def _tel_path(telefono: str) -> str:
    digits = re.sub(r"\D", "", telefono or "")
    if len(digits) == 9:
        return f"+51{digits}"
    if digits.startswith("51") and len(digits) >= 11:
        return f"+{digits}"
    if telefono.startswith("+"):
        return telefono
    return f"+{digits}" if digits else (telefono or "unknown")


def _ext_from_mime(mime: str | None) -> str:
    return {"image/png": "png", "image/webp": "webp"}.get((mime or "").lower(), "jpg")


def upload_bytes(bucket: str, path: str, data: bytes, content_type: str) -> bool:
    try:
        db.sb.storage.from_(bucket).upload(
            path=path,
            file=data,
            file_options={"content-type": content_type, "upsert": "true"},
        )
        return True
    except Exception as e:
        logger.warning("No se pudo subir foto a %s/%s: %s", bucket, path, e)
        return False


def kind_for_paso(paso: str) -> str:
    if paso == "esperando_dni_foto":
        return "dni"
    if paso == "esperando_local_foto":
        return "local"
    return "otro"


def persist_image_bytes(
    telefono: str,
    image_bytes: bytes,
    kind: str,
    mime_type: str | None = None,
) -> dict | None:
    """Sube bytes al bucket correcto. Devuelve {bucket, path, kind} o None."""
    if not image_bytes:
        return None
    ct = mime_type or "image/jpeg"
    ext = _ext_from_mime(ct)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    tel = _tel_path(telefono)
    if kind == "dni":
        bucket, path = BUCKET_DNI, f"prospecto/{tel}/dni_{ts}.{ext}"
    elif kind == "local":
        bucket, path = BUCKET_LOCAL, f"prospecto/{tel}/local_{ts}.{ext}"
    else:
        bucket, path = BUCKET_LOCAL, f"prospecto/{tel}/otro_{ts}.{ext}"
    if not upload_bytes(bucket, path, image_bytes, ct):
        return None
    logger.info("Prospecto %s: foto %s → %s/%s", tel, kind, bucket, path)
    return {"bucket": bucket, "path": path, "kind": kind}


def persist_image_from_media_id(
    telefono: str,
    media_id: str,
    kind: str,
    mime_type: str | None = None,
) -> dict | None:
    from app.services.vision import download_whatsapp_media_sync

    raw = download_whatsapp_media_sync(media_id)
    if not raw:
        return None
    return persist_image_bytes(telefono, raw, kind, mime_type)


async def persist_image_from_media_id_async(
    telefono: str,
    media_id: str,
    kind: str,
    mime_type: str | None = None,
) -> dict | None:
    from app.services.meta_webhook import download_media

    raw = await download_media(media_id)
    if not raw:
        return None
    return persist_image_bytes(telefono, raw, kind, mime_type)


def session_datos(session: dict | None) -> dict:
    if not session:
        return {}
    raw = session.get("datos")
    if isinstance(raw, str):
        import json
        try:
            return json.loads(raw) or {}
        except Exception:
            return {}
    return raw or {}


def ensure_prospecto_session(telefono: str, session: dict | None) -> dict:
    """Crea o reusa sesión fase=prospecto. Devuelve datos."""
    datos = session_datos(session) if session and session.get("fase") == "prospecto" else {}
    if "paso" not in datos:
        datos["paso"] = "esperando_datos"
    if "fotos" not in datos:
        datos["fotos"] = []
    db.upsert_session(telefono, "prospecto", datos, None)
    return datos


def record_foto(datos: dict, saved: dict, media_id: str) -> dict:
    fotos = list(datos.get("fotos") or [])
    fotos.append({
        "kind": saved["kind"],
        "bucket": saved["bucket"],
        "path": saved["path"],
        "media_id": media_id,
    })
    datos["fotos"] = fotos
    if saved["kind"] == "dni":
        datos["dni_foto_path"] = saved["path"]
    elif saved["kind"] == "local":
        datos["local_foto_path"] = saved["path"]
    return datos


def parse_ruc_o_dni(text: str) -> tuple[str | None, str | None]:
    """Extrae (ruc, dni) si el mensaje trae 11 u 8 dígitos válidos."""
    digits = "".join(c for c in (text or "") if c.isdigit())
    ruc = dni = None
    if len(digits) == 11 and digits[:2] in ("10", "20"):
        ruc = digits
    elif len(digits) == 8:
        dni = digits
    elif len(digits) >= 19:  # RUC+DNI pegados
        if digits[:2] in ("10", "20"):
            ruc, rest = digits[:11], digits[11:]
            if len(rest) >= 8:
                dni = rest[:8]
    elif len(digits) == 19:
        pass
    return ruc, dni
