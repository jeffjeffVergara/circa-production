"""Supabase client wrapper for all DB operations."""
from supabase import create_client
from app.config import SUPABASE_URL, SUPABASE_KEY, now_peru
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
    firmado_at = now_peru().isoformat()
    # 1. Marcar contrato firmado
    sb.table("bodegas").update({
        "contrato_hash": contract_hash,
        "contrato_firmado_at": firmado_at,
    }).eq("id", bodega_id).execute()
    # 2. Liberar linea via funcion existente (FIX BUG #8 de Jeff)
    liberar_linea_post_contrato(bodega_id)
    # 3. NUEVO: liberacion forzada explicita - garantiza que linea_disponible = linea_aprobada
    # Sirve como fallback si liberar_linea_post_contrato falla silenciosamente
    try:
        b = sb.table("bodegas").select("linea_aprobada").eq("id", bodega_id).single().execute().data or {}
        if b.get("linea_aprobada"):
            sb.table("bodegas").update({
                "linea_disponible": b["linea_aprobada"]
            }).eq("id", bodega_id).execute()
    except Exception as e:
        import logging
        logging.warning(f"sign_contract: liberacion forzada de linea fallo para bodega {bodega_id}: {e}")

    # NUEVO: registrar en tabla contratos para evidencia legal
    # Si falla por cualquier razon, NO rompemos la firma - solo loggeamos warning
    try:
        bodega = sb.table("bodegas").select(
            "razon_social, representante_legal, dni_representante"
        ).eq("id", bodega_id).single().execute().data or {}
        sb.table("contratos").insert({
            "bodega_id": bodega_id,
            "version": "v2.1_2026-04-28",
            "url_contrato": None,
            "aceptado_at": firmado_at,
            "canal": "whatsapp",
            "ip_address": None,
            "user_agent": None,
            "nombre_firmante": (
                bodega.get("representante_legal") or bodega.get("razon_social")
            ),
            "dni_firmante": bodega.get("dni_representante"),
            "metadata": {
                "contrato_hash": contract_hash,
                "captured_via": "sign_contract_inline_v1",
            },
        }).execute()
    except Exception as e:
        import logging
        logging.warning(f"sign_contract: insert en tabla contratos fallo para bodega {bodega_id}: {e}")

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
    fecha_venc = None  # Se calcula al marcar entregado
    
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
        new_line = min(new_line, bodega["linea_aprobada"])  # Cap: never exceed approved
        sb.table("bodegas").update({"linea_disponible": max(0, new_line)}).eq("id", pedido["bodega_id"]).execute()
    
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


def log_biometria_auditoria(
    bodega_id: str,
    telefono: str,
    etapa: str,
    hit: bool,
    reason: str = "",
    reason_code: str = "",
    confidence: str = "",
    provider: str = "",
    model: str = "",
    metadata: dict = None,
):
    """Audit trail for biometric validations (DNI photo / selfie)."""
    payload = {
        "bodega_id": bodega_id,
        "telefono": telefono,
        "etapa": etapa,
        "hit": hit,
        "reason": reason or "",
        "reason_code": reason_code or "",
        "confidence": confidence or "",
        "provider": provider or "",
        "model": model or "",
        "metadata": json.dumps(metadata or {}),
    }
    sb.table("biometria_auditoria").insert(payload).execute()


# ============================================================
# Helpers para motor de promociones (Sprint promociones DIMAX 22-abr-2026)
# ============================================================

def get_promociones_activas(distribuidor_id: str) -> list:
    """Devuelve las reglas de promociones activas para un distribuidor."""
    try:
        r = sb.table("promociones_distribuidor").select("*").eq(
            "distribuidor_id", distribuidor_id
        ).eq("activa", True).execute()
        return r.data or []
    except Exception as e:
        import logging
        logging.error(f"get_promociones_activas error: {e}")
        return []


def get_distribuidor_de_bodega(bodega_id: str) -> str:
    """Devuelve el distribuidor_id asignado a una bodega."""
    try:
        r = sb.table("bodegas").select("distribuidor_id").eq(
            "id", bodega_id
        ).single().execute()
        return r.data["distribuidor_id"] if r.data else None
    except Exception as e:
        import logging
        logging.error(f"get_distribuidor_de_bodega error: {e}")
        return None


