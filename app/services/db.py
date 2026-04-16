"""Supabase client wrapper for all DB operations."""
from supabase import create_client
from app.config import SUPABASE_URL, SUPABASE_KEY
from datetime import datetime, timedelta, date
import json

sb = create_client(SUPABASE_URL, SUPABASE_KEY)

# ── SESIONES ──────────────────────────────────
def get_session(telefono: str):
    r = sb.table("sesiones").select("*").eq("telefono", telefono).order("last_activity", desc=True).limit(1).execute()
    return r.data[0] if r.data else None

def upsert_session(telefono: str, fase: str, datos: dict = None, bodega_id: str = None):
    existing = get_session(telefono)
    payload = {
        "telefono": telefono,
        "fase": fase,
        "datos": json.dumps(datos or {}),
        "last_activity": datetime.utcnow().isoformat(),
        "expires_at": (datetime.utcnow() + timedelta(hours=24)).isoformat(),
    }
    if bodega_id:
        payload["bodega_id"] = bodega_id
    if existing:
        sb.table("sesiones").update(payload).eq("id", existing["id"]).execute()
    else:
        sb.table("sesiones").insert(payload).execute()

# ── BODEGAS ───────────────────────────────────
def get_bodega_by_phone(telefono: str):
    r = sb.table("bodegas").select("*").eq("telefono_whatsapp", telefono).limit(1).execute()
    return r.data[0] if r.data else None

def get_bodega_by_ruc(ruc: str):
    r = sb.table("bodegas").select("*").eq("ruc", ruc).limit(1).execute()
    return r.data[0] if r.data else None

def update_bodega(bodega_id: str, data: dict):
    sb.table("bodegas").update(data).eq("id", bodega_id).execute()

def activate_bodega(bodega_id: str, pin_hash: str):
    sb.table("bodegas").update({
        "pin_hash": pin_hash,
        "estado": "activo",
    }).eq("id", bodega_id).execute()

def sign_contract(bodega_id: str, contract_hash: str):
    sb.table("bodegas").update({
        "contrato_hash": contract_hash,
        "contrato_firmado_at": datetime.utcnow().isoformat(),
    }).eq("id", bodega_id).execute()

# ── CATÁLOGO ──────────────────────────────────
def get_catalogo(distribuidor_id: str, marca: str = None, categoria: str = None):
    """Returns flat dict format compatible with legacy catalogo.py code."""
    q = sb.table("catalogo_distribuidor").select("*, productos_circa(*)").eq("distribuidor_id", distribuidor_id).eq("activo", True)
    rows = q.execute().data
    # Flatten: move productos_circa fields to top level
    result = []
    for row in rows:
        pc = row.get("productos_circa") or {}
        if marca and pc.get("marca") != marca:
            continue
        if categoria and pc.get("categoria") != categoria:
            continue
        # Compatible structure: id = producto_circa_id (for cart lookups)
        item = {
            "id": pc.get("id"),
            "nombre": pc.get("nombre", ""),
            "marca": pc.get("marca", ""),
            "categoria": pc.get("categoria", ""),
            "descripcion": pc.get("descripcion", ""),
            "presentacion": pc.get("presentacion", ""),
            "imagen_url": pc.get("imagen_url", ""),
            "unidades": row.get("unidades") or {},
            "codigo": row.get("codigo") or pc.get("codigo", ""),
            "sku": row.get("sku_distribuidor", ""),
            "activo": row.get("activo", True),
        }
        result.append(item)
    return result

def get_catalogo_all_for_bodega(bodega_id: str):
    """Get catalog from bodega's default distribuidor."""
    bodega = sb.table("bodegas").select("distribuidor_id").eq("id", bodega_id).single().execute().data
    if not bodega:
        return []
    return sb.table("catalogo_distribuidor").select("*, productos_circa(*)").eq("distribuidor_id", bodega["distribuidor_id"]).eq("activo", True).execute().data

def get_marcas(distribuidor_id: str):
    items = sb.table("catalogo_distribuidor").select("productos_circa(marca)").eq("distribuidor_id", distribuidor_id).eq("activo", True).execute().data
    items = [{"marca": i["productos_circa"]["marca"]} for i in items if i.get("productos_circa")]
    return sorted(set(i["marca"] for i in items))

def get_categorias(distribuidor_id: str):
    items = sb.table("catalogo_distribuidor").select("productos_circa(categoria)").eq("distribuidor_id", distribuidor_id).eq("activo", True).execute().data
    items = [{"categoria": i["productos_circa"]["categoria"]} for i in items if i.get("productos_circa")]
    return sorted(set(i["categoria"] for i in items))

# ── CARRITOS ──────────────────────────────────
def get_carrito(bodega_id: str):
    r = sb.table("carritos").select("*").eq("bodega_id", bodega_id).limit(1).execute()
    return r.data[0] if r.data else None

def save_carrito(bodega_id: str, items: list):
    existing = get_carrito(bodega_id)
    payload = {"bodega_id": bodega_id, "items": json.dumps(items), "updated_at": datetime.utcnow().isoformat()}
    if existing:
        sb.table("carritos").update(payload).eq("id", existing["id"]).execute()
    else:
        sb.table("carritos").insert(payload).execute()

def clear_carrito(bodega_id: str):
    sb.table("carritos").delete().eq("bodega_id", bodega_id).execute()

