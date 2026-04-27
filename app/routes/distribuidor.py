"""
Distribuidor Portal API — Circa
"""
from fastapi import APIRouter, HTTPException, Header, Depends, UploadFile, File
from pydantic import BaseModel
from typing import Optional
import os, httpx
from datetime import datetime, timezone

router = APIRouter(prefix="/api/distribuidor", tags=["distribuidor"])

SUPABASE_URL = os.getenv("SUPABASE_URL", "https://rhxqcoijzgqlecpdfhde.supabase.co")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_KEY", os.getenv("SUPABASE_KEY", ""))

def _sb_headers():
    return {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}",
            "Content-Type": "application/json", "Prefer": "return=representation"}

def _sb_get(path, params=None):
    r = httpx.get(f"{SUPABASE_URL}/rest/v1/{path}", headers=_sb_headers(), params=params or {}, timeout=15)
    if r.status_code >= 400:
        import logging
        logging.getLogger("circa").error(f"Supabase error {r.status_code}: {r.text}")
        r.raise_for_status()
    return r.json()

def _sb_patch(path, data, params=None):
    r = httpx.patch(f"{SUPABASE_URL}/rest/v1/{path}", headers=_sb_headers(), json=data, params=params or {}, timeout=15)
    r.raise_for_status()
    return r.json()

async def verify_distribuidor(x_api_token: str = Header(..., alias="X-API-Token")):
    rows = _sb_get("distribuidores", {"select": "*", "api_token": f"eq.{x_api_token}"})
    if not rows:
        raise HTTPException(status_code=401, detail="Token invalido")
    return rows[0]

STATUS_FLOW = {"confirmado":"recibido","recibido":"en_preparacion","en_preparacion":"despachado","despachado":"en_camino","en_camino":"entregado"}
STATUS_LABELS = {"confirmado":"Nuevo","recibido":"Recibido","en_preparacion":"En Preparacion","despachado":"Despachado","en_camino":"En Camino","entregado":"Entregado","pagado":"Pagado"}

WA_MESSAGES = {
    "recibido": "✅ *Pedido {numero} recibido*\n{distribuidor} confirmo que recibio tu pedido.",
    "en_preparacion": "📦 *Pedido {numero} en preparacion*\n{distribuidor} esta armando tu pedido.",
    "despachado": "🚚 *Pedido {numero} despachado*\n{distribuidor} despacho tu pedido. Salio del almacen.",
    "en_camino": "🚚 *Pedido {numero} en camino*\nTu pedido va camino a tu bodega.",
    "entregado": "🎉 *Pedido {numero} entregado*\nTu pedido fue entregado en tu bodega. Gracias por comprar con Circa!",
}

META_TOKEN = os.getenv("META_ACCESS_TOKEN", "")
PHONE_NUMBER_ID = os.getenv("META_PHONE_NUMBER_ID", "1076586305533033")

def _send_wa_text(to, text):
    if not META_TOKEN: return
    try:
        httpx.post(f"https://graph.facebook.com/v23.0/{PHONE_NUMBER_ID}/messages",
            headers={"Authorization": f"Bearer {META_TOKEN}", "Content-Type": "application/json"},
            json={"messaging_product":"whatsapp","to":to,"type":"text","text":{"body":text}}, timeout=15)
    except Exception as e:
        print(f"[WA notify error] {e}")

class StatusUpdate(BaseModel):
    nuevo_estado: str

@router.get("/pedidos")
async def list_pedidos(estado: Optional[str] = None, dist: dict = Depends(verify_distribuidor)):
    params = {"select":"*","distribuidor_id":f"eq.{dist['id']}","order":"created_at.desc"}
    if estado: params["estado"] = f"eq.{estado}"
    pedidos = _sb_get("pedidos", params)
    # Fetch bodega data separately
    bodega_ids = list(set(p.get("bodega_id","") for p in pedidos if p.get("bodega_id")))
    bodegas_map = {}
    for bid in bodega_ids:
        try:
            rows = _sb_get("bodegas", {"select":"id,nombre_comercial,telefono_whatsapp,ruc,direccion_fiscal","id":f"eq.{bid}"})
            if rows: bodegas_map[bid] = rows[0]
        except: pass
    for p in pedidos:
        p["bodegas"] = bodegas_map.get(p.get("bodega_id"), {})
        if "items_json" in p and "items" not in p:
            p["items"] = p["items_json"]
    return {"pedidos": pedidos, "distribuidor": dist["nombre_comercial"]}