def get_catalogo_info_for_skus(distribuidor_id: str, skus: list) -> dict:
    """
    Devuelve info de productos por sku_distribuidor.
    Para que el motor sepa categoria, marca, contenido_caja, contenido_pack.
    Retorna: { sku_distribuidor: {categoria, marca, contenido_caja, contenido_pack} }
    """
    if not skus:
        return {}
    try:
        r = sb.table("catalogo_distribuidor").select(
            "sku_distribuidor, productos_circa(categoria, marca, contenido_caja, contenido_pack)"
        ).eq("distribuidor_id", distribuidor_id).in_("sku_distribuidor", skus).execute()
        result = {}
        for row in r.data or []:
            sku = row["sku_distribuidor"]
            pc = row.get("productos_circa") or {}
            result[sku] = {
                "categoria": pc.get("categoria"),
                "marca": pc.get("marca"),
                "contenido_caja": pc.get("contenido_caja"),
                "contenido_pack": pc.get("contenido_pack"),
            }
        return result
    except Exception as e:
        import logging
        logging.error(f"get_catalogo_info_for_skus error: {e}")
        return {}


def get_skus_for_catalogo_ids(distribuidor_id: str, catalogo_ids: list) -> dict:
    """
    Mapea UUIDs de productos_circa a sku_distribuidor del distribuidor dado.
    Útil para el frontend que solo conoce catalogo_id (UUID).
    Retorna: { catalogo_id_uuid: sku_distribuidor_string }
    """
    if not catalogo_ids:
        return {}
    try:
        r = sb.table("catalogo_distribuidor").select(
            "producto_circa_id, sku_distribuidor"
        ).eq("distribuidor_id", distribuidor_id).in_("producto_circa_id", catalogo_ids).execute()
        return {row["producto_circa_id"]: row["sku_distribuidor"] for row in r.data or []}
    except Exception as e:
        import logging
        logging.error(f"get_skus_for_catalogo_ids error: {e}")
        return {}


# ============================================================
# Helpers para preventa DIMAX (Sprint preventa 28-abr-2026)
# ============================================================

def upsert_bodega_para_preventa(ruc: str, distribuidor_id: str, **datos_bodega) -> tuple:
    """
    Busca bodega por RUC. Si existe, devuelve (bodega, False).
    Si NO existe, crea bodega con estado='inactivo' y linea_disponible=0
    (línea bloqueada hasta firmar contrato), devuelve (bodega_nueva, True).
    
    datos_bodega puede incluir: razon_social, nombre_comercial, telefono_whatsapp,
        direccion_fiscal, direccion_despacho, dni_representante, representante_legal,
        distrito, provincia, solo_dni_sin_ruc (bool; onboarding salta RUC).
    """
    existing = get_bodega_by_ruc(ruc)
    if existing:
        return (existing, False)
    
    payload = {
        "ruc": ruc,
        "distribuidor_id": distribuidor_id,
        "estado": "inactivo",
        "linea_aprobada": 500,
        "linea_disponible": 0,  # Bloqueada hasta firmar contrato
        **{k: v for k, v in datos_bodega.items() if v is not None},
    }
    nueva = sb.table("bodegas").insert(payload).execute().data[0]
    return (nueva, True)


