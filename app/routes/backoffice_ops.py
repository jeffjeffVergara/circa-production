"""
Circa — Endpoints operativos del backoffice.
Funciones: bodegas_ops_handler, marcar_pago_distribuidor_handler, gmv_handler
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from zoneinfo import ZoneInfo

from fastapi import Depends, HTTPException

from app.services import db
from app.services.backoffice_auth import get_backoffice_user
from app.services.fees import dias_atraso_desde_vencimiento, hoy_peru

logger = logging.getLogger("circa.backoffice_ops")
TZ_PERU = ZoneInfo("America/Lima")

VALID_ESTADOS = ["entregado", "pagado", "recibido", "preventa_aceptada",
                 "confirmado", "en_preparacion", "despachado", "en_camino"]


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
    q = db.sb.table("bodegas").select(
        "id, razon_social, nombre_comercial, representante_legal,"
        "representante_nombre_corto, telefono_whatsapp, ruc,"
        "dni_representante, solo_dni_sin_ruc, direccion_fiscal,"
        "distrito, estado, es_test, en_piloto,"
        "linea_aprobada, linea_disponible,"
        "onboarding_fase, kyc_nivel, created_at"
    )
    if test == "real":
        q = q.eq("es_test", False)
    elif test == "test":
        q = q.eq("es_test", True)
    if estado:
        q = q.eq("estado", estado)

    bodegas_raw = q.order("created_at", desc=True).limit(1000).execute().data or []
    if not bodegas_raw:
        return {"bodegas": [], "total": 0, "kpis": _kpis_vacios(), "filtros_disponibles": _filtros_vacios()}

    bodega_ids = [b["id"] for b in bodegas_raw]

    bv_rows = []
    for i in range(0, len(bodega_ids), 50):
        chunk = bodega_ids[i:i + 50]
        rows = db.sb.table("bodega_vendedores").select(
            "bodega_id, vendedor_id, rol, grupo, supervisor, dia_visita, dia_entrega, activo"
        ).eq("activo", True).in_("bodega_id", chunk).limit(500).execute().data or []
        bv_rows.extend(rows)

    vendedor_ids = list({bv["vendedor_id"] for bv in bv_rows if bv.get("vendedor_id")})
    v_map = {}
    for i in range(0, len(vendedor_ids), 50):
        chunk = vendedor_ids[i:i + 50]
        for v in db.sb.table("vendedores").select("id, codigo, nombre, celular, telefono_whatsapp").in_("id", chunk).limit(50).execute().data or []:
            v_map[v["id"]] = v

    bv_by_bodega = {}
    for bv in bv_rows:
        bid = bv["bodega_id"]
        if bid not in bv_by_bodega:
            v = v_map.get(bv["vendedor_id"]) or {}
            bv_by_bodega[bid] = {
                "vendedor_codigo": v.get("codigo", ""), "vendedor_nombre": v.get("nombre", ""),
                "vendedor_telefono": v.get("telefono_whatsapp") or v.get("celular", ""),
                "supervisor": bv.get("supervisor", ""), "grupo": bv.get("grupo", ""),
                "rol": bv.get("rol", ""), "dia_visita": bv.get("dia_visita", ""),
                "dia_entrega": bv.get("dia_entrega", ""),
            }

    ses_map = {}
    for i in range(0, len(bodega_ids), 50):
        chunk = bodega_ids[i:i + 50]
        for s in db.sb.table("sesiones").select("bodega_id, fase, last_activity").in_("bodega_id", chunk).limit(500).execute().data or []:
            ses_map[s["bodega_id"]] = s

    ped_stats = {}
    hoy = hoy_peru()
    for i in range(0, len(bodega_ids), 50):
        chunk = bodega_ids[i:i + 50]
        pedidos = db.sb.table("pedidos").select(
            "bodega_id, estado, created_at, monto_financiado, total_pedido, fee_monto, fecha_vencimiento"
        ).in_("bodega_id", chunk).in_("estado", VALID_ESTADOS).order("created_at", desc=True).limit(2000).execute().data or []
        for p in pedidos:
            bid = p["bodega_id"]
            if bid not in ped_stats:
                ped_stats[bid] = {"n_pedidos": 0, "ultimo_pedido": None, "venta_total": 0,
                                  "financiado_total": 0, "saldo": 0, "dias_mora": 0, "monto_vencido": 0}
            s = ped_stats[bid]
            s["n_pedidos"] += 1
            ts = p.get("created_at", "")
            if not s["ultimo_pedido"] or ts > s["ultimo_pedido"]:
                s["ultimo_pedido"] = ts
            s["venta_total"] += float(p.get("total_pedido") or 0)
            mf = float(p.get("monto_financiado") or 0)
            s["financiado_total"] += mf
            if mf > 0 and p.get("estado") != "pagado":
                fv = p.get("fecha_vencimiento")
                dias = dias_atraso_desde_vencimiento(fv, hoy) if fv else 0
                fee = float(p.get("fee_monto") or 0)
                total_deuda = mf + fee
                s["saldo"] += total_deuda
                if dias > 0:
                    s["dias_mora"] = max(s["dias_mora"], dias)
                    s["monto_vencido"] += total_deuda

    result = []
    for b in bodegas_raw:
        bid = b["id"]
        vdata = bv_by_bodega.get(bid, {})
        ses = ses_map.get(bid, {})
        ps = ped_stats.get(bid, {})
        tel = b.get("telefono_whatsapp", "")
        enrolada_flag = b.get("estado") == "activo"
        la = float(b.get("linea_aprobada") or 0)
        ld = float(b.get("linea_disponible") or 0)
        linea_usada = la - ld
        uso_pct = round((linea_usada / la) * 100) if la > 0 else 0
        tel_clean = tel.replace("+", "").replace(" ", "") if tel else ""
        vtel = vdata.get("vendedor_telefono", "")
        vtel_clean = vtel.replace("+", "").replace(" ", "") if vtel else ""
        result.append({
            "id": bid,
            "nombre_comercial": b.get("nombre_comercial") or b.get("razon_social") or "?",
            "razon_social": b.get("razon_social", ""),
            "representante": b.get("representante_nombre_corto") or b.get("representante_legal") or "",
            "telefono_whatsapp": tel, "wa_link": f"https://wa.me/{tel_clean}" if tel_clean else None,
            "ruc": b.get("ruc", ""), "dni": b.get("dni_representante", ""),
            "distrito": b.get("distrito", ""), "direccion": b.get("direccion_fiscal", ""),
            "estado": b.get("estado", ""),
            "onboarding_fase": b.get("onboarding_fase") or "invited",
            "kyc_nivel": b.get("kyc_nivel") or "ninguno",
            "enrolada": enrolada_flag,
            "es_test": b.get("es_test", False), "en_piloto": b.get("en_piloto", False),
            "vendedor_codigo": vdata.get("vendedor_codigo", ""),
            "vendedor_nombre": vdata.get("vendedor_nombre", ""),
            "vendedor_telefono": vtel,
            "vendedor_wa_link": f"https://wa.me/{vtel_clean}" if vtel_clean else None,
            "supervisor": vdata.get("supervisor", ""), "grupo": vdata.get("grupo", ""),
            "rol": vdata.get("rol", ""),
            "dia_visita": vdata.get("dia_visita", ""), "dia_entrega": vdata.get("dia_entrega", ""),
            "linea_aprobada": la, "linea_disponible": ld, "linea_usada": linea_usada, "uso_pct": uso_pct,
            "fase_bot": ses.get("fase") or "sin_sesion", "last_activity": ses.get("last_activity"),
            "n_pedidos": ps.get("n_pedidos", 0), "ultimo_pedido": ps.get("ultimo_pedido"),
            "venta_total": round(ps.get("venta_total", 0), 2),
            "financiado_total": round(ps.get("financiado_total", 0), 2),
            "saldo": round(ps.get("saldo", 0), 2), "dias_mora": ps.get("dias_mora", 0),
            "monto_vencido": round(ps.get("monto_vencido", 0), 2),
            "created_at": b.get("created_at", ""),
        })

    if search:
        q_lower = search.lower()
        result = [r for r in result if q_lower in ((r.get("nombre_comercial") or "") + (r.get("razon_social") or "") + (r.get("representante") or "") + (r.get("telefono_whatsapp") or "") + (r.get("ruc") or "") + (r.get("dni") or "")).lower()]
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
        result = [r for r in result if r["linea_aprobada"] > 0 and r["linea_usada"] == 0 and r["enrolada"]]
    if mora == "vencido":
        result = [r for r in result if r["dias_mora"] > 0]
    elif mora == "por_vencer":
        result = [r for r in result if r["saldo"] > 0 and r["dias_mora"] == 0]
    elif mora == "sin_deuda":
        result = [r for r in result if r["saldo"] == 0]

    total = len(result)
    activas = sum(1 for r in result if r["estado"] == "activo")
    enroladas_cnt = sum(1 for r in result if r["enrolada"])
    return {
        "bodegas": result, "total": total,
        "kpis": {
            "total": total, "activas": activas, "enroladas": enroladas_cnt,
            "pendientes_enrolamiento": total - enroladas_cnt,
            "usando_linea": sum(1 for r in result if r["linea_usada"] > 0 and r["enrolada"]),
            "linea_sin_uso": sum(1 for r in result if r["linea_aprobada"] > 0 and r["linea_usada"] == 0 and r["enrolada"]),
            "sin_pedido": sum(1 for r in result if r["n_pedidos"] == 0),
            "en_mora": sum(1 for r in result if r["dias_mora"] > 0),
            "monto_mora": round(sum(r["monto_vencido"] for r in result), 2),
        },
        "filtros_disponibles": {
            "vendedores": sorted({r["vendedor_codigo"] for r in result if r["vendedor_codigo"]}),
            "supervisores": sorted({r["supervisor"] for r in result if r["supervisor"]}),
            "grupos": sorted({r["grupo"] for r in result if r["grupo"]}),
        },
    }


def _filtros_vacios():
    return {"vendedores": [], "supervisores": [], "grupos": []}

def _kpis_vacios():
    return {"total": 0, "activas": 0, "enroladas": 0, "pendientes_enrolamiento": 0,
            "usando_linea": 0, "linea_sin_uso": 0, "sin_pedido": 0, "en_mora": 0, "monto_mora": 0}


async def marcar_pago_distribuidor_handler(
    pedido_id: str,
    user: dict = Depends(get_backoffice_user),
):
    rows = db.sb.table("pedidos").select("id,estado,monto_financiado,circa_pagado_dist_at").eq("id", pedido_id).limit(1).execute().data
    if not rows:
        raise HTTPException(status_code=404, detail="Pedido no encontrado")
    p = rows[0]
    if p.get("circa_pagado_dist_at"):
        raise HTTPException(status_code=400, detail="Ya marcado como pagado")
    if float(p.get("monto_financiado") or 0) <= 0:
        raise HTTPException(status_code=400, detail="Sin monto financiado")
    ahora = datetime.now(timezone.utc).isoformat()
    db.sb.table("pedidos").update({
        "circa_pagado_dist_at": ahora,
        "circa_pagado_dist_por": user.get("email", ""),
    }).eq("id", pedido_id).execute()
    return {"ok": True, "pedido_id": pedido_id, "pagado_at": ahora}


async def gmv_handler(
    test: str = "real",
    periodo: str = "mes",
    user: dict = Depends(get_backoffice_user),
):
    ahora = datetime.now(TZ_PERU)
    if periodo == "mes":
        desde = ahora.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        label = ahora.strftime("%B %Y").capitalize()
    elif periodo == "semana":
        dow = ahora.weekday()
        desde = (ahora - timedelta(days=dow)).replace(hour=0, minute=0, second=0, microsecond=0)
        label = f"Semana del {desde.strftime('%d/%m')}"
    else:
        desde = None
        label = "Acumulado total"

    q = db.sb.table("pedidos").select(
        "numero,total_pedido,monto_financiado,monto_contado,fee_monto,"
        "estado,created_at,bodega_id,circa_pagado_dist_at"
    ).in_("estado", VALID_ESTADOS)
    if desde:
        q = q.gte("created_at", desde.isoformat())

    pedidos = q.order("created_at", desc=True).limit(5000).execute().data or []
    if test == "real":
        pedidos = [p for p in pedidos if not (p.get("numero") or "").startswith("TEST")]
    elif test == "test":
        pedidos = [p for p in pedidos if (p.get("numero") or "").startswith("TEST")]

    gmv_total = 0.0; financiado = 0.0; contado = 0.0; fee_total = 0.0
    n_pedidos = 0; n_financiados = 0; bodegas_set = set(); pago_dist_pendiente = 0.0
    semanas = {}

    for p in pedidos:
        tp = float(p.get("total_pedido") or 0)
        mf = float(p.get("monto_financiado") or 0)
        mc = float(p.get("monto_contado") or 0)
        fee = float(p.get("fee_monto") or 0)
        gmv_total += tp; financiado += mf; contado += mc; fee_total += fee
        n_pedidos += 1
        if mf > 0: n_financiados += 1
        bodegas_set.add(p.get("bodega_id"))
        if mf > 0 and not p.get("circa_pagado_dist_at"):
            pago_dist_pendiente += mf
        ca = p.get("created_at", "")
        if ca:
            try:
                dt = datetime.fromisoformat(ca.replace("Z", "+00:00"))
                ws = (dt - timedelta(days=dt.weekday())).strftime("%Y-%m-%d")
                if ws not in semanas:
                    semanas[ws] = {"semana": ws, "gmv": 0, "financiado": 0, "contado": 0, "pedidos": 0}
                semanas[ws]["gmv"] += tp; semanas[ws]["financiado"] += mf
                semanas[ws]["contado"] += mc; semanas[ws]["pedidos"] += 1
            except Exception:
                pass

    ticket_prom = round(gmv_total / n_pedidos, 2) if n_pedidos > 0 else 0
    pct_fin = round((financiado / gmv_total) * 100, 1) if gmv_total > 0 else 0
    sem_sorted = sorted(semanas.values(), key=lambda s: s["semana"], reverse=True)
    for s in sem_sorted:
        s["gmv"] = round(s["gmv"], 2); s["financiado"] = round(s["financiado"], 2); s["contado"] = round(s["contado"], 2)

    return {
        "periodo": periodo, "label": label,
        "gmv_total": round(gmv_total, 2), "financiado": round(financiado, 2),
        "contado": round(contado, 2), "fee_total": round(fee_total, 2),
        "n_pedidos": n_pedidos, "n_financiados": n_financiados,
        "n_bodegas": len(bodegas_set), "ticket_promedio": ticket_prom,
        "pct_financiado": pct_fin, "pago_dist_pendiente": round(pago_dist_pendiente, 2),
        "semanas": sem_sorted,
    }