@router.get("/pedidos/{pedido_id}")
async def get_pedido(pedido_id: str, dist: dict = Depends(verify_distribuidor)):
    rows = _sb_get("pedidos", {"select":"*","id":f"eq.{pedido_id}","distribuidor_id":f"eq.{dist['id']}"})
    if not rows: raise HTTPException(status_code=404, detail="Pedido no encontrado")
    return rows[0]

@router.post("/pedidos/{pedido_id}/status")
async def update_status(pedido_id: str, body: StatusUpdate, dist: dict = Depends(verify_distribuidor)):
    rows = _sb_get("pedidos", {"select":"*","id":f"eq.{pedido_id}","distribuidor_id":f"eq.{dist['id']}"})
    if not rows: raise HTTPException(status_code=404, detail="Pedido no encontrado")
    pedido = rows[0]
    # Fetch bodega for notification
    try:
        b_rows = _sb_get("bodegas", {"select":"nombre_comercial,telefono_whatsapp","id":f"eq.{pedido.get('bodega_id','')}"})
        pedido["bodegas"] = b_rows[0] if b_rows else {}
    except: pedido["bodegas"] = {}
    current = pedido["estado"]
    nuevo = body.nuevo_estado
    if nuevo != STATUS_FLOW.get(current):
        raise HTTPException(status_code=400, detail=f"No se puede pasar de '{current}' a '{nuevo}'. Siguiente: '{STATUS_FLOW.get(current)}'")
    _sb_patch("pedidos", {"estado": nuevo, f"fecha_{nuevo}": datetime.now(timezone.utc).isoformat()}, {"id": f"eq.{pedido_id}"})
    bodega = pedido.get("bodegas") or {}
    tel = bodega.get("telefono_whatsapp","")
    if tel and nuevo in WA_MESSAGES:
        _send_wa_text(tel, WA_MESSAGES[nuevo].format(numero=pedido.get("numero",pedido_id[:8]), distribuidor=dist["nombre_comercial"]))
    # If entregado, send payment reminder
    if nuevo == "entregado":
        # Calcular fecha_vencimiento desde entrega
        try:
            ped_fv = _sb_get("pedidos", {"select":"plazo_dias","id":f"eq.{pedido_id}"})[0]
            plazo_d = ped_fv.get("plazo_dias") or 7
            from datetime import timedelta as td
            fv = (datetime.now(timezone.utc) + td(days=plazo_d)).strftime("%Y-%m-%d")
            _sb_patch("pedidos", {"fecha_vencimiento": fv}, {"id": f"eq.{pedido_id}"})
            _sb_patch("pagos", {"fecha_vencimiento": fv}, {"pedido_id": f"eq.{pedido_id}"})
        except Exception as efv:
            import logging
            logging.getLogger("circa").error(f"fecha_vencimiento calc error: {efv}")
        try:
            ped = _sb_get("pedidos", {"select":"*","id":f"eq.{pedido_id}"})[0]
            monto_fin = ped.get("monto_financiado") or 0
            fee = ped.get("fee_monto") or 0
            total_credito = round(monto_fin + fee, 2)
            plazo = ped.get("plazo_dias") or 7
            venc = ped.get("fecha_vencimiento") or ""
            if not venc and ped.get("created_at"):
                from datetime import timedelta
                created = datetime.fromisoformat(ped["created_at"].replace("Z","+00:00"))
                venc = (created + timedelta(days=plazo)).strftime("%d/%m/%Y")
            num = ped.get("numero", "")
            if tel and monto_fin > 0:
                reminder = (
                    f"\U0001f4b3 *Recordatorio de pago*\n"
                    f"━━━━━━━━━━━━━━━━━━\n\n"
                    f"Pedido: *{num}*\n"
                    f"Monto financiado: S/{monto_fin:.2f}\n"
                    f"Fee: S/{fee:.2f}\n"
                    f"*Total a pagar: S/{total_credito:.2f}*\n\n"
                    f"Vence: *{venc}*\n"
                    f"Plazo: {plazo} dias\n\n"
                    f"━━━━━━━━━━━━━━━━━━\n"
                    f"Paga por Yape o Plin al:\n"
                    f"\U0001f4f1 *986311567*\n"
                    f"\U0001f464 PALI SAC\n\n"
                    f"Despues de pagar, escribe *YA PAGUE* en este chat."
                )
                _send_wa_text(tel, reminder)
                # Send payment reminder card
                try:
                    from app.services.cards import generate_payment_reminder_card
                    import tempfile
                    venc_str = venc if isinstance(venc, str) else str(venc)
                    card_bytes = generate_payment_reminder_card(num, monto_fin, fee, total_credito, plazo, venc_str)
                    tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
                    tmp.write(card_bytes)
                    tmp.close()
                    upload_r = httpx.post(
                        f"https://graph.facebook.com/v23.0/{PHONE_NUMBER_ID}/media",
                        headers={"Authorization": f"Bearer {META_TOKEN}"},
                        files={"file": ("reminder.png", open(tmp.name, "rb"), "image/png")},
                        data={"messaging_product": "whatsapp", "type": "image/png"},
                        timeout=30)
                    media_id = upload_r.json().get("id")
                    if media_id:
                        httpx.post(f"https://graph.facebook.com/v23.0/{PHONE_NUMBER_ID}/messages",
                            headers={"Authorization": f"Bearer {META_TOKEN}", "Content-Type": "application/json"},
                            json={"messaging_product": "whatsapp", "to": tel, "type": "image",
                                  "image": {"id": media_id}}, timeout=15)
                    import os; os.unlink(tmp.name)
                except Exception as card_e:
                    import logging
                    logging.getLogger("circa").error(f"Reminder card error: {card_e}")
        except Exception as e:
            import logging
            logging.getLogger("circa").error(f"Payment reminder error: {e}")
    return {"ok":True,"pedido_id":pedido_id,"estado_anterior":current,"estado_nuevo":nuevo,"notificado":bool(tel)}

