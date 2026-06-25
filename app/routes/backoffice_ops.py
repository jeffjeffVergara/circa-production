"""
Circa — Endpoint enriquecido de bodegas para operaciones.

Agrega a app/routes/backoffice.py (o como archivo separado importado en backoffice.py).
Devuelve bodegas con vendedor, supervisor, grupo, onboarding, mora, pedidos y link WA.

Uso:
  GET /api/backoffice/bodegas-ops?test=real
  GET /api/backoffice/bodegas-ops?test=real&supervisor=ACOSTA+SERPA+ANGELO+LELIS
  GET /api/backoffice/bodegas-ops?test=real&vendedor=VW168
  GET /api/backoffice/bodegas-ops?test=real&onboarding=invited
  GET /api/backoffice/bodegas-ops?test=real&enrolada=no
  GET /api/backoffice/bodegas-ops?test=real&con_pedido=no
  GET /api/backoffice/bodegas-ops?test=real&linea_sin_uso=true
  GET /api/backoffice/bodegas-ops?test=real&mora=vencido
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import Depends

from app.services import db
from app.services.backoffice_auth import get_backoffice_user
from app.services.fees import dias_atraso_desde_vencimiento, hoy_peru

logger = logging.getLogger("circa.backoffice_ops")


async def bodegas_ops_handler(
    test: Optional[str] = "real",
    search: Optional[str] = None,
    estado: Optional[str] = None,
    vendedor: Optional[str] = None,
    supervisor: Optional[str] = None,
    grupo: Optional[str] = None,
    onboarding: Optional[str] = None,
    enrolada: Optional[str] = None,
    con_pedido: Optional[str] = None,
    linea_sin_uso: Optional[str] = None,
    mora: Optional[str] = None,
    user: dict = Depends(get_backoffice_user),
):
    """Bodegas enriquecidas con vendedor, supervisor, grupo, mora, pedidos."""

    # ── 1. Cargar bodegas ────────────────────────────────
    q = db.sb.table("bodegas").select(
        "id, razon_social, nombre_comercial, representante_legal,"
        "representante_nombre_corto, telefono_whatsapp, ruc,"
        "dni_representante, solo_dni_sin_ruc, direccion_fiscal,"
        "distrito, estado, es_test, en_piloto,"
        "linea_aprobada, linea_disponible,"
        "onboarding_fase, kyc_nivel,"
        "created_at"
    )
    if test == "real":
        q = q.eq("es_test", False)
    elif test == "test":
        q = q.eq("es_test", True)
    if estado:
        q = q.eq("estado", estado)

    bodegas_raw = q.order("created_at", desc=True).limit(1000).execute().data or []
    if not bodegas_raw:
        return {"bodegas": [], "total": 0, "filtros_disponibles": _filtros_vacios()}

    bodega_ids = [b["id"] for b in bodegas_raw]
    b_map = {b["id"]: b for b in bodegas_raw}

    # ── 2. Cargar vendedores y mappings ──────────────────
    bv_rows = (
        db.sb.table("bodega_vendedores")
        .select("bodega_id, vendedor_id, rol, grupo, supervisor, dia_visita, dia_entrega, activo")
        .eq("activo", True)
        .in_("bodega_id", bodega_ids)
        .limit(2000)
        .execute().data or []
    )

    vendedor_ids = list({bv["vendedor_id"] for bv in bv_rows if bv.get("vendedor_id")})
    v_map = {}
    if vendedor_ids:
        # Cargar en chunks de 50 para evitar límites
        for i in range(0, len(vendedor_ids), 50):
            chunk = vendedor_ids[i:i+50]
            vrows = (
                db.sb.table("vendedores")
                .select("id, codigo, nombre, celular, telefono_whatsapp, activo")
                .in_("id", chunk)
                .limit(50)
                .execute().data or []
            )
            for v in vrows:
                v_map[v["id"]] = v

    # Crear lookup bodega → vendedor principal (primer mapping activo)
    bv_by_bodega: dict[str, dict] = {}
    for bv in bv_rows:
        bid = bv["bodega_id"]
        if bid not in bv_by_bodega:  # primer mapping = principal
            v = v_map.get(bv["vendedor_id"]) or {}
            bv_by_bodega[bid] = {
                "vendedor_codigo": v.get("codigo", ""),
                "vendedor_nombre": v.get("nombre", ""),
                "vendedor_telefono": v.get("telefono_whatsapp") or v.get("celular", ""),
                "supervisor": bv.get("supervisor", ""),
                "grupo": bv.get("grupo", ""),
                "rol": bv.get("rol", ""),
                "dia_visita": bv.get("dia_visita", ""),
                "dia_entrega": bv.get("dia_entrega", ""),
            }

    # ── 3. Cargar sesiones (fase bot + última actividad) ─
    sesiones_raw = (
        db.sb.table("sesiones")
        .select("bodega_id, fase, last_activity")
        .in_("bodega_id", bodega_ids)
        .limit(1000)
        .execute().data or []
    )
    ses_map = {s["bodega_id"]: s for s in sesiones_raw}

    # ── 4. Cargar pedidos (conteo + último pedido) ───────
    pedidos_raw = (
        db.sb.table("pedidos")
        .select("bodega_id, estado, created_at, monto_financiado, total_pedido,"
                "fee_monto, fecha_vencimiento, plazo_dias")
        .in_("bodega_id", bodega_ids)
        .in_("estado", ["entregado", "pagado", "recibido", "preventa_aceptada",
                        "confirmado", "en_preparacion", "despachado", "en_camino"])
        .order("created_at", desc=True)
        .limit(5000)
        .execute().data or []
    )

    ped_stats: dict[str, dict] = {}
    hoy = hoy_peru()
    for p in pedidos_raw:
        bid = p["bodega_id"]
        if bid not in ped_stats:
            ped_stats[bid] = {
                "n_pedidos": 0, "ultimo_pedido": None,
                "venta_total": 0, "financiado_total": 0,
                "saldo": 0, "dias_mora": 0, "monto_vencido": 0,
            }
        s = ped_stats[bid]
        s["n_pedidos"] += 1
        ts = p.get("created_at", "")
        if not s["ultimo_pedido"] or ts > s["ultimo_pedido"]:
            s["ultimo_pedido"] = ts
        s["venta_total"] += float(p.get("total_pedido") or 0)
        mf = float(p.get("monto_financiado") or 0)
        s["financiado_total"] += mf

        # Calcular mora para pedidos financiados no pagados
        if mf > 0 and p.get("estado") not in ("pagado",):
            fv = p.get("fecha_vencimiento")
            dias = dias_atraso_desde_vencimiento(fv, hoy) if fv else 0
            fee = float(p.get("fee_monto") or 0)
            total_deuda = mf + fee
            s["saldo"] += total_deuda
            if dias > 0:
                s["dias_mora"] = max(s["dias_mora"], dias)
                s["monto_vencido"] += total_deuda

    # ── 5. Ensamblar respuesta enriquecida ───────────────
    result = []
    for b in bodegas_raw:
        bid = b["id"]
        vdata = bv_by_bodega.get(bid, {})
        ses = ses_map.get(bid, {})
        ps = ped_stats.get(bid, {})
        tel = b.get("telefono_whatsapp", "")

        # Determinar si está "enrolada" (onboarding completado o tiene PIN)
        onb = b.get("onboarding_fase") or "invited"
        enrolada_flag = b.get("estado") == "activo"

        # Línea
        la = float(b.get("linea_aprobada") or 0)
        ld = float(b.get("linea_disponible") or 0)
        linea_usada = la - ld
        uso_pct = round((linea_usada / la) * 100) if la > 0 else 0

        # WhatsApp link
        tel_clean = tel.replace("+", "").replace(" ", "") if tel else ""
        wa_link = f"https://wa.me/{tel_clean}" if tel_clean else None

        row = {
            # Identificación
            "id": bid,
            "nombre_comercial": b.get("nombre_comercial") or b.get("razon_social") or "?",
            "razon_social": b.get("razon_social", ""),
            "representante": b.get("representante_nombre_corto") or b.get("representante_legal") or "",
            "telefono_whatsapp": tel,
            "wa_link": wa_link,
            "ruc": b.get("ruc", ""),
            "dni": b.get("dni_representante", ""),
            "distrito": b.get("distrito", ""),
            "direccion": b.get("direccion_fiscal", ""),

            # Estado y onboarding
            "estado": b.get("estado", ""),
            "onboarding_fase": onb,
            "kyc_nivel": b.get("kyc_nivel") or "ninguno",
            "enrolada": enrolada_flag,
            "es_test": b.get("es_test", False),
            "en_piloto": b.get("en_piloto", False),

            # Vendedor / Supervisor
            "vendedor_codigo": vdata.get("vendedor_codigo", ""),
            "vendedor_nombre": vdata.get("vendedor_nombre", ""),
            "vendedor_telefono": vdata.get("vendedor_telefono", ""),
            "vendedor_wa_link": f"https://wa.me/{vdata.get('vendedor_telefono', '').replace('+', '')}" if vdata.get("vendedor_telefono") else None,
            "supervisor": vdata.get("supervisor", ""),
            "grupo": vdata.get("grupo", ""),
            "rol": vdata.get("rol", ""),
            "dia_visita": vdata.get("dia_visita", ""),
            "dia_entrega": vdata.get("dia_entrega", ""),

            # Línea de crédito
            "linea_aprobada": la,
            "linea_disponible": ld,
            "linea_usada": linea_usada,
            "uso_pct": uso_pct,

            # Sesión bot
            "fase_bot": ses.get("fase") or "sin_sesion",
            "last_activity": ses.get("last_activity"),

            # Pedidos y cobranza
            "n_pedidos": ps.get("n_pedidos", 0),
            "ultimo_pedido": ps.get("ultimo_pedido"),
            "venta_total": round(ps.get("venta_total", 0), 2),
            "financiado_total": round(ps.get("financiado_total", 0), 2),
            "saldo": round(ps.get("saldo", 0), 2),
            "dias_mora": ps.get("dias_mora", 0),
            "monto_vencido": round(ps.get("monto_vencido", 0), 2),

            # Fechas
            "created_at": b.get("created_at", ""),
        }
        result.append(row)

    # ── 6. Aplicar filtros del frontend ──────────────────
    if search:
        q_lower = search.lower()
        result = [r for r in result if q_lower in (
            r["nombre_comercial"] + r["razon_social"] + r["representante"]
            + r["telefono_whatsapp"] + r["ruc"] + r["dni"]
        ).lower()]

    if vendedor:
        result = [r for r in result if r["vendedor_codigo"] == vendedor]
    if supervisor:
        result = [r for r in result if supervisor.lower() in r["supervisor"].lower()]
    if grupo:
        result = [r for r in result if grupo.lower() in r["grupo"].lower()]
    if onboarding:
        result = [r for r in result if r["onboarding_fase"] == onboarding]
    if enrolada == "si":
        result = [r for r in result if r["enrolada"]]
    elif enrolada == "no":
        result = [r for r in result if not r["enrolada"]]
    if con_pedido == "si":
        result = [r for r in result if r["n_pedidos"] > 0]
    elif con_pedido == "no":
        result = [r for r in result if r["n_pedidos"] == 0]
    if linea_sin_uso == "true":
        result = [r for r in result if r["linea_aprobada"] > 0 and r["linea_usada"] == 0]
    if mora == "vencido":
        result = [r for r in result if r["dias_mora"] > 0]
    elif mora == "por_vencer":
        result = [r for r in result if r["saldo"] > 0 and r["dias_mora"] == 0]
    elif mora == "sin_deuda":
        result = [r for r in result if r["saldo"] == 0]

    # ── 7. Generar opciones de filtros (para dropdowns) ──
    todos_vendedores = sorted({r["vendedor_codigo"] for r in result if r["vendedor_codigo"]})
    todos_supervisores = sorted({r["supervisor"] for r in result if r["supervisor"]})
    todos_grupos = sorted({r["grupo"] for r in result if r["grupo"]})
    todos_onboarding = sorted({r["onboarding_fase"] for r in result})
    todos_estados = sorted({r["estado"] for r in result if r["estado"]})

    # ── 8. KPIs del conjunto filtrado ────────────────────
    total = len(result)
    activas = sum(1 for r in result if r["estado"] == "activo")
    enroladas = sum(1 for r in result if r["enrolada"])
    pendientes = total - enroladas
    con_linea = sum(1 for r in result if r["linea_aprobada"] > 0 and r["linea_usada"] > 0 and r["enrolada"])
    sin_pedido_val = sum(1 for r in result if r["n_pedidos"] == 0)
    en_mora = sum(1 for r in result if r["dias_mora"] > 0)
    monto_mora = round(sum(r["monto_vencido"] for r in result), 2)
    linea_sin_uso_cnt = sum(1 for r in result if r["linea_aprobada"] > 0 and r["linea_usada"] == 0)

    return {
        "bodegas": result,
        "total": total,
        "kpis": {
            "total": total,
            "activas": activas,
            "enroladas": enroladas,
            "pendientes_enrolamiento": pendientes,
            "usando_linea": con_linea,
            "linea_sin_uso": linea_sin_uso_cnt,
            "sin_pedido": sin_pedido_val,
            "en_mora": en_mora,
            "monto_mora": monto_mora,
        },
        "filtros_disponibles": {
            "vendedores": todos_vendedores,
            "supervisores": todos_supervisores,
            "grupos": todos_grupos,
            "onboarding_fases": todos_onboarding,
            "estados": todos_estados,
        },
    }


def _filtros_vacios():
    return {
        "vendedores": [], "supervisores": [], "grupos": [],
        "onboarding_fases": [], "estados": [],
    }


# ── Registrar en el router de backoffice ─────────────────
# Agregar esto al final de app/routes/backoffice.py:
#
# from app.routes.backoffice_ops import bodegas_ops_handler
# router.get("/bodegas-ops")(bodegas_ops_handler)
#
# O si prefieres en el mismo archivo, copia la función
# y agrega el decorador:
# @router.get("/bodegas-ops")
