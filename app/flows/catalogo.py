"""
WhatsApp Flow Endpoint — Single-Screen Catálogo.
Cart state stored in Supabase (no cart_state field needed in Flow).
"""

import logging
import json
from app.services import db

logger = logging.getLogger("circa.flows.catalogo")

FEE_RATE = 0.03
MIN_FEE = 5.0

CATEGORIES = [
    {"id": "Abarrotes",         "emoji": "🛒"},
    {"id": "Bebidas Calientes", "emoji": "🥤"},
    {"id": "Golosinas",         "emoji": "🍬"},
    {"id": "Lácteos",           "emoji": "🥛"},
]


async def handle_catalogo(flow_data: dict) -> dict:
    action = flow_data.get("action", "")
    data   = flow_data.get("data", {})

    logger.info(f"Catalogo: action={action}, data_keys={list(data.keys())}")

    if action == "ping":
        return {"version": "3.0", "data": {"status": "active"}}

    bodega_id = data.get("bodega_id", "") or "b1b2c3d4-0001-4000-8000-000000000001"

    if action == "INIT":
        return _build_categories(bodega_id)

    selected = data.get("selected", "")
    logger.info(f"selected='{selected}', bodega={bodega_id}")

    # Load session from Supabase
    session = _load_session(bodega_id)

    if selected in ("BACK_CATS", "ADD_MORE"):
        session["cat"] = ""
        _save_session(bodega_id, session)
        return _build_categories(bodega_id, session)

    if selected == "BACK_PRODS":
        cat = session.get("cat", "")
        if cat:
            return await _build_products(bodega_id, session, cat)
        return _build_categories(bodega_id, session)

    if selected == "VIEW_CART":
        cart = session.get("cart", [])
        items = []
        for i, item in enumerate(cart):
            items.append({
                "id": f"DEL_{i}",
                "main-content": {
                    "title": f"{item.get('qty',0)}x {item.get('name','')}",
                    "description": f"S/{item.get('sub',0):.2f} - Toca para quitar",
                },
            })
        total = sum(i.get("sub", 0) for i in cart)
        items.append({"id": "ADD_MORE", "main-content": {"title": "Agregar mas", "description": "Volver a categorias"}})
        items.append({"id": "CHECKOUT", "main-content": {"title": "Confirmar pedido", "description": f"Total: S/{total:.2f}"}})
        if not cart:
            items = [{"id": "ADD_MORE", "main-content": {"title": "Carrito vacio", "description": "Toca para agregar"}}]
        return _make_response(items, bodega_id)

    if selected == "CHECKOUT":
        return await _do_checkout(bodega_id, session)

    if selected.startswith("REMOVE_"):
        try:
            idx = int(selected.split("_", 1)[1])
            cart = session.get("cart", [])
            if 0 <= idx < len(cart):
                cart.pop(idx)
            session["cart"] = cart
            _save_session(bodega_id, session)
        except (ValueError, IndexError):
            pass
        return _build_cart(bodega_id, session)

    if selected.startswith("ADD_"):
        return await _do_add_to_cart(bodega_id, session, selected)

    if selected.startswith("PROD_"):
        prod_id = selected[5:]
        return await _build_product_detail(bodega_id, session, prod_id)

    # Default: treat as category name
    return await _build_products(bodega_id, session, selected)


# ── Session management (Supabase) ──

def _load_session(bodega_id: str) -> dict:
    try:
        r = db.sb.table("flow_sessions").select("session_data").eq("bodega_id", bodega_id).limit(1).execute()
        if r.data and len(r.data) > 0 and r.data[0].get("session_data"):
            return json.loads(r.data[0]["session_data"])
    except Exception as e:
        logger.error(f"Load session error: {e}")
    return {"cart": [], "cat": "", "dist": ""}


def _save_session(bodega_id: str, session: dict):
    try:
        data = {"bodega_id": bodega_id, "session_data": json.dumps(session, ensure_ascii=False)}
        db.sb.table("flow_sessions").upsert(data, on_conflict="bodega_id").execute()
    except Exception as e:
        logger.error(f"Save session error: {e}")