def crear_pedido_preventa(
    bodega_id: str,
    distribuidor_id: str,
    items_dimax: list,
    total_pedido: float,
    descuento_prorrateado: float = 0,
    vendedor_id: str = None,
    dimax_pedido_id: str = None,
    fecha_visita: str = None,
    fecha_entrega: str = None,
) -> dict:
    """
    Crea un pedido en estado='preventa_confirmada', origen='preventa_dimax'.
    NO genera número (eso pasa al confirmar con PIN).
    NO baja línea de crédito.
    NO crea pagos ni recordatorios.
    
    items_dimax: list of dicts con {sku_distribuidor, cantidad, unidad, precio_unitario, subtotal}
    
    Resuelve sku_distribuidor → catalogo_id via lookup. Items que no matchean se reportan
    en el resultado pero NO bloquean la creación del pedido (decisión: opción b, resiliencia).
    
    Returns: {
        "pedido_id": uuid,
        "items_creados": int,
        "items_no_match": list of dicts con SKUs no encontrados
    }
    """
    monto_productos = float(total_pedido) + float(descuento_prorrateado)  # Subtotal antes de descuento
    
    # Insertar pedido (sin número, sin financiamiento)
    pedido = sb.table("pedidos").insert({
        "bodega_id": bodega_id,
        "distribuidor_id": distribuidor_id,
        "vendedor_id": vendedor_id,
        "estado": "preventa_confirmada",
        "origen": "preventa_dimax",
        "monto_productos": monto_productos,
        "descuento_prorrateado": descuento_prorrateado,
        "total_pedido": total_pedido,
        "monto_financiado": 0,
        "monto_contado": 0,
        "dimax_pedido_id": dimax_pedido_id,
        "fecha_visita": fecha_visita,
        "fecha_entrega": fecha_entrega,
    }).execute().data[0]
    pedido_id = pedido["id"]
    
    # Resolver SKUs DIMAX → catalogo_id (normalizar quitando ceros a la izquierda)
    skus_normalizados = list({str(it["sku_distribuidor"]).lstrip("0") or "0" for it in items_dimax})
    catalogo = sb.table("catalogo_distribuidor").select("id, sku_distribuidor").eq(
        "distribuidor_id", distribuidor_id
    ).in_("sku_distribuidor", skus_normalizados).execute().data
    sku_to_cat = {c["sku_distribuidor"]: c["id"] for c in catalogo}
    
    items_creados = 0
    items_no_match = []
    
    for it in items_dimax:
        sku_norm = str(it["sku_distribuidor"]).lstrip("0") or "0"
        catalogo_id = sku_to_cat.get(sku_norm)
        if not catalogo_id:
            items_no_match.append({
                "sku_distribuidor": it["sku_distribuidor"],
                "descripcion": it.get("descripcion"),
                "cantidad": it["cantidad"],
            })
            continue
        
        # pack_size = número entero de unidades por pack ("UND x 1" → 1, "CJA x 6" → 6)
        unidad_str = it.get("unidad") or "UND x 1"
        try:
            pack_size_int = int(unidad_str.split("x")[-1].strip())
        except (ValueError, AttributeError):
            pack_size_int = 1  # fallback seguro
        
        sb.table("items_pedido").insert({
            "pedido_id": pedido_id,
            "catalogo_id": catalogo_id,
            "pack_size": pack_size_int,
            "unidad": unidad_str,
            "cantidad": it["cantidad"],
            "precio": it["precio_unitario"],
            "subtotal": it.get("subtotal", it["cantidad"] * it["precio_unitario"]),
        }).execute()
        items_creados += 1
    
    log_evento(pedido_id, bodega_id, "preventa_creada", None, "borrador", "dimax")
    
    return {
        "pedido_id": pedido_id,
        "items_creados": items_creados,
        "items_no_match": items_no_match,
    }


def get_preventa_pendiente(bodega_id: str) -> dict:
    """
    Devuelve la preventa más reciente en estado borrador para esta bodega.
    Incluye items_pedido. Devuelve None si no hay.
    """
    r = sb.table("pedidos").select("*").eq(
        "bodega_id", bodega_id
    ).eq("estado", "preventa_confirmada").eq("origen", "preventa_dimax").order(
        "fecha_visita", desc=True
    ).limit(1).execute()
    
    if not r.data:
        return None
    
    pedido = r.data[0]
    items = sb.table("items_pedido").select(
        "*, catalogo_distribuidor(sku_distribuidor, productos_circa(nombre, marca))"
    ).eq("pedido_id", pedido["id"]).execute().data
    pedido["items"] = items
    return pedido


def liberar_linea_post_contrato(bodega_id: str) -> bool:
    """
    Activa la línea de crédito de una bodega que firmó contrato.
    Hace UPDATE linea_disponible = linea_aprobada.
    Idempotente (correr 2 veces no rompe).
    El trigger cap_linea_disponible valida que no exceda linea_aprobada.
    
    Returns: True si actualizó, False si la bodega no existe.
    """
    r = sb.table("bodegas").select("id, linea_aprobada").eq(
        "id", bodega_id
    ).limit(1).execute()
    
    if not r.data:
        return False
    
    bodega = r.data[0]
    sb.table("bodegas").update({
        "linea_disponible": bodega["linea_aprobada"]
    }).eq("id", bodega_id).execute()
    
    return True

