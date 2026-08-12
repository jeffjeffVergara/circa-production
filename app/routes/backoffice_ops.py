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
    fase_bot: Optional[str] = None,
    tipo: Optional[str] = None,
    linea_usando: Optional[str] = None,
    page: int = 1,
    page_size: int = 50,
    user: dict = Depends(get_backoffice_user),
):
    """Lista de bodegas: filtra, pagina y cuenta del lado del servidor sobre la vista v_bodegas_ops."""
    try:
        page = max(1, int(page))
    except (TypeError, ValueError):
        page = 1
    try:
        page_size = min(200, max(10, int(page_size)))
    except (TypeError, ValueError):
        page_size = 50

    def _apply(qb):
        if test == "real":
            qb = qb.eq("es_test", False)
        elif test == "test":
            qb = qb.eq("es_test", True)
        if estado:
            qb = qb.eq("estado", estado)
        if vendedor:
            qb = qb.eq("vendedor_codigo", vendedor)
        if supervisor:
            qb = qb.ilike("supervisor", f"%{supervisor}%")
        if grupo:
            qb = qb.ilike("grupo", f"%{grupo}%")
        if tipo in ("bodega", "mercado"):
            qb = qb.eq("tipo", tipo)
        if onboarding:
            qb = qb.eq("onboarding_fase", onboarding)
        if enrolada == "si":
            qb = qb.eq("enrolada", True)
        elif enrolada == "no":
            qb = qb.eq("enrolada", False)
        if con_pedido == "si":
            qb = qb.gt("n_pedidos", 0)
        elif con_pedido == "no":
            qb = qb.eq("n_pedidos", 0)
        if mora == "vencido":
            qb = qb.gt("dias_mora", 0)
        elif mora == "por_vencer":
            qb = qb.gt("saldo", 0).eq("dias_mora", 0)
        elif mora == "sin_deuda":
            qb = qb.eq("saldo", 0)
        if fase_bot:
            qb = qb.eq("fase_bot", fase_bot)
        if linea_usando == "si":
            qb = qb.gt("linea_usada", 0).eq("enrolada", True)
        elif linea_usando == "no":
            qb = qb.gt("linea_aprobada", 0).eq("linea_usada", 0).eq("enrolada", True)
        if linea_sin_uso == "true":
            qb = qb.gt("linea_aprobada", 0).eq("linea_usada", 0).eq("enrolada", True)
        if search:
            term = search.replace("%", "").replace(",", " ").strip()
            if term:
                pat = f"*{term}*"
                qb = qb.or_(
                    f"razon_social.ilike.{pat},nombre_comercial.ilike.{pat},"
                    f"representante_legal.ilike.{pat},representante_nombre_corto.ilike.{pat},"
                    f"telefono_whatsapp.ilike.{pat},ruc.ilike.{pat},dni_representante.ilike.{pat}"
                )
        return qb

    def _f(v):
        try:
            return float(v or 0)
        except (TypeError, ValueError):
            return 0.0

    # Set filtrado completo (columnas livianas) para KPIs y opciones de filtro
    agg_cols = ("estado,enrolada,linea_aprobada,linea_usada,n_pedidos,dias_mora,"
                "monto_vencido,saldo,vendedor_codigo,supervisor,grupo")
    # Total y KPIs con count='exact' (ignora el tope de 1000 filas/req de PostgREST)
    def _count(cond=None):
        qb = _apply(db.sb.table("v_bodegas_ops").select("id", count="exact"))
        if cond:
            qb = cond(qb)
        return qb.limit(1).execute().count or 0

    total = _count()
    if total == 0:
        return {"bodegas": [], "total": 0, "page": page, "page_size": page_size,
                "total_pages": 0, "kpis": _kpis_vacios(), "filtros_disponibles": _filtros_vacios()}

    enroladas_cnt = _count(lambda q: q.eq("enrolada", True))
    mora_rows = _apply(db.sb.table("v_bodegas_ops").select("monto_vencido").gt("dias_mora", 0)).range(0, 9999).execute().data or []
    kpis = {
        "total": total,
        "activas": _count(lambda q: q.eq("estado", "activo")),
        "enroladas": enroladas_cnt,
        "pendientes_enrolamiento": total - enroladas_cnt,
        "usando_linea": _count(lambda q: q.gt("linea_usada", 0).eq("enrolada", True)),
        "linea_sin_uso": _count(lambda q: q.gt("linea_aprobada", 0).eq("linea_usada", 0).eq("enrolada", True)),
        "sin_pedido": _count(lambda q: q.eq("n_pedidos", 0)),
        "en_mora": _count(lambda q: q.gt("dias_mora", 0)),
        "monto_mora": round(sum(_f(r.get("monto_vencido")) for r in mora_rows), 2),
    }
    # Opciones de filtro: una muestra basta (cada vendedor/supervisor tiene muchas bodegas)
    sample = _apply(db.sb.table("v_bodegas_ops").select("vendedor_codigo,supervisor,grupo")).range(0, 999).execute().data or []
    filtros = {
        "vendedores": sorted({r["vendedor_codigo"] for r in sample if r.get("vendedor_codigo")}),
        "supervisores": sorted({r["supervisor"] for r in sample if r.get("supervisor")}),
        "grupos": sorted({r["grupo"] for r in sample if r.get("grupo")}),
    }

    # Página
    offset = (page - 1) * page_size
    page_rows = (_apply(db.sb.table("v_bodegas_ops").select("*"))
                 .order("created_at", desc=True)
                 .range(offset, offset + page_size - 1).execute().data or [])

    result = []
    for b in page_rows:
        tel = b.get("telefono_whatsapp") or ""
        tel_clean = tel.replace("+", "").replace(" ", "") if tel else ""
        vtel = b.get("vendedor_telefono") or ""
        vtel_clean = vtel.replace("+", "").replace(" ", "") if vtel else ""
        la = _f(b.get("linea_aprobada")); ld = _f(b.get("linea_disponible"))
        lusada = _f(b.get("linea_usada"))
        result.append({
            "id": b.get("id"),
            "nombre_comercial": b.get("nombre_comercial") or b.get("razon_social") or "?",
            "razon_social": b.get("razon_social", ""),
            "representante": b.get("representante_nombre_corto") or b.get("representante_legal") or "",
            "telefono_whatsapp": tel, "wa_link": f"https://wa.me/{tel_clean}" if tel_clean else None,
            "ruc": b.get("ruc", ""), "dni": b.get("dni_representante", ""),
            "distrito": b.get("distrito", ""), "direccion": b.get("direccion_fiscal", ""),
            "estado": b.get("estado", ""),
            "onboarding_fase": b.get("onboarding_fase") or "invited",
            "kyc_nivel": b.get("kyc_nivel") or "ninguno",
            "enrolada": bool(b.get("enrolada")),
            "es_test": b.get("es_test", False), "en_piloto": b.get("en_piloto", False),
            "vendedor_codigo": b.get("vendedor_codigo") or "",
            "vendedor_nombre": b.get("vendedor_nombre") or "",
            "vendedor_telefono": vtel,
            "vendedor_wa_link": f"https://wa.me/{vtel_clean}" if vtel_clean else None,
            "supervisor": b.get("supervisor") or "", "grupo": b.get("grupo") or "",
            "rol": b.get("rol") or "",
            "dia_visita": b.get("dia_visita") or "", "dia_entrega": b.get("dia_entrega") or "",
            "linea_aprobada": la, "linea_disponible": ld, "linea_usada": lusada,
            "uso_pct": round((lusada / la) * 100) if la > 0 else 0,
            "fase_bot": b.get("fase_bot") or "sin_sesion", "last_activity": b.get("last_activity"),
            "n_pedidos": b.get("n_pedidos", 0) or 0, "ultimo_pedido": b.get("ultimo_pedido"),
            "venta_total": round(_f(b.get("venta_total")), 2),
            "financiado_total": round(_f(b.get("financiado_total")), 2),
            "saldo": round(_f(b.get("saldo")), 2), "dias_mora": b.get("dias_mora", 0) or 0,
            "monto_vencido": round(_f(b.get("monto_vencido")), 2),
            "created_at": b.get("created_at", ""),
            "tipo": b.get("tipo") or "bodega",
        })

    total_pages = (total + page_size - 1) // page_size
    return {
        "bodegas": result, "total": total,
        "page": page, "page_size": page_size, "total_pages": total_pages,
        "kpis": kpis, "filtros_disponibles": filtros,
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
    # Filter by bodega es_test, not pedido prefix
    if test in ("real", "test"):
        test_bids = set()
        all_bids = list({p.get("bodega_id") for p in pedidos if p.get("bodega_id")})
        for i in range(0, len(all_bids), 50):
            chunk = all_bids[i:i+50]
            for b in db.sb.table("bodegas").select("id,es_test").in_("id", chunk).limit(50).execute().data or []:
                if b.get("es_test"): test_bids.add(b["id"])
        if test == "real":
            pedidos = [p for p in pedidos if p.get("bodega_id") not in test_bids]
        else:
            pedidos = [p for p in pedidos if p.get("bodega_id") in test_bids]

    gmv_total = 0.0; financiado = 0.0; contado = 0.0; fee_total = 0.0
    n_pedidos = 0; n_financiados = 0; bodegas_set = set(); pago_dist_pendiente = 0.0
    semanas = {}
    bodegas_gmv = {}

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
        bid = p.get("bodega_id") or ""
        if bid not in bodegas_gmv:
            bodegas_gmv[bid] = {"bodega_id": bid, "nombre": "", "gmv": 0, "financiado": 0, "contado": 0, "pedidos": 0}
        bodegas_gmv[bid]["gmv"] += tp
        bodegas_gmv[bid]["financiado"] += mf
        bodegas_gmv[bid]["contado"] += mc
        bodegas_gmv[bid]["pedidos"] += 1
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

    bid_list = list(bodegas_gmv.keys())
    for i in range(0, len(bid_list), 50):
        chunk = bid_list[i:i+50]
        for b in db.sb.table("bodegas").select("id,nombre_comercial,razon_social").in_("id", chunk).limit(50).execute().data or []:
            if b["id"] in bodegas_gmv:
                bodegas_gmv[b["id"]]["nombre"] = b.get("nombre_comercial") or b.get("razon_social") or "?"
    bodegas_ranked = sorted(bodegas_gmv.values(), key=lambda x: x["gmv"], reverse=True)
    for bg in bodegas_ranked:
        bg["gmv"] = round(bg["gmv"], 2)
        bg["financiado"] = round(bg["financiado"], 2)
        bg["contado"] = round(bg["contado"], 2)

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
        "bodegas": bodegas_ranked,
    }
