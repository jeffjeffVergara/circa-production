"""Observabilidad de recorrido del cliente (onboarding, WA, biometría, errores)."""

from __future__ import annotations

import json
import logging
import os
from typing import Any

import httpx

from app.config import ANTHROPIC_VISION_MODEL
from app.services import db

logger = logging.getLogger("circa.observability")

_BODEGA_COLS = (
    "id,razon_social,nombre_comercial,telefono_whatsapp,dni_representante,"
    "representante_legal,estado,onboarding_fase,kyc_nivel,es_test,solo_dni_sin_ruc,"
    "linea_aprobada,linea_disponible,created_at,updated_at"
)

_FASE_LABELS = {
    "welcome": "Bienvenida",
    "reg_ruc": "Registro RUC",
    "reg_dni": "Verificación DNI",
    "reg_biometria": "Selfie / biometría",
    "reg_linea_acepta": "Aceptación de línea",
    "reg_contrato": "Contrato",
    "reg_pin": "Creación de PIN",
    "menu": "Menú principal",
    "reset_clave": "Reset de clave",
}

_ANALYTICS_EVENT_LABELS = {
    "message_replied": "cliente respondió en WA",
    "message_sent": "Circa envió mensaje WA",
    "catalog_opened": "abrió catálogo",
    "order_created": "creó pedido",
}

_WA_DIRECTION_LABELS = {
    "inbound": "entrada · bodeguero → Circa",
    "outbound": "salida · Circa → bodeguero",
}

_WA_TYPE_HINTS = {
    "text": "texto escrito o botón",
    "image": "foto (DNI, selfie, etc.)",
    "interactive": "botón o lista de WhatsApp",
    "button": "respuesta a botón",
    "document": "documento adjunto",
    "audio": "nota de voz",
    "video": "video",
}


def _analytics_title(event_type: str) -> str:
    key = (event_type or "event").strip()
    label = _ANALYTICS_EVENT_LABELS.get(key, key.replace("_", " "))
    return f"Analytics · {label}"


def _analytics_detail(row: dict[str, Any]) -> str:
    et = row.get("event_type") or ""
    parts = []
    if et == "message_replied":
        parts.append("El bodeguero envió un mensaje; el sistema lo contabiliza para métricas de respuesta.")
    elif et == "message_sent":
        parts.append("Circa envió un mensaje al bodeguero; registro paralelo al WA outbound.")
    meta = row.get("metadata") or {}
    if meta.get("message_type"):
        parts.append(f"tipo {meta['message_type']}")
    if meta.get("response_time_ms") is not None:
        parts.append(f"latencia respuesta {meta['response_time_ms']} ms")
    parts.append(f"origen {row.get('source') or '—'}")
    return " · ".join(parts)


def _wa_message_title(row: dict[str, Any]) -> str:
    direction = row.get("direction") or "?"
    mtype = row.get("message_type") or "text"
    dir_lbl = _WA_DIRECTION_LABELS.get(direction, direction)
    return f"WA {dir_lbl} · {mtype}"


def _wa_message_detail(row: dict[str, Any]) -> str:
    content = (row.get("content") or "").strip()
    mtype = row.get("message_type") or "text"
    hint = _WA_TYPE_HINTS.get(mtype, mtype)
    prefix = f"[{hint}] "
    if row.get("template_name"):
        prefix += f"plantilla {row['template_name']} · "
    body = content or "(sin texto visible)"
    if len(body) > 220:
        body = body[:217] + "…"
    rt = row.get("response_time_ms")
    if rt is not None and row.get("direction") == "outbound":
        body += f" · tiempo de respuesta del bot: {rt} ms"
    return prefix + body


def _digits_only(value: str) -> str:
    return "".join(c for c in (value or "") if c.isdigit())


def _phone_e164(value: str) -> str | None:
    digits = _digits_only(value)
    if len(digits) < 9:
        return None
    if digits.startswith("51") and len(digits) == 11:
        return f"+{digits}"
    if len(digits) == 9:
        return f"+51{digits}"
    return f"+{digits}"