@router.post("/pedidos/{pedido_id}/facturar")
async def preparar_factura(pedido_id: str, dist: dict = Depends(verify_distribuidor)):
    rows = _sb_get("pedidos", {"select":"*","id":f"eq.{pedido_id}","distribuidor_id":f"eq.{dist['id']}"})
    if not rows: raise HTTPException(status_code=404, detail="Pedido no encontrado")
    pedido = rows[0]
    try:
        b_rows = _sb_get("bodegas", {"select":"nombre_comercial,telefono_whatsapp,ruc,direccion,razon_social","id":f"eq.{pedido.get('bodega_id','')}"})
        pedido["bodegas"] = b_rows[0] if b_rows else {}
    except: pedido["bodegas"] = {}
    if pedido["estado"] not in ("despachado","en_camino","entregado"):
        raise HTTPException(status_code=400, detail="Solo se puede facturar pedidos despachados o entregados")
    bodega = pedido.get("bodegas") or {}
    items = pedido.get("items_json", pedido.get("items", []))
    lineas, subtotal = [], 0
    for i, item in enumerate(items, 1):
        pu = item.get("precio_unitario", item.get("precio", 0))
        cant = item.get("cantidad", 1)
        vv = pu * cant
        igv = round(vv * 0.18, 2)
        lineas.append({"numero":i,"codigo":item.get("codigo",f"PROD-{i:03d}"),"descripcion":item.get("nombre",item.get("producto","")),"cantidad":cant,"unidad_medida":item.get("unidad","NIU"),"precio_unitario":pu,"valor_venta":round(vv,2),"igv":igv,"precio_venta":round(vv+igv,2)})
        subtotal += vv
    igv_total = round(subtotal * 0.18, 2)
    factura = {"tipo_documento":"01","serie":dist.get("serie_factura","F001"),
        "emisor":{"ruc":dist.get("ruc",""),"razon_social":dist.get("razon_social",dist["nombre_comercial"]),"direccion":dist.get("direccion","")},
        "receptor":{"ruc":bodega.get("ruc",""),"razon_social":bodega.get("razon_social",bodega.get("nombre_comercial","")),"direccion":bodega.get("direccion","")},
        "fecha_emision":datetime.now(timezone.utc).strftime("%Y-%m-%d"),"moneda":"PEN","items":lineas,
        "subtotal":round(subtotal,2),"igv":igv_total,"total":round(subtotal+igv_total,2),
        "pedido_circa":pedido.get("numero",""),"observacion":f"Pedido Circa {pedido.get('numero','')}"}
    _sb_patch("pedidos", {"facturado":True,"fecha_facturado":datetime.now(timezone.utc).isoformat()}, {"id":f"eq.{pedido_id}"})
    return {"factura": factura}

