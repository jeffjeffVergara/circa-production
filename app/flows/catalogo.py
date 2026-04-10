"""
WhatsApp Flow Endpoint — Single-Screen Catálogo.
Cart state stored in Supabase (no cart_state field needed in Flow).
v2 — Simplified UX, editable cart, payment + plazo selection.
"""

import logging
import json
from app.services import db

logger = logging.getLogger("circa.flows.catalogo")

# ── Fee schedule ──
FEES = {7: 0.03, 15: 0.05, 30: 0.07}
MIN_FEE = 5.0

CATEGORIES = [
    {"id": "Abarrotes",         "emoji": "🛒"},
    {"id": "Bebidas Calientes", "emoji": "☕"},
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

    session = _load_session(bodega_id)

    if selected in ("BACK_CATS", "ADD_MORE"):
        session["cat"] = ""
        session.pop("pay_mode", None)
        _save_session(bodega_id, session)
        return _build_categories(bodega_id, session)

    if selected == "BACK_PRODS":
        cat = session.get("cat", "")
        if cat:
            return await _build_products(bodega_id, session, cat)
        return _build_categories(bodega_id, session)

    if selected == "BACK_CART":
        return _build_cart(bodega_id, session)

    if selected == "VIEW_CART":
        return _build_cart(bodega_id, session)

    if selected.startswith("REMOVE_"):
        try:
            idx = int(selected.split("_", 1)[1])
            cart = session.get("cart", [])
            if 0 <= idx < len(cart):
                removed = cart.pop(idx)
                logger.info(f"Removed from cart: {removed.get('name','?')}")
            session["cart"] = cart
            _save_session(bodega_id, session)
        except (ValueError, IndexError):
            pass
        return _build_cart(bodega_id, session)

    if selected == "CHECKOUT":
        return _build_payment_options(bodega_id, session)

    if selected.startswith("PAY_"):
        return _build_plazo_options(bodega_id, session, selected)

    if selected.startswith("PLAZO_"):
        return _build_confirmation(bodega_id, session, selected)

    if selected == "CONFIRM":
        return await _do_checkout(bodega_id, session)

    if selected.startswith("SUMMARY") or selected.startswith("ITEM_") or selected == "PAY_INFO":
        return _build_confirmation(bodega_id, session, f"PLAZO_{session.get('plazo', 0)}")

    if selected.startswith("ADD_"):
        return await _do_add_to_cart(bodega_id, session, selected)

    if selected.startswith("PROD_"):
        prod_id = selected[5:]
        return await _build_product_detail(bodega_id, session, prod_id)

    return await _build_products(bodega_id, session, selected)


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
    n = sum(i.get("qty", 0) for i in cart)
    return {
        "id": "VIEW_CART",
        "main-content": {
            "title":       f"🛒 Carrito ({n} uds)",
            "description": f"Total: S/{total:.2f} — Toca para ver",
        },
    }


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
        unit_price = None
        for pk in (6, 12, 24):
            precio = p.get(f"precio_pack_{pk}")
            if precio:
                ppu = precio / pk
                if unit_price is None or ppu < unit_price:
                    unit_price = ppu
        desc = f"Desde S/{unit_price:.2f}/ud" if unit_price else "Ver opciones"
        items.append({
            "id": f"PROD_{p['id']}",
            "main-content": {
                "title":       p.get("nombre", "Sin nombre"),
                "description": desc,
            },
        })

    if not items:
        items.append({
            "id": "BACK_CATS",
            "main-content": {"title": "No hay productos", "description": "Volver"},
        })

    items.append({
        "id": "BACK_CATS",
        "main-content": {"title": "← Categorías", "description": ""},
    })

    badge = _cart_badge(session.get("cart", []))
    if badge:
        items.append(badge)

    return _make_response(items, bodega_id)


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

    packs = []
    for pk in (6, 12, 24):
        precio = p.get(f"precio_pack_{pk}")
        if precio:
            packs.append((pk, precio))

    if packs:
        for pk, precio in packs:
            ppu = precio / pk
            for qty in (1, 2, 5):
                total = precio * qty
                units = pk * qty
                items.append({
                    "id": f"ADD_{qty}_{product_id}_PK{pk}",
                    "main-content": {
                        "title":       f"{units} uds — S/{total:.2f}",
                        "description": f"{qty} pack{'s' if qty > 1 else ''} de {pk} · S/{ppu:.2f}/ud",
                    },
                })
    else:
        for qty in (1, 3, 6, 12):
            items.append({
                "id": f"ADD_{qty}_{product_id}_PK1",
                "main-content": {
                    "title":       f"Agregar {qty} unidad{'es' if qty > 1 else ''}",
                    "description": nombre,
                },
            })

    items.append({
        "id": "BACK_PRODS",
        "main-content": {"title": "← Volver", "description": ""},
    })

    badge = _cart_badge(session.get("cart", []))
    if badge:
        items.append(badge)

    return _make_response(items, bodega_id)


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


def _build_cart(bodega_id, session):
    cart  = session.get("cart", [])
    items = []

    if not cart:
        items.append({
            "id": "ADD_MORE",
            "main-content": {"title": "🛒 Carrito vacío", "description": "Toca para agregar productos"},
        })
        return _make_response(items, bodega_id)

    total = 0
    for idx, item in enumerate(cart):
        sub   = item.get("sub", 0)
        total += sub
        units = item.get("qty", 0) * item.get("pk", 1)
        items.append({
            "id": f"REMOVE_{idx}",
            "main-content": {
                "title":       f"❌ {item['name']}",
                "description": f"{units} uds · S/{sub:.2f} — Toca para quitar",
            },
        })

    items.append({
        "id": "ADD_MORE",
        "main-content": {"title": "➕ Agregar más productos", "description": ""},
    })

    items.append({
        "id": "CHECKOUT",
        "main-content": {
            "title":       f"✅ Pedir todo — S/{total:.2f}",
            "description": f"{len(cart)} producto{'s' if len(cart) > 1 else ''} en tu carrito",
        },
    })

    return _make_response(items, bodega_id)


def _build_payment_options(bodega_id, session):
    cart  = session.get("cart", [])
    total = sum(i.get("sub", 0) for i in cart)

    if not cart:
        return _build_categories(bodega_id, session)

    items = [
        {
            "id": "PAY_CIRCA",
            "main-content": {
                "title":       "💳 100% Circa (crédito)",
                "description": f"Financiar S/{total:.2f} — elige plazo",
            },
        },
        {
            "id": "PAY_5050",
            "main-content": {
                "title":       "💳💵 50% Circa + 50% Contado",
                "description": f"Crédito S/{total / 2:.2f} + Contado S/{total / 2:.2f}",
            },
        },
        {
            "id": "PAY_CONTADO",
            "main-content": {
                "title":       "💵 100% Contado",
                "description": f"Pagar S/{total:.2f} al recibir — sin fee",
            },
        },
        {
            "id": "BACK_CART",
            "main-content": {"title": "← Volver al carrito", "description": ""},
        },
    ]

    return _make_response(items, bodega_id)


def _build_plazo_options(bodega_id, session, pay_mode):
    cart  = session.get("cart", [])
    total = sum(i.get("sub", 0) for i in cart)

    session["pay_mode"] = pay_mode
    _save_session(bodega_id, session)

    if pay_mode == "PAY_CONTADO":
        session["plazo"] = 0
        session["fee_rate"] = 0
        _save_session(bodega_id, session)
        return _build_confirmation(bodega_id, session, "PLAZO_0")

    financed = total if pay_mode == "PAY_CIRCA" else total / 2

    items = []
    for days, rate in sorted(FEES.items()):
        fee = max(financed * rate, MIN_FEE)
        pct = int(rate * 100)
        items.append({
            "id": f"PLAZO_{days}",
            "main-content": {
                "title":       f"📅 {days} días — fee {pct}%",
                "description": f"Fee: S/{fee:.2f} · Total: S/{financed + fee:.2f}",
            },
        })

    items.append({
        "id": "CHECKOUT",
        "main-content": {"title": "← Cambiar forma de pago", "description": ""},
    })

    return _make_response(items, bodega_id)


def _build_confirmation(bodega_id, session, plazo_selected):
    cart     = session.get("cart", [])
    total    = sum(i.get("sub", 0) for i in cart)
    pay_mode = session.get("pay_mode", "PAY_CIRCA")

    try:
        days = int(plazo_selected.replace("PLAZO_", ""))
    except ValueError:
        days = 0

    session["plazo"] = days
    rate = FEES.get(days, 0)
    session["fee_rate"] = rate

    if pay_mode == "PAY_CONTADO":
        financed = 0
        contado  = total
        fee      = 0
    elif pay_mode == "PAY_5050":
        financed = total / 2
        contado  = total / 2
        fee      = max(financed * rate, MIN_FEE) if rate else 0
    else:
        financed = total
        contado  = 0
        fee      = max(financed * rate, MIN_FEE) if rate else 0

    session["financed"] = round(financed, 2)
    session["contado"]  = round(contado, 2)
    session["fee"]      = round(fee, 2)
    _save_session(bodega_id, session)

    grand_total = total + fee

    items = []
    items.append({
        "id": "SUMMARY_HDR",
        "main-content": {
            "title":       "📋 Resumen de tu pedido",
            "description": f"{len(cart)} producto{'s' if len(cart) > 1 else ''}",
        },
    })

    for item in cart:
        units = item.get("qty", 0) * item.get("pk", 1)
        items.append({
            "id": f"ITEM_{item.get('pid','')}",
            "main-content": {
                "title":       f"  {item['name']} ({units} uds)",
                "description": f"  S/{item.get('sub', 0):.2f}",
            },
        })

    if pay_mode == "PAY_CONTADO":
        pay_desc = f"💵 Contado: S/{total:.2f}"
    elif pay_mode == "PAY_5050":
        pay_desc = f"💳 Crédito S/{financed:.2f} ({days}d) + 💵 S/{contado:.2f}"
    else:
        pay_desc = f"💳 Crédito {days} días"

    items.append({
        "id": "PAY_INFO",
        "main-content": {
            "title":       pay_desc,
            "description": f"Fee: S/{fee:.2f}" if fee > 0 else "Sin fee",
        },
    })

    items.append({
        "id": "CONFIRM",
        "main-content": {
            "title":       f"✅ CONFIRMAR — S/{grand_total:.2f}",
            "description": "Toca para enviar tu pedido",
        },
    })

    items.append({
        "id": "CHECKOUT",
        "main-content": {"title": "← Cambiar forma de pago", "description": ""},
    })

    return _make_response(items, bodega_id)


async def _do_checkout(bodega_id, session):
    cart = session.get("cart", [])
    if not cart:
        return _build_categories(bodega_id, session)

    total    = sum(i.get("sub", 0) for i in cart)
    fee      = session.get("fee", 0)
    financed = session.get("financed", total)
    contado  = session.get("contado", 0)
    plazo    = session.get("plazo", 0)
    fee_rate = session.get("fee_rate", 0)
    dist     = session.get("dist", "a1b2c3d4-0001-4000-8000-000000000001")

    pedido_num = "CRC-000"
    try:
        result = db.sb.table("pedidos").insert({
            "bodega_id":       bodega_id,
            "distribuidor_id": dist,
            "monto_productos": round(total, 2),
            "monto_financiado": round(financed, 2),
            "monto_contado":   round(contado, 2),
            "fee_tasa":        fee_rate,
            "fee_monto":       round(fee, 2),
            "plazo_dias":      plazo if plazo > 0 else None,
            "total":           round(total + fee, 2),
            "estado":          "borrador",
            "items_json":      json.dumps(cart, ensure_ascii=False),
        }).execute()
        if result.data:
            pedido_num = f"CRC-{str(result.data[0]['id'])[:8]}"
        logger.info(f"Order {pedido_num}: bodega={bodega_id}, total=S/{total + fee:.2f}, plazo={plazo}d")
    except Exception as e:
        logger.error(f"Order creation failed: {e}", exc_info=True)

    session["cart"] = []
    session.pop("pay_mode", None)
    session.pop("plazo", None)
    session.pop("fee_rate", None)
    session.pop("financed", None)
    session.pop("contado", None)
    session.pop("fee", None)
    _save_session(bodega_id, session)

    lines = [f"✅ Pedido {pedido_num}"]
    lines.append(f"Productos: S/{total:.2f}")
    if fee > 0:
        lines.append(f"Fee ({int(fee_rate*100)}%): S/{fee:.2f}")
    lines.append(f"TOTAL: S/{total + fee:.2f}")
    if plazo > 0:
        lines.append(f"Plazo: {plazo} días")

    return {
        "version": "3.0",
        "screen":  "SUCCESS",
        "data": {
            "message": "\n".join(lines),
        },
    }