def search_bodegas(query: str, *, limit: int = 20) -> list[dict[str, Any]]:
    """Busca bodegas por DNI, teléfono, razón social o nombre comercial."""
    q = (query or "").strip()
    if len(q) < 2:
        return []

    lim = max(1, min(limit, 50))
    found: dict[str, dict[str, Any]] = {}
    digits = _digits_only(q)

    def _add(rows: list[dict] | None) -> None:
        for row in rows or []:
            found[row["id"]] = row

    if len(digits) == 8:
        _add(
            db.sb.table("bodegas")
            .select(_BODEGA_COLS)
            .eq("dni_representante", digits)
            .limit(lim)
            .execute()
            .data
        )

    tel = _phone_e164(q) or (_phone_e164(digits) if digits else None)
    if tel:
        _add(
            db.sb.table("bodegas")
            .select(_BODEGA_COLS)
            .eq("telefono_whatsapp", tel)
            .limit(lim)
            .execute()
            .data
        )

    pattern = f"%{q}%"
    for col in ("razon_social", "nombre_comercial", "representante_legal"):
        _add(
            db.sb.table("bodegas")
            .select(_BODEGA_COLS)
            .ilike(col, pattern)
            .limit(lim)
            .execute()
            .data
        )

    rows = list(found.values())
    rows.sort(key=lambda r: r.get("created_at") or "", reverse=True)
    return rows[:lim]


def _event(
    at: str | None,
    *,
    kind: str,
    title: str,
    detail: str = "",
    status: str = "info",
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "at": at,
        "kind": kind,
        "title": title,
        "detail": detail,
        "status": status,
        "meta": meta or {},
    }


def _fetch_table(
    table: str,
    *,
    bodega_id: str,
    telefono: str | None,
    select: str,
    order_col: str = "created_at",
    limit: int = 80,
) -> list[dict[str, Any]]:
    try:
        q = db.sb.table(table).select(select).order(order_col, desc=True).limit(limit)
        if bodega_id:
            q = q.eq("bodega_id", bodega_id)
        elif telefono:
            q = q.eq("telefono", telefono)
        else:
            return []
        return q.execute().data or []
    except Exception as e:
        logger.warning("observability fetch %s: %s", table, e)
        return []