def _make_response(items, bodega_id, cart_state="{}"):
    return {
        "version": "3.0",
        "screen": "CATALOG",
        "data": {
            "items":      items,
            "bodega_id":  bodega_id,
            "cart_state":  cart_state,
        },
    }


def _cart_badge(cart):
    if not cart:
        return None
    total = sum(i.get("sub", 0) for i in cart)
    n = len(cart)
    return {
        "id": "VIEW_CART",
        "main-content": {
            "title":       f"🛒 Ver carrito ({n} {'item' if n == 1 else 'items'})",
            "description": f"Total: S/{total:.2f}",
        },
    }


# ── Categories ──

def _build_categories(bodega_id, session=None):
    items = [
        {
            "id": c["id"],
            "main-content": {
                "title":       f"{c['emoji']} {c['id']}",
                "description": "Ver productos",
            },
        }
        for c in CATEGORIES
    ]
    if session:
        badge = _cart_badge(session.get("cart", []))
        if badge:
            items.append(badge)
    return _make_response(items, bodega_id)


# ── Products ──

async def _build_products(bodega_id, session, category):
    dist = session.get("dist", "")
    if not dist:
        try:
            row = db.sb.table("bodegas").select("distribuidor_id").eq("id", bodega_id).single().execute().data
            dist = row["distribuidor_id"] if row else "a1b2c3d4-0001-4000-8000-000000000001"
        except Exception:
            dist = "a1b2c3d4-0001-4000-8000-000000000001"

    session["dist"] = dist
    session["cat"]  = category
    _save_session(bodega_id, session)

    try:
        productos = db.get_catalogo(dist, categoria=category)
    except Exception as e:
        logger.error(f"Error loading products: {e}")
        productos = []

    items = []
    for p in productos:
        precios = [p[k] for k in ("precio_pack_6", "precio_pack_12", "precio_pack_24") if p.get(k)]
        min_p = min(precios) if precios else 0
        items.append({
            "id": f"PROD_{p['id']}",
            "main-content": {
                "title":       p.get("nombre", "Sin nombre"),
                "description": f"Desde S/{min_p:.2f}" if min_p else "Ver detalle",
            },
        })

    if not items:
        items.append({
            "id": "BACK_CATS",
            "main-content": {"title": "No hay productos", "description": "Volver"},
        })

    items.append({
        "id": "BACK_CATS",
        "main-content": {"title": "← Volver a categorias", "description": ""},
    })

    badge = _cart_badge(session.get("cart", []))
    if badge:
        items.append(badge)

    return _make_response(items, bodega_id)


# ── Product detail ──

async def _build_product_detail(bodega_id, session, product_id):
    try:
        p = db.sb.table("catalogo").select("*").eq("id", product_id).single().execute().data
    except Exception as e:
        logger.error(f"Product load error: {e}")
        p = None

    if not p:
        return _build_categories(bodega_id, session)

    nombre = p.get("nombre", "Producto")
    items  = []

    for pack_size in (6, 12, 24):
        precio = p.get(f"precio_pack_{pack_size}")
        if not precio:
            continue
        for qty in (1, 2, 5):
            sub = precio * qty
            items.append({
                "id": f"ADD_{qty}_{product_id}_PK{pack_size}",
                "main-content": {
                    "title":       f"{qty}x Pack {pack_size} — S/{sub:.2f}",
                    "description": f"S/{precio:.2f} c/u",
                },
            })

    if not items:
        for qty in (1, 2, 5):
            items.append({
                "id": f"ADD_{qty}_{product_id}_PK1",
                "main-content": {
                    "title":       f"Agregar {qty} unidad(es)",
                    "description": nombre,
                },
            })

    items.append({
        "id": "BACK_PRODS",
        "main-content": {"title": "← Volver a productos", "description": ""},
    })

    badge = _cart_badge(session.get("cart", []))
    if badge:
        items.append(badge)

    return _make_response(items, bodega_id)


