"""
Distribuidor Portal API — Circa
"""
from fastapi import APIRouter, HTTPException, Header, Depends
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
    params = {"select":"*,bodegas(nombre_comercial,telefono,ruc,direccion)","distribuidor_id":f"eq.{dist['id']}","order":"created_at.desc"}
    if estado: params["estado"] = f"eq.{estado}"
    return {"pedidos": _sb_get("pedidos", params), "distribuidor": dist["nombre_comercial"]}

@router.get("/pedidos/{pedido_id}")
async def get_pedido(pedido_id: str, dist: dict = Depends(verify_distribuidor)):
    rows = _sb_get("pedidos", {"select":"*,bodegas(nombre_comercial,telefono,ruc,direccion)","id":f"eq.{pedido_id}","distribuidor_id":f"eq.{dist['id']}"})
    if not rows: raise HTTPException(status_code=404, detail="Pedido no encontrado")
    return rows[0]

@router.post("/pedidos/{pedido_id}/status")
async def update_status(pedido_id: str, body: StatusUpdate, dist: dict = Depends(verify_distribuidor)):
    rows = _sb_get("pedidos", {"select":"*,bodegas(nombre_comercial,telefono)","id":f"eq.{pedido_id}","distribuidor_id":f"eq.{dist['id']}"})
    if not rows: raise HTTPException(status_code=404, detail="Pedido no encontrado")
    pedido = rows[0]
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
    rows = _sb_get("pedidos", {"select":"*,bodegas(nombre_comercial,telefono,ruc,direccion,razon_social)","id":f"eq.{pedido_id}","distribuidor_id":f"eq.{dist['id']}"})
    if not rows: raise HTTPException(status_code=404, detail="Pedido no encontrado")
    pedido = rows[0]
    if pedido["estado"] not in ("despachado","en_camino","entregado"):
        raise HTTPException(status_code=400, detail="Solo se puede facturar pedidos despachados o entregados")
    bodega = pedido.get("bodegas") or {}
    items = pedido.get("items", [])
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