@router.get("/conciliacion")
async def conciliacion(fecha: Optional[str] = None, dist: dict = Depends(verify_distribuidor)):
    """Daily reconciliation: how much Circa owes the distributor."""
    params = {"select":"*","distribuidor_id":f"eq.{dist['id']}","estado":"in.(confirmado,recibido,en_preparacion,despachado,en_camino,entregado)"}
    pedidos = _sb_get("pedidos", params)
    total_productos = 0
    total_financiado = 0
    total_contado = 0
    total_fee_circa = 0
    desglose = []
    for p in pedidos:
        mp = p.get("monto_productos") or 0
        mf = p.get("monto_financiado") or 0
        mc = p.get("monto_contado") or 0
        fee = p.get("fee_monto") or 0
        total_productos += mp
        total_financiado += mf
        total_contado += mc
        total_fee_circa += fee
        desglose.append({
            "numero": p.get("numero",""),
            "estado": p.get("estado",""),
            "monto_productos": round(mp,2),
            "bodega_paga_contado": round(mc,2),
            "circa_financia": round(mf,2),
            "fee_circa": round(fee,2),
            "circa_paga_distribuidor": round(mf,2),
        })
    return {
        "distribuidor": dist["nombre_comercial"],
        "resumen": {
            "total_productos": round(total_productos,2),
            "total_bodega_contado": round(total_contado,2),
            "total_circa_financia": round(total_financiado,2),
            "circa_debe_distribuidor": round(total_financiado,2),
            "total_fee_circa": round(total_fee_circa,2),
            "pedidos_count": len(pedidos),
        },
        "desglose": desglose,
    }


@router.post("/pedidos/{pedido_id}/sustento")
async def upload_sustento(pedido_id: str, file: UploadFile = File(...), dist: dict = Depends(verify_distribuidor)):
    """Upload delivery proof (signed guide, invoice, photo)."""
    rows = _sb_get("pedidos", {"select":"id,estado","id":f"eq.{pedido_id}","distribuidor_id":f"eq.{dist['id']}"})
    if not rows:
        raise HTTPException(status_code=404, detail="Pedido no encontrado")
    if rows[0]["estado"] not in ("despachado","en_camino","entregado"):
        raise HTTPException(status_code=400, detail="Solo se puede subir sustento para pedidos despachados o entregados")
    content = await file.read()
    import base64
    ext = file.filename.split(".")[-1] if "." in file.filename else "jpg"
    # Upload to Supabase Storage
    storage_path = f"sustentos/{pedido_id}.{ext}"
    try:
        upload_url = f"{SUPABASE_URL}/storage/v1/object/sustentos/{storage_path}"
        r = httpx.post(upload_url, headers={
            "apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}",
            "Content-Type": file.content_type or "application/octet-stream",
            "x-upsert": "true",
        }, content=content, timeout=30)
        if r.status_code < 300:
            public_url = f"{SUPABASE_URL}/storage/v1/object/public/sustentos/{storage_path}"
            _sb_patch("pedidos", {"prueba_entrega_url": public_url}, {"id": f"eq.{pedido_id}"})
            return {"ok": True, "url": public_url}
        else:
            # Fallback: store as base64 data URL
            b64 = base64.b64encode(content).decode()
            data_url = f"data:{file.content_type};base64,{b64[:100]}..."
            _sb_patch("pedidos", {"prueba_entrega_url": f"uploaded:{file.filename}"}, {"id": f"eq.{pedido_id}"})
            return {"ok": True, "url": f"uploaded:{file.filename}", "note": "Storage bucket may need setup"}
    except Exception as e:
        _sb_patch("pedidos", {"prueba_entrega_url": f"uploaded:{file.filename}"}, {"id": f"eq.{pedido_id}"})
        return {"ok": True, "url": f"uploaded:{file.filename}", "note": str(e)}

# ===================== CIRCA ADMIN =====================

ADMIN_TOKEN = os.getenv("CIRCA_ADMIN_TOKEN", "circa-admin-2026")

async def verify_admin(x_admin_token: str = Header(..., alias="X-Admin-Token")):
    if x_admin_token != ADMIN_TOKEN:
        raise HTTPException(status_code=401, detail="Token admin invalido")
    return True


def _days_ago_iso(days: int) -> str:
    from datetime import timedelta
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