# ── PEDIDOS ───────────────────────────────────
def create_pedido(bodega_id: str, distribuidor_id: str, items: list, 
                  monto_productos: float, monto_financiado: float, monto_contado: float,
                  fee_tasa: float, fee_monto: float, plazo_dias: int):
    # Generate order number
    numero = sb.rpc("gen_numero_pedido").execute().data
    fecha_venc = (date.today() + timedelta(days=plazo_dias)).isoformat()
    
    pedido = sb.table("pedidos").insert({
        "numero": numero,
        "bodega_id": bodega_id,
        "distribuidor_id": distribuidor_id,
        "monto_productos": monto_productos,
        "monto_financiado": monto_financiado,
        "monto_contado": monto_contado,
        "fee_tasa": fee_tasa,
        "fee_monto": fee_monto,
        "monto_total_credito": monto_financiado + fee_monto,
        "plazo_dias": plazo_dias,
        "fecha_vencimiento": fecha_venc,
        "estado": "confirmado",
        "confirmado_at": datetime.utcnow().isoformat(),
    }).execute().data[0]
    
    # Insert items
    for item in items:
        sb.table("items_pedido").insert({
            "pedido_id": pedido["id"],
            "catalogo_id": item["catalogo_id"],
            "pack_size": item["pack_size"],
            "cantidad": item["cantidad"],
            "precio": item["precio"],
            "subtotal": item["precio"] * item["cantidad"],
        }).execute()
    
    # Create payment record
    sb.table("pagos").insert({
        "pedido_id": pedido["id"],
        "monto_esperado": monto_financiado + fee_monto,
        "fecha_vencimiento": fecha_venc,
    }).execute()
    
    # Create reminder schedule
    for tipo in ["d5", "d3", "d1", "d0", "d_1", "d_3", "d_7"]:
        sb.table("recordatorios").insert({
            "pedido_id": pedido["id"],
            "tipo": tipo,
        }).execute()
    
    # Update bodega linea disponible (only subtract financed amount)
    bodega = sb.table("bodegas").select("linea_disponible").eq("id", bodega_id).single().execute().data
    new_line = max(0, bodega["linea_disponible"] - monto_financiado)
    sb.table("bodegas").update({
        "linea_disponible": new_line,
        "ultimo_pedido_items": json.dumps(items),
    }).eq("id", bodega_id).execute()
    
    # Log event
    log_evento(pedido["id"], bodega_id, "pedido_confirmado", None, "confirmado", "bodeguero")
    
    return pedido

def update_pedido_estado(pedido_id: str, nuevo_estado: str, actor: str = "sistema"):
    pedido = sb.table("pedidos").select("estado").eq("id", pedido_id).single().execute().data
    anterior = pedido["estado"] if pedido else None
    
    update = {"estado": nuevo_estado}
    ts = datetime.utcnow().isoformat()
    if nuevo_estado == "aprobado": update["aprobado_at"] = ts
    elif nuevo_estado == "despachado": update["despachado_at"] = ts
    elif nuevo_estado == "entregado": update["entregado_at"] = ts
    elif nuevo_estado == "pagado": update["pagado_at"] = ts
    
    sb.table("pedidos").update(update).eq("id", pedido_id).execute()
    log_evento(pedido_id, None, f"estado_{nuevo_estado}", anterior, nuevo_estado, actor)

def get_pedidos_activos(bodega_id: str):
    return sb.table("pedidos").select("*").eq("bodega_id", bodega_id).not_.in_("estado", ["pagado", "rechazado"]).execute().data

# ── PAGOS ─────────────────────────────────────
def registrar_pago(pedido_id: str, monto: float, metodo: str = "yape"):
    sb.table("pagos").update({
        "monto_pagado": monto,
        "metodo": metodo,
        "estado": "pagado",
        "fecha_pago": datetime.utcnow().isoformat(),
    }).eq("pedido_id", pedido_id).execute()
    
    # Restore credit line: recalculate from scratch
    pedido = sb.table("pedidos").select("bodega_id, monto_financiado").eq("id", pedido_id).single().execute().data
    if pedido:
        bodega = sb.table("bodegas").select("linea_aprobada").eq("id", pedido["bodega_id"]).single().execute().data
        # Sum all active (unpaid) financed amounts — exclude the one being paid now
        activos = sb.table("pedidos").select("monto_financiado").eq("bodega_id", pedido["bodega_id"]).not_.in_("estado", ["pagado", "rechazado"]).execute().data
        total_activo = sum(p["monto_financiado"] for p in activos)
        new_line = bodega["linea_aprobada"] - total_activo
        sb.table("bodegas").update({"linea_disponible": new_line}).eq("id", pedido["bodega_id"]).execute()
    
    update_pedido_estado(pedido_id, "pagado", "bodeguero")

# ── EVENTOS ───────────────────────────────────
def log_evento(pedido_id, bodega_id, accion, estado_anterior, estado_nuevo, actor="sistema", metadata=None):
    sb.table("eventos").insert({
        "pedido_id": pedido_id,
        "bodega_id": bodega_id,
        "accion": accion,
        "estado_anterior": estado_anterior,
        "estado_nuevo": estado_nuevo,
        "actor": actor,
        "metadata": json.dumps(metadata or {}),
    }).execute()
