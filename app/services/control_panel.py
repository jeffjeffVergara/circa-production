"""Búsqueda y acciones de soporte por DNI / teléfono (Control Panel)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from app.services import db
from app.services.client_observability import search_bodegas

_FASE_LABELS = {
    "welcome": "Bienvenida",
    "reg_ruc": "Registro RUC",
    "reg_dni": "Verificación DNI",
    "reg_biometria": "Selfie / biometría",
    "reg_linea_acepta": "Aceptación de línea",
    "reg_contrato": "Contrato",
    "reg_pin": "Creación de PIN",
    "reset_clave": "Reset de clave (WA)",
    "menu": "Menú principal",
    "catalogo": "Catálogo",
    "cart_review": "Revisión carrito",
    "pin_pago": "PIN de pago",
}


def _parse_session_datos(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {}
    return {}


def _pin_status(bodega: dict[str, Any]) -> dict[str, Any]:
    blocked_until = bodega.get("pin_bloqueado_hasta")
    blocked = False
    if blocked_until:
        try:
            dt = datetime.fromisoformat(str(blocked_until).replace("Z", "+00:00"))
            blocked = dt > datetime.now(timezone.utc)
        except (TypeError, ValueError):
            blocked = False
    return {
        "has_pin": bool(bodega.get("pin_hash")),
        "intentos": int(bodega.get("pin_intentos") or 0),
        "bloqueado": blocked,
        "bloqueado_hasta": blocked_until,
    }


def lookup_bodegas(query: str, *, limit: int = 15) -> list[dict[str, Any]]:
    """Busca bodegas y enriquece con sesión WA y estado de PIN."""
    base_rows = search_bodegas(query, limit=min(limit, 25))
    if not base_rows:
        return []

    ids = [r["id"] for r in base_rows if r.get("id")]
    extra_by_id: dict[str, dict] = {}
    if ids:
        extra_rows = (
            db.sb.table("bodegas")
            .select(
                "id,pin_hash,pin_intentos,pin_bloqueado_hasta,onboarding_fase,kyc_nivel,representante_nombre_corto"
            )
            .in_("id", ids)
            .execute()
            .data
            or []
        )
        extra_by_id = {r["id"]: r for r in extra_rows}

    out: list[dict[str, Any]] = []
    for row in base_rows:
        bid = row.get("id")
        extra = extra_by_id.get(bid or "", {})
        merged = {**row, **extra}
        tel = merged.get("telefono_whatsapp") or ""
        ses = db.get_session(tel) if tel else None
        fase = ses.get("fase") if ses else None
        datos = _parse_session_datos(ses.get("datos") if ses else None)
        pin = _pin_status(merged)
        out.append(
            {
                **merged,
                "sesion": {
                    "fase": fase,
                    "fase_label": _FASE_LABELS.get(str(fase or ""), str(fase or "sin sesión")),
                    "last_activity": ses.get("last_activity") if ses else None,
                    "datos_keys": sorted(datos.keys()) if datos else [],
                },
                "pin_status": pin,
            }
        )
    return out


def unlock_pin(bodega_id: str) -> dict[str, Any]:
    """Quita bloqueo e intentos fallidos de PIN sin borrar la clave."""
    rows = (
        db.sb.table("bodegas")
        .select("id,telefono_whatsapp,pin_hash")
        .eq("id", bodega_id)
        .limit(1)
        .execute()
        .data
        or []
    )
    if not rows:
        raise ValueError("Bodega no encontrada")
    db.update_bodega(
        bodega_id,
        {"pin_intentos": 0, "pin_bloqueado_hasta": None},
    )
    return {"ok": True, "telefono": rows[0].get("telefono_whatsapp")}
