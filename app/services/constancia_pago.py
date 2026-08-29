"""
Captura de constancias de pago que envía la bodega por WhatsApp.

Problema que resuelve
---------------------
Cuando una bodega manda la foto de su Yape/Plin, el bot registraba el mensaje en
`messages` guardando sólo el `media_id` de Meta. La imagen nunca se descargaba.
Meta purga el medio a los ~30 días → el voucher se perdía para siempre.

Al 28/08/2026 hay 46 pedidos CRC pagados sin `pago_cliente_sustento_url` por esta
causa (23 bodegas, del 28/05 al 22/08).

Qué hace este módulo
--------------------
1. `guardar_entrante()` — SIEMPRE persiste la imagen en Storage, aunque no se
   pueda asociar a ningún pedido. Es la red de seguridad: nada se pierde.
2. Si además hay un pedido cobrable (`entregado` / `pago_reportado`) SIN sustento,
   la enlaza como `pago_cliente_sustento_url`.

Decisiones de diseño
--------------------
- **Nunca sobreescribe** un sustento existente. Ante la duda, la copia neutra
  queda en `sustentos/entrantes/` y Backoffice puede corregir.
- Se guarda **antes** de cualquier lógica de "Ya pagué", así que cubre el caso en
  que la constancia llega ANTES del botón (bug CRC-115, Market Jharfer 21/08).
- Si la bodega tiene varios pedidos cobrables, se elige **el más próximo a vencer**
  entre los que no tienen sustento. Es la heurística que usa cobranzas.
- Todo el módulo es best-effort: cualquier excepción se loguea y se traga. Guardar
  la constancia nunca debe romper la conversación con la bodega.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

from app.services import db

logger = logging.getLogger("circa")

BUCKET = "sustentos"
CARPETA_PEDIDO = "pagos_cliente"     # misma que usa Backoffice > Cobranzas
CARPETA_ENTRANTES = "entrantes"      # red de seguridad, no ligada a pedido

ESTADOS_COBRABLES = ("entregado", "pago_reportado")


def _ext(mime: str | None) -> str:
    return {"image/png": "png", "image/webp": "webp"}.get((mime or "").lower(), "jpg")


def _tel(telefono: str) -> str:
    d = re.sub(r"\D", "", telefono or "")
    return f"+{d}" if d else "desconocido"


def _public_url(path: str) -> str:
    from app.routes import distribuidor as dist
    return f"{dist.SUPABASE_URL}/storage/v1/object/public/{BUCKET}/{path}"


def _subir(path: str, data: bytes, content_type: str) -> bool:
    try:
        db.sb.storage.from_(BUCKET).upload(
            path=path,
            file=data,
            file_options={"content-type": content_type, "upsert": "true"},
        )
        return True
    except Exception as e:
        logger.warning("constancia: no se pudo subir %s/%s: %s", BUCKET, path, e)
        return False


def _pedido_destino(bodega_id: str) -> dict | None:
    """Pedido cobrable sin sustento, el más próximo a vencer."""
    try:
        rows = (
            db.sb.table("pedidos")
            .select("id,numero,estado,fecha_vencimiento,pago_cliente_sustento_url")
            .eq("bodega_id", bodega_id)
            .in_("estado", list(ESTADOS_COBRABLES))
            .execute()
            .data
        ) or []
    except Exception as e:
        logger.warning("constancia: no se pudo listar pedidos de %s: %s", bodega_id, e)
        return None

    candidatos = [r for r in rows if not r.get("pago_cliente_sustento_url")]
    if not candidatos:
        return None
    # pago_reportado gana sobre entregado: la bodega ya declaró que pagó.
    candidatos.sort(
        key=lambda r: (
            0 if r.get("estado") == "pago_reportado" else 1,
            r.get("fecha_vencimiento") or "9999-12-31",
        )
    )
    return candidatos[0]


def guardar_entrante(
    telefono: str,
    media_id: str,
    bodega: dict | None,
    mime_type: str | None = None,
) -> dict | None:
    """
    Descarga la imagen de Meta y la persiste. Si hay pedido cobrable sin sustento,
    la enlaza. Devuelve {path, url, pedido_numero|None} o None.

    Best-effort: nunca lanza.
    """
    if not media_id:
        return None
    try:
        from app.services.vision import download_whatsapp_media_sync

        raw = download_whatsapp_media_sync(media_id)
        if not raw:
            logger.warning("constancia: media %s no se pudo descargar (tel %s)", media_id, telefono)
            return None

        ct = mime_type or "image/jpeg"
        ext = _ext(ct)
        ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")

        # 1) Copia neutra — esto es lo que garantiza que nada se pierda.
        path_neutro = f"{CARPETA_ENTRANTES}/{_tel(telefono)}/{ts}_{media_id[:12]}.{ext}"
        if not _subir(path_neutro, raw, ct):
            return None
        logger.info("constancia: imagen de %s guardada en %s", telefono, path_neutro)

        resultado = {"path": path_neutro, "url": _public_url(path_neutro), "pedido_numero": None}

        # 2) Enlace al pedido, sólo si corresponde y sin pisar nada.
        if not bodega or not bodega.get("id"):
            return resultado

        pedido = _pedido_destino(bodega["id"])
        if not pedido:
            return resultado

        path_pedido = f"{CARPETA_PEDIDO}/{pedido['id']}.{ext}"
        if not _subir(path_pedido, raw, ct):
            return resultado

        ahora = datetime.now(timezone.utc).isoformat()
        db.sb.table("pedidos").update({
            "pago_cliente_sustento_url": _public_url(path_pedido),
            "pago_cliente_sustento_subido_at": ahora,
        }).eq("id", pedido["id"]).execute()

        resultado["pedido_numero"] = pedido.get("numero")
        resultado["url"] = _public_url(path_pedido)
        logger.info(
            "constancia: %s enlazada a pedido %s (estado %s)",
            telefono, pedido.get("numero"), pedido.get("estado"),
        )
        try:
            db.log_evento(
                pedido["id"], None, "constancia_pago_capturada",
                None, path_pedido, "bot",
            )
        except Exception:
            pass
        return resultado

    except Exception as e:
        logger.error("constancia: fallo guardando media %s de %s: %s", media_id, telefono, e, exc_info=True)
        return None