def build_timeline(bodega_id: str) -> dict[str, Any]:
    """Arma línea de tiempo unificada para una bodega."""
    bodega = (
        db.sb.table("bodegas").select(_BODEGA_COLS).eq("id", bodega_id).limit(1).execute().data
        or []
    )
    if not bodega:
        return {"bodega": None, "events": [], "summary": {}}
    b = bodega[0]
    tel = b.get("telefono_whatsapp") or ""
    events: list[dict[str, Any]] = []

    events.append(
        _event(
            b.get("created_at"),
            kind="bodega",
            title="Alta en Circa",
            detail=f"{b.get('razon_social')} · estado {b.get('estado')} · onboarding {b.get('onboarding_fase')}",
            status="info",
            meta={"linea_aprobada": b.get("linea_aprobada")},
        )
    )

    ses = (
        db.sb.table("sesiones")
        .select("fase,datos,last_activity,expires_at")
        .eq("bodega_id", bodega_id)
        .limit(1)
        .execute()
        .data
        or []
    )
    if not ses and tel:
        ses = (
            db.sb.table("sesiones")
            .select("fase,datos,last_activity,expires_at")
            .eq("telefono", tel)
            .limit(1)
            .execute()
            .data
            or []
        )
    if ses:
        s = ses[0]
        fase = str(s.get("fase") or "")
        datos = s.get("datos") or {}
        if isinstance(datos, str):
            try:
                datos = json.loads(datos)
            except json.JSONDecodeError:
                datos = {}
        detail_parts = [f"Fase actual: {_FASE_LABELS.get(fase, fase)}"]
        if datos.get("dni_number"):
            detail_parts.append(f"DNI en sesión: {datos.get('dni_number')}")
        if datos.get("dni_nombre"):
            detail_parts.append(f"Nombre RENIEC: {datos.get('dni_nombre')}")
        flags = []
        if datos.get("dni_verified"):
            flags.append("dni_verified")
        if datos.get("dni_photo_verified"):
            flags.append("dni_photo_verified")
        if datos.get("biometria_verified"):
            flags.append("biometria_verified")
        if flags:
            detail_parts.append("Flags: " + ", ".join(flags))
        events.append(
            _event(
                s.get("last_activity"),
                kind="sesion",
                title="Estado de sesión WhatsApp",
                detail=" · ".join(detail_parts),
                status="info",
                meta={"fase": fase, "datos": datos},
            )
        )

    for row in _fetch_table(
        "biometria_auditoria",
        bodega_id=bodega_id,
        telefono=tel,
        select="created_at,etapa,hit,reason,reason_code,confidence,metadata",
        limit=40,
    ):
        etapa = row.get("etapa") or "kyc"
        hit = bool(row.get("hit"))
        events.append(
            _event(
                row.get("created_at"),
                kind="biometria",
                title=f"Biometría · {etapa}",
                detail=row.get("reason") or "",
                status="ok" if hit else "error",
                meta={
                    "reason_code": row.get("reason_code"),
                    "confidence": row.get("confidence"),
                    "metadata": row.get("metadata") or {},
                },
            )
        )

    for row in _fetch_table(
        "eventos",
        bodega_id=bodega_id,
        telefono=tel,
        select="created_at,accion,estado_anterior,estado_nuevo,actor,metadata",
        limit=40,
    ):
        events.append(
            _event(
                row.get("created_at"),
                kind="evento",
                title=f"Evento · {row.get('accion') or 'accion'}",
                detail=f"{row.get('estado_anterior') or '—'} → {row.get('estado_nuevo') or '—'}",
                status="info",
                meta={"actor": row.get("actor"), "metadata": row.get("metadata") or {}},
            )
        )

    for row in _fetch_table(
        "events",
        bodega_id=bodega_id,
        telefono=tel,
        select="created_at,event_type,source,channel,metadata",
        limit=40,
    ):
        events.append(
            _event(
                row.get("created_at"),
                kind="analytics",
                title=_analytics_title(row.get("event_type") or ""),
                detail=_analytics_detail(row),
                status="info",
                meta=row.get("metadata") or {},
            )
        )

    msg_q = (
        db.sb.table("messages")
        .select("created_at,direction,message_type,content,template_name,response_time_ms,metadata")
        .order("created_at", desc=True)
        .limit(60)
    )
    if bodega_id:
        msg_q = msg_q.eq("bodega_id", bodega_id)
    elif tel:
        msg_q = msg_q.eq("telefono", tel)
    try:
        messages = msg_q.execute().data or []
    except Exception:
        messages = []

    for row in messages:
        events.append(
            _event(
                row.get("created_at"),
                kind="mensaje",
                title=_wa_message_title(row),
                detail=_wa_message_detail(row),
                status="info",
                meta={
                    "response_time_ms": row.get("response_time_ms"),
                    "metadata": row.get("metadata") or {},
                },
            )
        )

    try:
        bo_rows = (
            db.sb.table("backoffice_audit_log")
            .select("created_at,action,comment,entity_type,user_email,after_json,before_json")
            .eq("entity_type", "bodega")
            .eq("entity_id", bodega_id)
            .order("created_at", desc=True)
            .limit(30)
            .execute()
            .data
            or []
        )
    except Exception:
        bo_rows = []

    for row in bo_rows:
        events.append(
            _event(
                row.get("created_at"),
                kind="backoffice",
                title=f"Backoffice · {row.get('action') or 'accion'}",
                detail=(row.get("comment") or "")[:300],
                status="info",
                meta={"user_email": row.get("user_email"), "after": row.get("after_json")},
            )
        )

    events = [e for e in events if e.get("at")]
    events.sort(key=lambda e: e["at"], reverse=True)

    errors = [e for e in events if e.get("status") == "error"]
    last_fase = ses[0].get("fase") if ses else b.get("onboarding_fase")

    return {
        "bodega": b,
        "events": events,
        "summary": {
            "total_events": len(events),
            "errors": len(errors),
            "last_error": errors[0] if errors else None,
            "current_fase": str(last_fase or ""),
            "current_fase_label": _FASE_LABELS.get(str(last_fase or ""), str(last_fase or "")),
        },
    }


