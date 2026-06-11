"""Resumen WhatsApp de preventa armada por vendedor (link_token / AVISAR)."""
from __future__ import annotations

import json
from typing import Any

from app.services import db
from app.services.representante_comms import nombre_para_comunicar_representante


def nombre_corto_vendedor(nombre_completo: str) -> str:
    if not nombre_completo:
        return "tu vendedor"
    tokens = nombre_completo.strip().split()
    if len(tokens) >= 3:
        return tokens[2].capitalize()
    if tokens:
        return tokens[0].capitalize()
    return "tu vendedor"


def parse_items_json(pedido: dict) -> list[dict[str, Any]]:
    try:
        raw = pedido.get("items_json")
        items = json.loads(raw) if isinstance(raw, str) else (raw or [])
        return items if isinstance(items, list) else []
    except Exception:
        return []


def resumen_items_text(items: list, max_lineas: int = 10) -> str:
    out = []
    for i in items[:max_lineas]:
        qty = i.get("cantidad", 1)
        nom = (i.get("nombre") or "")[:45]
        sub = float(i.get("subtotal") or 0)
        out.append(f"{qty}x {nom} — S/{sub:.2f}")
    if len(items) > max_lineas:
        out.append(f"... y {len(items) - max_lineas} productos más")
    return "\n".join(out)


def calc_financiable_efectivo(total: float, linea_disponible: float) -> tuple[float, float]:
    linea = float(linea_disponible or 0)
    financiable = round(min(total, linea), 2)
    efectivo = round(max(0.0, total - linea), 2)
    return financiable, efectivo


def build_preventa_propuesta_mensaje(
    *,
    bodega: dict,
    items: list,
    total: float,
    linea_disponible: float,
    vendedor_nombre: str,
) -> str:
    items_text = resumen_items_text(items)
    financiable, efectivo = calc_financiable_efectivo(total, linea_disponible)
    saludo = nombre_para_comunicar_representante(bodega) or (bodega.get("nombre_comercial") or "Hola")

    if efectivo > 0:
        desglose = (
            f"💰 *TOTAL: S/ {total:.2f}*\n"
            f"📊 Tu línea: S/ {linea_disponible:.2f}\n\n"
            f"💳 Financias con Circa: *S/ {financiable:.2f}*\n"
            f"💵 Pagas en efectivo al vendedor: *S/ {efectivo:.2f}*"
        )
    else:
        desglose = (
            f"💰 *TOTAL: S/ {total:.2f}*\n"
            f"📊 Línea disponible: S/ {linea_disponible:.2f}"
        )

    return (
        f"🛒 *{saludo}, tu preventa está lista*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"{items_text}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"{desglose}\n"
        f"👤 Preventa armada por *{vendedor_nombre}*\n\n"
        f"Si todo está bien, escribe *APROBAR* para confirmar y financiar con tu línea Circa.\n"
        f"Si no quieres aprobarla, escribe *RECHAZAR*."
    )


def session_datos_aprobar_preventa(
    *,
    pedido: dict,
    link_token: str,
    total: float,
    financiable: float,
    efectivo: float,
    vendedor_nombre: str,
) -> dict[str, Any]:
    return {
        "pedido_id": pedido["id"],
        "pedido_numero": pedido.get("numero") or "",
        "link_token": link_token,
        "total": total,
        "financiable": financiable,
        "efectivo": efectivo,
        "vendedor_nombre": vendedor_nombre,
        "intentos_pin": 0,
    }


def preparar_aprobar_preventa(
    telefono_bodega: str,
    *,
    bodega: dict,
    pedido: dict,
    vendedor_nombre: str,
) -> str:
    """Deja sesión en aprobar_preventa y devuelve el texto del resumen para WhatsApp."""
    items = parse_items_json(pedido)
    total = float(pedido.get("total_pedido") or 0)
    linea = float(bodega.get("linea_disponible") or 0)
    financiable, efectivo = calc_financiable_efectivo(total, linea)
    link_token = (pedido.get("link_token") or "").lower()

    db.upsert_session(
        telefono_bodega,
        "aprobar_preventa",
        session_datos_aprobar_preventa(
            pedido=pedido,
            link_token=link_token,
            total=total,
            financiable=financiable,
            efectivo=efectivo,
            vendedor_nombre=vendedor_nombre,
        ),
        bodega["id"],
    )

    return build_preventa_propuesta_mensaje(
        bodega=bodega,
        items=items,
        total=total,
        linea_disponible=linea,
        vendedor_nombre=vendedor_nombre,
    )