@router.get("/admin/pedidos")
async def admin_list_pedidos(
    bodega: Optional[str] = None,
    distribuidor: Optional[str] = None,
    estado: Optional[str] = None,
    tipo: Optional[str] = None,
    admin: bool = Depends(verify_admin),
):
    """List all orders with full details — admin view."""
    params = {"select":"*","order":"created_at.desc","limit":"1000"}
    if estado: params["estado"] = f"eq.{estado}"
    if tipo in ("venta", "preventa"):
        params["tipo_operacion"] = f"eq.{tipo}"
    pedidos = _sb_get("pedidos", params)
    # Fetch all bodegas and distribuidores
    bodega_ids = list(set(p.get("bodega_id","") for p in pedidos if p.get("bodega_id")))
    dist_ids = list(set(p.get("distribuidor_id","") for p in pedidos if p.get("distribuidor_id")))
    bodegas_map = {}
    for bid in bodega_ids:
        try:
            rows = _sb_get("bodegas", {
                "select": (
                    "id,nombre_comercial,razon_social,representante_legal,"
                    "representante_nombre_corto,telefono_whatsapp,ruc,"
                    "direccion_fiscal,linea_aprobada,linea_disponible"
                ),
                "id": f"eq.{bid}",
            })
            if rows: bodegas_map[bid] = rows[0]
        except: pass
    dist_map = {}
    for did in dist_ids:
        try:
            rows = _sb_get("distribuidores", {"select":"id,nombre_comercial,ruc","id":f"eq.{did}"})
            if rows: dist_map[did] = rows[0]
        except: pass
    for p in pedidos:
        p["bodega"] = bodegas_map.get(p.get("bodega_id"), {})
        p["distribuidor"] = dist_map.get(p.get("distribuidor_id"), {})
        if "items_json" in p and "items" not in p:
            p["items"] = p["items_json"]
    # Filter by name if provided
    if bodega:
        bl = bodega.lower()
        def _match_bodega(p: dict) -> bool:
            b = p.get("bodega", {}) or {}
            haystack = " ".join([
                b.get("nombre_comercial", "") or "",
                b.get("razon_social", "") or "",
                b.get("representante_legal", "") or "",
                b.get("representante_nombre_corto", "") or "",
                b.get("telefono_whatsapp", "") or "",
                b.get("ruc", "") or "",
            ]).lower()
            return bl in haystack
        pedidos = [p for p in pedidos if _match_bodega(p)]
    if distribuidor:
        dl = distribuidor.lower()
        pedidos = [p for p in pedidos if dl in (p.get("distribuidor",{}).get("nombre_comercial","") or "").lower()]
    return {"pedidos": pedidos, "total": len(pedidos)}


@router.post("/admin/preventa/{pedido_id}/aceptar")
async def admin_aceptar_preventa(pedido_id: str, admin: bool = Depends(verify_admin)):
    rows = _sb_get("pedidos", {"select":"id,numero,estado,tipo_operacion","id":f"eq.{pedido_id}"})
    if not rows:
        raise HTTPException(status_code=404, detail="Pedido no encontrado")
    p = rows[0]
    if p.get("tipo_operacion") != "preventa":
        raise HTTPException(status_code=400, detail="El pedido no es pre-venta")
    if p.get("estado") != "preventa_confirmada":
        raise HTTPException(status_code=400, detail="La pre-venta no está en estado confirmada")
    _sb_patch(
        "pedidos",
        {
            "estado": "preventa_aceptada",
            "preventa_aceptada_at": datetime.now(timezone.utc).isoformat(),
            "preventa_aceptada_por": "admin",
        },
        {"id": f"eq.{pedido_id}"},
    )
    return {"ok": True, "pedido_id": pedido_id, "estado": "preventa_aceptada", "numero": p.get("numero")}

@router.get("/admin/resumen")
async def admin_resumen(admin: bool = Depends(verify_admin)):
    """Dashboard summary for Circa admin."""
    pedidos = _sb_get("pedidos", {"select":"estado,monto_productos,monto_financiado,monto_contado,fee_monto,total","limit":"500"})
    estados = {}
    total_financiado = 0
    total_fee = 0
    total_contado = 0
    for p in pedidos:
        e = p.get("estado","?")
        estados[e] = estados.get(e, 0) + 1
        total_financiado += p.get("monto_financiado") or 0
        total_fee += p.get("fee_monto") or 0
        total_contado += p.get("monto_contado") or 0
    return {
        "pedidos_por_estado": estados,
        "total_pedidos": len(pedidos),
        "total_financiado": round(total_financiado, 2),
        "total_fee_circa": round(total_fee, 2),
        "total_contado": round(total_contado, 2),
        "circa_cobra_bodegas": round(total_financiado + total_fee, 2),
    }


