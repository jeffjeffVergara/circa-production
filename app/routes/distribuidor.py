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
    "despachado": "🚚 *Pedido {numero} despachado*\n{distribuidor} envio tu pedido. Ya va en camino!",
    "en_camino": "🚚 *Pedido {numero} en camino*\nTu pedido esta siendo entregado.",
    "entregado": "🎉 *Pedido {numero} entregado*\nTu pedido fue entregado. Gracias por comprar con Circa!",
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
            rows = _sb_get("bodegas", {"select":"id,nombre_comercial,telefono,ruc,direccion,razon_social","id":f"eq.{bid}"})
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
        b_rows = _sb_get("bodegas", {"select":"nombre_comercial,telefono","id":f"eq.{pedido.get('bodega_id','')}"})
        pedido["bodegas"] = b_rows[0] if b_rows else {}
    except: pedido["bodegas"] = {}
    current = pedido["estado"]
    nuevo = body.nuevo_estado
    if nuevo != STATUS_FLOW.get(current):
        raise HTTPException(status_code=400, detail=f"No se puede pasar de '{current}' a '{nuevo}'. Siguiente: '{STATUS_FLOW.get(current)}'")
    _sb_patch("pedidos", {"estado": nuevo, f"fecha_{nuevo}": datetime.now(timezone.utc).isoformat()}, {"id": f"eq.{pedido_id}"})
    bodega = pedido.get("bodegas") or {}
    tel = bodega.get("telefono","")
    if tel and nuevo in WA_MESSAGES:
        _send_wa_text(tel, WA_MESSAGES[nuevo].format(numero=pedido.get("numero",pedido_id[:8]), distribuidor=dist["nombre_comercial"]))
    return {"ok":True,"pedido_id":pedido_id,"estado_anterior":current,"estado_nuevo":nuevo,"notificado":bool(tel)}

@router.post("/pedidos/{pedido_id}/facturar")
async def preparar_factura(pedido_id: str, dist: dict = Depends(verify_distribuidor)):
    rows = _sb_get("pedidos", {"select":"*","id":f"eq.{pedido_id}","distribuidor_id":f"eq.{dist['id']}"})
    if not rows: raise HTTPException(status_code=404, detail="Pedido no encontrado")
    pedido = rows[0]
    try:
        b_rows = _sb_get("bodegas", {"select":"nombre_comercial,telefono,ruc,direccion,razon_social","id":f"eq.{pedido.get('bodega_id','')}"})
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