def _timeline_for_claude(timeline: dict[str, Any], *, max_events: int = 40) -> str:
    b = timeline.get("bodega") or {}
    lines = [
        f"Bodega: {b.get('razon_social')} ({b.get('nombre_comercial') or '—'})",
        f"Teléfono: {b.get('telefono_whatsapp')} · DNI: {b.get('dni_representante') or '—'}",
        f"Representante: {b.get('representante_legal') or '—'}",
        f"Estado: {b.get('estado')} · Onboarding: {b.get('onboarding_fase')} · KYC: {b.get('kyc_nivel')}",
        f"es_test={b.get('es_test')} solo_dni_sin_ruc={b.get('solo_dni_sin_ruc')}",
        "",
        "Línea de tiempo (más reciente primero):",
    ]
    for ev in (timeline.get("events") or [])[:max_events]:
        lines.append(
            f"- [{ev.get('at')}] ({ev.get('status')}) {ev.get('kind')}: {ev.get('title')} — {ev.get('detail')}"
        )
    summary = timeline.get("summary") or {}
    if summary.get("last_error"):
        le = summary["last_error"]
        lines.extend(["", "Último error registrado:", f"- {le.get('title')}: {le.get('detail')}"])
    return "\n".join(lines)


def analyze_with_claude(
    timeline: dict[str, Any],
    *,
    question: str | None = None,
) -> dict[str, Any]:
    """Análisis on-demand con Claude sobre el recorrido del cliente."""
    api_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY no configurada en el servidor")

    context = _timeline_for_claude(timeline)
    user_q = (question or "").strip() or (
        "Explica qué pasó con este cliente en el onboarding, si hay errores o bloqueos, "
        "por qué pudo fallar, y qué acción concreta recomiendas al equipo de soporte."
    )

    system = (
        "Eres un analista de soporte de Circa (crédito embebido para bodegas en Perú vía WhatsApp). "
        "Interpretas logs de sesión, biometría KYC, mensajes y eventos. "
        "Responde en español, claro y accionable: (1) resumen del recorrido, (2) errores detectados y causa probable, "
        "(3) estado actual, (4) pasos recomendados para soporte. "
        "No inventes datos que no estén en el contexto."
    )

    model = os.getenv("OBSERVABILITY_CLAUDE_MODEL", ANTHROPIC_VISION_MODEL).strip()

    try:
        r = httpx.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": model,
                "max_tokens": 1200,
                "system": system,
                "messages": [
                    {
                        "role": "user",
                        "content": f"Contexto del cliente:\n\n{context}\n\nPregunta del operador:\n{user_q}",
                    }
                ],
            },
            timeout=60.0,
        )
        r.raise_for_status()
        data = r.json()
        text = ""
        for block in data.get("content") or []:
            if block.get("type") == "text":
                text += block.get("text") or ""
        return {
            "analysis": text.strip() or "Sin respuesta del modelo.",
            "model": model,
            "question": user_q,
        }
    except httpx.HTTPStatusError as e:
        logger.error("Claude analyze HTTP %s: %s", e.response.status_code, e.response.text[:400])
        raise RuntimeError("Claude no respondió correctamente") from e
    except Exception as e:
        logger.error("Claude analyze error: %s", e, exc_info=True)
        raise RuntimeError("No se pudo completar el análisis con Claude") from e