@router.get("/admin/analytics-resumen")
async def admin_analytics_resumen(admin: bool = Depends(verify_admin)):
    """Light analytics dashboard for pilot event/message tracking."""
    since_7d = _days_ago_iso(7)
    since_30d = _days_ago_iso(30)

    events_7d = _sb_get("events", {"select": "event_type,created_at", "created_at": f"gte.{since_7d}", "limit": "5000"})
    events_30d = _sb_get("events", {"select": "event_type,created_at,bodega_id", "created_at": f"gte.{since_30d}", "limit": "20000"})
    msgs_7d = _sb_get("messages", {"select": "direction,bodega_id", "created_at": f"gte.{since_7d}", "limit": "10000"})

    def _cnt(rows, ev):
        return sum(1 for r in rows if r.get("event_type") == ev)

    funnel = {
        "catalog_opened": _cnt(events_7d, "catalog_opened"),
        "product_added": _cnt(events_7d, "product_added"),
        "order_created": _cnt(events_7d, "order_created") + _cnt(events_7d, "preventa_created"),
        "order_confirmed": _cnt(events_7d, "order_confirmed") + _cnt(events_7d, "preventa_confirmada"),
        "payment_made": _cnt(events_7d, "payment_made"),
    }

    inbound = sum(1 for m in msgs_7d if m.get("direction") == "inbound")
    outbound = sum(1 for m in msgs_7d if m.get("direction") == "outbound")
    response_rate = round((inbound / outbound) * 100, 1) if outbound else 0.0

    by_type = {}
    for ev in events_7d:
        t = ev.get("event_type", "unknown")
        by_type[t] = by_type.get(t, 0) + 1
    top_events = sorted(
        [{"event_type": k, "count": v} for k, v in by_type.items()],
        key=lambda x: x["count"],
        reverse=True,
    )[:8]

    active_bodegas_30d = len(set(e.get("bodega_id") for e in events_30d if e.get("bodega_id")))

    return {
        "period_days": 7,
        "funnel": funnel,
        "messages": {
            "inbound_7d": inbound,
            "outbound_7d": outbound,
            "response_rate_pct": response_rate,
        },
        "active_bodegas_30d": active_bodegas_30d,
        "top_events_7d": top_events,
    }

@router.post("/admin/cobranza/{pedido_id}")
async def admin_send_cobranza(pedido_id: str, admin: bool = Depends(verify_admin)):
    """Manually send payment reminder to bodeguero."""
    rows = _sb_get("pedidos", {"select":"*","id":f"eq.{pedido_id}"})
    if not rows:
        raise HTTPException(status_code=404, detail="Pedido no encontrado")
    ped = rows[0]
    bid = ped.get("bodega_id","")
    try:
        b_rows = _sb_get("bodegas", {"select":"telefono_whatsapp,nombre_comercial","id":f"eq.{bid}"})
        tel = b_rows[0].get("telefono_whatsapp","") if b_rows else ""
    except:
        tel = ""
    if not tel:
        raise HTTPException(status_code=400, detail="Bodega sin telefono")
    monto_fin = ped.get("monto_financiado") or 0
    fee = ped.get("fee_monto") or 0
    total_credito = round(monto_fin + fee, 2)
    plazo = ped.get("plazo_dias") or 7
    venc = ped.get("fecha_vencimiento") or "Por definir"
    num = ped.get("numero", "")
    reminder = (
        f"\U0001f4b3 *Recordatorio de pago — Circa*\n"
        f"\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n\n"
        f"Pedido: *{num}*\n"
        f"Monto financiado: S/{monto_fin:.2f}\n"
        f"Fee: S/{fee:.2f}\n"
        f"*Total a pagar: S/{total_credito:.2f}*\n\n"
        f"Vence: *{venc}*\n\n"
        f"\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n"
        f"Paga por Yape o Plin al:\n"
        f"\U0001f4f1 *986311567*\n"
        f"\U0001f464 PALI SAC\n\n"
        f"Escribe *YA PAGUE* en este chat."
    )
    _send_wa_text(tel, reminder)
    return {"ok": True, "enviado_a": tel, "pedido": num}

# ===================== COBRANZAS =====================