# ── Add to cart ──

async def _do_add_to_cart(bodega_id, session, selected):
    remainder = selected[4:]
    first_us  = remainder.index("_")
    qty       = int(remainder[:first_us])
    rest      = remainder[first_us + 1:]

    pk_pos     = rest.rfind("_PK")
    product_id = rest[:pk_pos] if pk_pos > 0 else rest
    pack_size  = int(rest[pk_pos + 3:]) if pk_pos > 0 else 12

    try:
        p = db.sb.table("catalogo").select("nombre, precio_pack_6, precio_pack_12, precio_pack_24").eq("id", product_id).single().execute().data
    except Exception:
        p = None

    precio = p.get(f"precio_pack_{pack_size}", 0) if p else 0
    nombre = p.get("nombre", "Producto") if p else "Producto"
    sub    = precio * qty

    cart  = session.get("cart", [])
    found = False
    for item in cart:
        if item.get("pid") == product_id and item.get("pk") == pack_size:
            item["qty"] += qty
            item["sub"]  = item["qty"] * precio
            found = True
            break

    if not found:
        cart.append({
            "pid": product_id, "name": nombre,
            "pk": pack_size, "qty": qty, "ppu": precio, "sub": sub,
        })

    session["cart"] = cart
    _save_session(bodega_id, session)
    logger.info(f"Cart +{qty}x PK{pack_size} {nombre} = S/{sub:.2f}")

    cat = session.get("cat", "")
    if cat:
        return await _build_products(bodega_id, session, cat)
    return _build_categories(bodega_id, session)


# ── Cart ──

def _build_cart(bodega_id, session):
    cart  = session.get("cart", [])
    items = []

    if not cart:
        items.append({
            "id": "ADD_MORE",
            "main-content": {"title": "Carrito vacio", "description": "Toca para agregar productos"},
        })
        return _make_response(items, bodega_id)

    total = 0
    for idx, item in enumerate(cart):
        sub = item.get("sub", 0)
        total += sub
        items.append({
            "id": f"REMOVE_{idx}",
            "main-content": {
                "title":       f"{item['qty']}x Pk{item['pk']} {item['name']}",
                "description": f"S/{sub:.2f} — Toca para quitar",
            },
        })

    items.append({
        "id": "ADD_MORE",
        "main-content": {"title": "Agregar mas productos", "description": ""},
    })

    fee = max(total * FEE_RATE, MIN_FEE)
    items.append({
        "id": "CHECKOUT",
        "main-content": {
            "title":       "Confirmar pedido",
            "description": f"Productos: S/{total:.2f} + Fee: S/{fee:.2f}",
        },
    })

    return _make_response(items, bodega_id)


# ── Checkout ──

async def _do_checkout(bodega_id, session):
    cart = session.get("cart", [])
    if not cart:
        return _build_categories(bodega_id, session)

    total = sum(i.get("sub", 0) for i in cart)
    fee   = max(total * FEE_RATE, MIN_FEE)
    dist  = session.get("dist", "a1b2c3d4-0001-4000-8000-000000000001")

    pedido_num = "CRC-000"
    try:
        result = db.sb.table("pedidos").insert({
            "bodega_id": bodega_id, "distribuidor_id": dist,
            "monto_productos": round(total, 2), "fee_monto": round(fee, 2),
            "total": round(total + fee, 2), "estado": "pendiente",
            "items_json": json.dumps(cart, ensure_ascii=False),
        }).execute()
        if result.data:
            pedido_num = f"CRC-{result.data[0]['id']}"
        logger.info(f"Order {pedido_num}: bodega={bodega_id}, total=S/{total + fee:.2f}")
    except Exception as e:
        logger.error(f"Order creation failed: {e}", exc_info=True)

    # Clear session after order
    session["cart"] = []
    _save_session(bodega_id, session)

    return {
        "version": "3.0",
        "screen":  "SUCCESS",
        "data": {
            "message": f"Pedido {pedido_num} confirmado\nTotal: S/{total + fee:.2f}",
        },
    }