@router.get("/admin/cobranzas")
async def admin_cobranzas(
    distribuidor: Optional[str] = None,
    bodega: Optional[str] = None,
    estado: Optional[str] = None,
    fecha_desde: Optional[str] = None,
    fecha_hasta: Optional[str] = None,
    admin: bool = Depends(verify_admin),
):
    """List all orders with delivery status + payment tracking."""
    from datetime import datetime, timedelta
    
    params = {
        "select": "*",
        "estado": "in.(entregado,pago_reportado,pagado)",
        "order": "created_at.desc",
        "limit": "500"
    }
    pedidos = _sb_get("pedidos", params)
    
    # Bodegas
    bodega_ids = list(set(p.get("bodega_id","") for p in pedidos if p.get("bodega_id")))
    bodegas_map = {}
    for bid in bodega_ids:
        try:
            rows = _sb_get("bodegas", {"select":"id,nombre_comercial,telefono_whatsapp,ruc,direccion_fiscal","id":f"eq.{bid}"})
            if rows: bodegas_map[bid] = rows[0]
        except: pass
    
    # Distribuidores
    dist_ids = list(set(p.get("distribuidor_id","") for p in pedidos if p.get("distribuidor_id")))
    dist_map = {}
    for did in dist_ids:
        try:
            rows = _sb_get("distribuidores", {"select":"id,nombre_comercial,ruc","id":f"eq.{did}"})
            if rows: dist_map[did] = rows[0]
        except: pass
    
    hoy = datetime.utcnow().date()
    resultado = []
    for p in pedidos:
        plazo = p.get("plazo_dias") or 0
        fecha_entregado = p.get("fecha_entregado") or p.get("created_at")
        
        if fecha_entregado and plazo > 0:
            try:
                fe = datetime.fromisoformat(fecha_entregado.replace("Z","+00:00")).date()
                venc = fe + timedelta(days=plazo)
                dias_restantes = (venc - hoy).days
            except:
                venc = None
                dias_restantes = None
        else:
            venc = None
            dias_restantes = None
        
        # Status
        if p.get("estado") == "pagado":
            status_cobranza = "pagado"
        elif p.get("estado") == "pago_reportado":
            status_cobranza = "pago_reportado"
        elif dias_restantes is None:
            status_cobranza = "pendiente"
        elif dias_restantes < 0:
            status_cobranza = "vencido"
        elif dias_restantes <= 3:
            status_cobranza = "por_vencer"
        else:
            status_cobranza = "al_dia"
        
        item = {
            "pedido_id": p["id"],
            "numero": p.get("numero", ""),
            "bodega": bodegas_map.get(p.get("bodega_id"), {}),
            "distribuidor": dist_map.get(p.get("distribuidor_id"), {}),
            "monto_financiado": float(p.get("monto_financiado") or 0),
            "fee": float(p.get("fee_monto") or 0),
            "total_pagar": float(p.get("monto_total_credito") or p.get("total") or (float(p.get("monto_financiado") or 0) + float(p.get("fee_monto") or 0))),
            "plazo_dias": plazo,
            "fecha_entregado": fecha_entregado,
            "fecha_vencimiento": venc.isoformat() if venc else None,
            "dias_restantes": dias_restantes,
            "status_cobranza": status_cobranza,
            "estado": p.get("estado"),
            "fecha_pagado": p.get("fecha_pagado"),
        }
        
        # Filters
        if distribuidor:
            dl = distribuidor.lower()
            if dl not in (item["distribuidor"].get("nombre_comercial","") or "").lower():
                continue
        if bodega:
            bl = bodega.lower()
            if bl not in (item["bodega"].get("nombre_comercial","") or "").lower():
                continue
        if estado and estado != "todos":
            if estado != status_cobranza:
                continue
        if fecha_desde:
            try:
                if fecha_entregado and datetime.fromisoformat(fecha_entregado.replace("Z","+00:00")).date() < datetime.fromisoformat(fecha_desde).date():
                    continue
            except: pass
        if fecha_hasta:
            try:
                if fecha_entregado and datetime.fromisoformat(fecha_entregado.replace("Z","+00:00")).date() > datetime.fromisoformat(fecha_hasta).date():
                    continue
            except: pass
        
        resultado.append(item)
    
    # Stats por distribuidor
    stats_dist = {}
    for r in resultado:
        dname = r["distribuidor"].get("nombre_comercial", "?") or "?"
        if dname not in stats_dist:
            stats_dist[dname] = {"nombre": dname, "total": 0, "al_dia": 0, "por_vencer": 0, "vencido": 0, "pagado": 0, "pago_reportado": 0, "monto_vencido": 0}
        s = stats_dist[dname]
        s["total"] += 1
        s[r["status_cobranza"]] = s.get(r["status_cobranza"], 0) + 1
        if r["status_cobranza"] == "vencido":
            s["monto_vencido"] += r["total_pagar"]
    
    # Tasa de pago puntual
    for s in stats_dist.values():
        total_vencidos_o_pagados = s.get("pagado", 0) + s.get("vencido", 0)
        if total_vencidos_o_pagados > 0:
            s["tasa_puntual"] = round(100 * s.get("pagado", 0) / total_vencidos_o_pagados, 1)
        else:
            s["tasa_puntual"] = 100
    
    return {"cobranzas": resultado, "total": len(resultado), "stats_distribuidor": list(stats_dist.values())}


@router.post("/admin/verificar-pago/{pedido_id}")
async def admin_verificar_pago(pedido_id: str, payload: dict, admin: bool = Depends(verify_admin)):
    """Mark order as paid + restore bodega line."""
    from datetime import datetime
    from app.services.analytics import track_event
    
    rows = _sb_get("pedidos", {"select":"*","id":f"eq.{pedido_id}"})
    if not rows:
        raise HTTPException(status_code=404, detail="Pedido no encontrado")
    ped = rows[0]
    
    monto_financiado = float(ped.get("monto_financiado") or 0)
    bodega_id = ped.get("bodega_id")
    
    # Update pedido
    patch = {
        "estado": "pagado",
        "fecha_pagado": datetime.utcnow().isoformat(),
        "metodo_pago": payload.get("metodo", "yape"),
        "nro_operacion": payload.get("nro_operacion", ""),
    }
    _sb_patch("pedidos", patch, {"id": f"eq.{pedido_id}"})
    track_event(
        "payment_made",
        bodega_id=bodega_id,
        pedido_id=pedido_id,
        source="admin",
        metadata={
            "metodo": payload.get("metodo", "yape"),
            "nro_operacion": payload.get("nro_operacion", ""),
            "monto_financiado": monto_financiado,
        },
    )
    
    # Restore bodega line
    if bodega_id and monto_financiado > 0:
        bod = _sb_get("bodegas", {"select":"linea_disponible,telefono_whatsapp,nombre_comercial","id":f"eq.{bodega_id}"})
        if bod:
            nueva_linea = float(bod[0].get("linea_disponible") or 0) + monto_financiado
            nueva_linea = min(nueva_linea, bod[0].get('linea_aprobada', nueva_linea))  # Cap
            _sb_patch("bodegas", {"linea_disponible": nueva_linea}, {"id": f"eq.{bodega_id}"})
            
            # Notify bodega
            tel = bod[0].get("telefono_whatsapp", "")
            if tel:
                msg = (
                    f"\u2705 *Pago verificado*\n\n"
                    f"Pedido: *{ped.get('numero','')}*\n"
                    f"Monto: S/{ped.get('total',0)}\n\n"
                    f"\U0001f4b0 Tu linea disponible ahora es: *S/{nueva_linea:.2f}*\n\n"
                    f"Escribe *MENU* para hacer otro pedido."
                )
                _send_wa_text(tel, msg)
    
    return {"ok": True, "pedido": ped.get("numero"), "linea_restaurada": monto_financiado}


@router.get("/admin/export-pagos-distribuidor")
async def admin_export_pagos(
    fecha_desde: Optional[str] = None,
    fecha_hasta: Optional[str] = None,
    admin: bool = Depends(verify_admin),
):
    """Resumen consolidado de pagos a distribuidores por rango de fechas."""
    params = {"select":"*","estado":"in.(entregado,pagado,despachado,en_camino)","order":"created_at.desc","limit":"1000"}
    pedidos = _sb_get("pedidos", params)
    
    # Filter by date
    from datetime import datetime
    filtered = []
    for p in pedidos:
        if not p.get("created_at"): continue
        try:
            fp = datetime.fromisoformat(p["created_at"].replace("Z","+00:00")).date()
            if fecha_desde and fp < datetime.fromisoformat(fecha_desde).date(): continue
            if fecha_hasta and fp > datetime.fromisoformat(fecha_hasta).date(): continue
            filtered.append(p)
        except: continue
    
    # Group by distribuidor
    grupos = {}
    for p in filtered:
        did = p.get("distribuidor_id", "")
        if did not in grupos:
            grupos[did] = {"pedidos": [], "total_financiado": 0}
        grupos[did]["pedidos"].append(p)
        grupos[did]["total_financiado"] += float(p.get("monto_financiado") or 0)
    
    # Enrich with distribuidor + bodega info
    for did, g in grupos.items():
        try:
            d = _sb_get("distribuidores", {"select":"*","id":f"eq.{did}"})
            g["distribuidor"] = d[0] if d else {}
        except: g["distribuidor"] = {}
        for p in g["pedidos"]:
            try:
                b = _sb_get("bodegas", {"select":"nombre_comercial,ruc,telefono_whatsapp","id":f"eq.{p.get('bodega_id','')}"})
                p["bodega"] = b[0] if b else {}
            except: p["bodega"] = {}
    
    return {"grupos": list(grupos.values()), "total_pedidos": len(filtered)}

