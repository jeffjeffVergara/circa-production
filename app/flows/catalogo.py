"""
WhatsApp Flow Endpoint — Single-Screen Catálogo.
Cart state stored in Supabase (no cart_state field needed in Flow).
"""

import logging
import json
from app.services import db

logger = logging.getLogger("circa.flows.catalogo")


def _sanitize(text, max_len=30):
    """Remove chars that break WhatsApp Flows and truncate."""
    t = text.replace("&", "y").replace("'", "").replace('"', "").replace("\n", " ")
    t = t.replace("·", "-").replace("—", "-").replace("—", "-").replace("·", "-")
    return t[:max_len]

FEE_RATE = 0.03
MIN_FEE = 3.0

CATEGORIES = [
    {"id": "Abarrotes",           "emoji": "🛒"},
    {"id": "Bebidas Calientes",   "emoji": "☕"},
    {"id": "Bebidas",             "emoji": "🥤"},
    {"id": "Cereales",            "emoji": "🥣"},
    {"id": "Confitería",          "emoji": "🍫"},
    {"id": "Lácteos",             "emoji": "🥛"},
    {"id": "Nutrición Infantil",  "emoji": "👶"},
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
        total = sum(i.get("sub", 0) for i in cart)
        items = []
        for i, item in enumerate(cart):
            name = item.get('name','')[:24]
            items.append({
                "id": f"RM{i}",
                "main-content": {
                    "title": f"{item.get('qty',0)}x {name}"[:30],
                    "description": f"S/{item.get('sub',0):.2f}",
                },
            })
        if not items:
            items.append({"id": "BACK_CATS", "main-content": {"title": "Carrito vacio", "description": "Agregar productos"}})
        items.append({"id": "BACK_CATS", "main-content": {"title": "Seguir comprando", "description": ""}})
        items.append({"id": "CHECKOUT", "main-content": {"title": "Pedir todo", "description": f"Total: S/{total:.2f}"}})
        return _make_response(items, bodega_id)

    if selected == "CHECKOUT":
        return await _do_checkout(bodega_id, session)

    if selected == "IGNORADO_PAY_CASH":
        session["pay"] = "contado"
        session["fee_rate"] = 0
        session["plazo"] = 0
        _save_session(bodega_id, session)
        return _build_confirm(bodega_id, session)

    if selected == "PAY_CIRCA":
        return _build_plazos(bodega_id, session)

    if selected.startswith("PLAZO_"):
        dias = int(selected.split("_")[1])
        rates = {7: 0.03, 15: 0.05, 30: 0.07}
        session["pay"] = "circa"
        session["plazo"] = dias
        session["fee_rate"] = rates.get(dias, 0.05)
        _save_session(bodega_id, session)
        return _build_confirm(bodega_id, session)

    if selected == "BACK_PAY":
        return _build_payment(bodega_id, session)

    if selected == "BACK_CART":
        cart = session.get("cart", [])
        total = sum(i.get("sub", 0) for i in cart)
        items = []
        for i, item in enumerate(cart):
            q = item.get("qty", 0)
            n = item.get("name", "")
            s = item.get("sub", 0)
            items.append({"id": f"RM{i}", "main-content": {"title": f"{q}x {n}"[:30], "description": f"S/{s:.2f}"}})
        if not items:
            items.append({"id": "BACK_CATS", "main-content": {"title": "Carrito vacio", "description": "Agregar productos"}})
        items.append({"id": "BACK_CATS", "main-content": {"title": "Seguir comprando", "description": ""}})
        items.append({"id": "CHECKOUT", "main-content": {"title": "Pedir todo", "description": f"Total: S/{total:.2f}"}})
        return _make_response(items, bodega_id)

    if selected == "CONFIRM":
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
    for p in productos[:8]:
        unidades = p.get("unidades") or {}
        if isinstance(unidades, str):
            import json as _json
            unidades = _json.loads(unidades)
        precios = list(unidades.values()) if unidades else []
        min_p = min(precios) if precios else 0
        marca = p.get("marca", "")
        title = _sanitize(p.get("nombre", "Sin nombre"), 30)
        desc = _sanitize(f"S/{min_p:.2f}" if min_p else "Ver detalle", 20)
        items.append({
            "id": f"PROD_{p['id']}",
            "main-content": {
                "title":       title,
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
        "main-content": {"title": "← Volver a categorias", "description": ""},
    })

    badge = _cart_badge(session.get("cart", []))
    if badge:
        items.append(badge)

    return _make_response(items, bodega_id)


# ── Product detail ──

async def _build_product_detail(bodega_id, session, product_id):
    try:
        # Get bodega's distribuidor
        bod = db.sb.table("bodegas").select("distribuidor_id").eq("id", bodega_id).limit(1).execute()
        dist_id = bod.data[0]["distribuidor_id"] if bod.data else None
        # Query from catalogo_distribuidor joined with productos_circa
        cd = db.sb.table("catalogo_distribuidor").select("*, productos_circa(*)").eq("producto_circa_id", product_id).eq("distribuidor_id", dist_id).limit(1).execute()
        if not cd.data:
            p = None
        else:
            row = cd.data[0]
            pc = row.get("productos_circa") or {}
            p = {"id": pc.get("id"), "nombre": pc.get("nombre", "Producto"), "marca": pc.get("marca", ""), "unidades": row.get("unidades") or {}}
    except Exception as e:
        logger.error(f"Product load error: {e}")
        p = None

    if not p:
        return _build_categories(bodega_id, session)

    nombre = p.get("nombre", "Producto")
    marca = p.get("marca", "")
    unidades = p.get("unidades") or {}
    if isinstance(unidades, str):
        import json as _json
        unidades = _json.loads(unidades)
    items  = []

    for unit_key, precio in unidades.items():
        if not precio or precio <= 0:
            continue
        label = unit_key.strip()
        for qty in (1, 2, 5):
            sub = round(precio * qty, 2)
            unit_safe = unit_key.replace(" ", "").upper()
            items.append({
                "id": f"ADD_{qty}_{product_id}_U{unit_safe}",
                "main-content": {
                    "title":       _sanitize(f"{qty}x {label} — S/{sub:.2f}", 30),
                    "description": _sanitize(f"S/{precio:.2f} c/u", 20),
                },
            })

    if not items:
        for qty in (1, 2, 5):
            items.append({
                "id": f"ADD_{qty}_{product_id}_U1",
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
    # Format: ADD_qty_productid_UunitKey  (e.g. ADD_2_abc123_UUNDx1)
    remainder = selected[4:]  # strip "ADD_"
    first_us  = remainder.index("_")
    qty       = int(remainder[:first_us])
    rest      = remainder[first_us + 1:]

    # Find unit marker "_U"
    u_pos = rest.rfind("_U")
    if u_pos > 0:
        product_id = rest[:u_pos]
        unit_key_safe = rest[u_pos + 2:]  # e.g. "UNDx1", "CJAx12"
    else:
        # Legacy PK format fallback
        pk_pos = rest.rfind("_PK")
        product_id = rest[:pk_pos] if pk_pos > 0 else rest
        unit_key_safe = f"PK{rest[pk_pos+3:]}" if pk_pos > 0 else "UNDx1"

    try:
        bod = db.sb.table("bodegas").select("distribuidor_id").eq("id", bodega_id).limit(1).execute()
        dist_id = bod.data[0]["distribuidor_id"] if bod.data else None
        cd = db.sb.table("catalogo_distribuidor").select("unidades, productos_circa(nombre, marca)").eq("producto_circa_id", product_id).eq("distribuidor_id", dist_id).limit(1).execute()
        if cd.data:
            row = cd.data[0]
            pc = row.get("productos_circa") or {}
            p = {"nombre": pc.get("nombre", "Producto"), "marca": pc.get("marca", ""), "unidades": row.get("unidades") or {}}
        else:
            p = None
    except Exception:
        p = None

    # Find matching unit and price
    precio = 0
    unit_label = unit_key_safe
    if p:
        unidades = p.get("unidades") or {}
        if isinstance(unidades, str):
            unidades = json.loads(unidades)
        # Match by removing spaces: "UND x 1" -> "UNDx1" == unit_key_safe
        for uk, up in unidades.items():
            if uk.replace(" ", "").upper() == unit_key_safe.upper():
                precio = up
                unit_label = uk
                break
        if not precio and unidades:
            unit_label, precio = next(iter(unidades.items()))

    nombre = p.get("nombre", "Producto") if p else "Producto"
    sub    = round(precio * qty, 2)

    cart  = session.get("cart", [])
    found = False
    for item in cart:
        if item.get("pid") == product_id and item.get("pk") == unit_label:
            item["qty"] += qty
            item["sub"]  = round(item["qty"] * precio, 2)
            found = True
            break

    if not found:
        cart.append({
            "pid": product_id, "name": nombre,
            "pk": unit_label, "qty": qty, "ppu": precio, "sub": sub,
        })

    session["cart"] = cart
    _save_session(bodega_id, session)
    logger.info(f"Cart +{qty}x {unit_label} {nombre} = S/{sub:.2f}")

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
                "title":       f"{item['qty']}x {item['name']}"[:30],
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
    dist  = session.get("dist", "a1b2c3d4-0001-4000-8000-000000000001")

    # Build cart summary
    items_text = "\n".join(f"▸ {i['qty']}x *{i['name']}*\n   S/{i['sub']:.2f}" for i in cart)

    pedido_id = "000"
    try:
        result = db.sb.table("pedidos").insert({
            "bodega_id": bodega_id, "distribuidor_id": dist,
            "monto_productos": round(total, 2),
            "total": round(total, 2), "estado": "borrador",
            "items_json": json.dumps(cart, ensure_ascii=False),
        }).execute()
        if result.data:
            pedido_id = result.data[0]["id"]
        logger.info(f"Order {pedido_id}: bodega={bodega_id}, total=S/{total:.2f}")
    except Exception as e:
        logger.error(f"Order creation failed: {e}", exc_info=True)

    # Send payment options via WhatsApp message (outside Flow)
    try:
        from app.services import meta_client
        bodega = db.sb.table("bodegas").select("telefono_whatsapp").eq("id", bodega_id).limit(1).execute()
        if bodega.data:
            phone = bodega.data[0].get("telefono_whatsapp", "").replace("+", "")
            if phone:
                import asyncio
                asyncio.create_task(_send_payment_options(phone, pedido_id, total, items_text, bodega_id))
    except Exception as e:
        logger.error(f"Payment msg error: {e}")

    session["cart"] = []
    session["pedido_id"] = str(pedido_id)
    _save_session(bodega_id, session)

    return {
        "version": "3.0",
        "screen": "SUCCESS",
        "data": {
            "message": f"Pedido registrado\nTotal: S/{total:.2f}\nRevisa las opciones de pago",
        },
    }


async def _send_payment_options(phone, pedido_id, total, items_text, bodega_id=None):
    """Send financing options after Flow closes."""
    import asyncio
    await asyncio.sleep(2)
    from app.services import meta_client

    linea = 0
    if bodega_id:
        try:
            b = db.sb.table("bodegas").select("linea_disponible").eq("id", bodega_id).limit(1).execute()
            if b.data:
                linea = b.data[0].get("linea_disponible", 0)
        except Exception:
            pass

    pid = str(pedido_id)[:8]
    fin100 = min(total, linea)
    fin50 = min(round(linea * 0.5, 2), total)
    fin25 = min(round(linea * 0.25, 2), total)

    if linea >= total:
        await meta_client.send_text(phone,
            f"\U0001f6d2 *TU PEDIDO*\n━━━━━━━━━━━━━━━━━━\n{items_text}\n━━━━━━━━━━━━━━━━━━\n"
            f"*TOTAL: S/{total:.2f}*\n"
            f"Credito disponible: *S/{linea:.2f}*")
        await meta_client.send_list(
            to=phone,
            body="Cuanto de tu linea Circa deseas usar para financiar?",
            button_text="Elegir opcion",
            sections=[{"title": "Financiamiento", "rows": [
                {"id": f"CONTADO_{pid}", "title": "Pagar todo al contado", "description": "No financiar"},
                {"id": f"FIN25_{pid}", "title": f"25% linea — S/{fin25:.2f}", "description": f"Contado: S/{round(total-fin25,2):.2f}"},
                {"id": f"FIN50_{pid}", "title": f"50% linea — S/{fin50:.2f}", "description": f"Contado: S/{round(total-fin50,2):.2f}"},
                {"id": f"FIN100_{pid}", "title": "Usar toda mi linea", "description": f"S/{min(total,linea):.2f} con Circa"},
            ]}])
    elif linea > 0:
        contado_min = total - linea
        await meta_client.send_text(phone,
            f"\U0001f6d2 *TU PEDIDO*\n━━━━━━━━━━━━━━━━━━\n{items_text}\n━━━━━━━━━━━━━━━━━━\n"
            f"*TOTAL: S/{total:.2f}*\n"
            f"Credito disponible: *S/{linea:.2f}*\n"
            f"Minimo al contado: S/{contado_min:.2f}")
        await meta_client.send_list(
            to=phone,
            body="Cuanto de tu linea Circa deseas usar para financiar?",
            button_text="Elegir opcion",
            sections=[{"title": "Financiamiento", "rows": [
                {"id": f"CONTADO_{pid}", "title": "Pagar todo al contado", "description": "Sin financiamiento"},
                {"id": f"FIN25_{pid}", "title": f"25% linea — S/{fin25:.2f}", "description": f"Contado: S/{round(total-fin25,2):.2f}"},
                {"id": f"FIN50_{pid}", "title": f"50% linea — S/{fin50:.2f}", "description": f"Contado: S/{round(total-fin50,2):.2f}"},
                {"id": f"FIN100_{pid}", "title": "Usar todo mi credito", "description": f"S/{linea:.2f} con Circa"},
            ]}])
    else:
        tel_fmt = f"+{phone}" if not phone.startswith("+") else phone
        db.sb.table("sesiones").delete().eq("telefono", tel_fmt).execute()
        db.sb.table("sesiones").insert({
            "telefono": tel_fmt, "fase": "pin_pago",
            "datos": json.dumps({"pedido_id": str(pedido_id), "dias": 0, "rate": 0, "monto": total}),
            "bodega_id": bodega_id,
        }).execute()
        await meta_client.send_text(phone,
            f"\U0001f6d2 *TU PEDIDO*\n━━━━━━━━━━━━━━━━━━\n{items_text}\n━━━━━━━━━━━━━━━━━━\n"
            f"TOTAL: S/{total:.2f}\n"
            f"Sin linea disponible. Solo contado.\n\n"
            f"Ingresa tu clave Circa para confirmar:")

    logger.info(f"Payment options sent to {phone}, linea={linea}")

# ── Payment & Confirmation ──

def _build_payment(bodega_id, session):
    total = sum(i.get("sub", 0) for i in session.get("cart", []))
    items = [
        {"id": "PAY_CIRCA", "main-content": {"title": "Pagar con Circa", "description": "Credito 7-30 dias"}},
        {"id": "PAY_CASH", "main-content": {"title": "Pagar al contado", "description": "Sin fee adicional"}},
        {"id": "BACK_CART", "main-content": {"title": "Volver al carrito", "description": f"Total: S/{total:.2f}"}},
    ]
    return _make_response(items, bodega_id)

def _build_plazos(bodega_id, session):
    total = sum(i.get("sub", 0) for i in session.get("cart", []))
    f7 = max(total * 0.03, 5); f15 = max(total * 0.05, 5); f30 = max(total * 0.07, 5)
    items = [
        {"id": "PLAZO_7", "main-content": {"title": "7 dias", "description": f"Fee S/{f7:.2f} - Total S/{total+f7:.2f}"}},
        {"id": "PLAZO_15", "main-content": {"title": "15 dias", "description": f"Fee S/{f15:.2f} - Total S/{total+f15:.2f}"}},
        {"id": "PLAZO_30", "main-content": {"title": "30 dias", "description": f"Fee S/{f30:.2f} - Total S/{total+f30:.2f}"}},
        {"id": "BACK_PAY", "main-content": {"title": "Opciones de pago", "description": ""}},
    ]
    return _make_response(items, bodega_id)

def _build_confirm(bodega_id, session):
    cart = session.get("cart", [])
    total = sum(i.get("sub", 0) for i in cart)
    fee_rate = session.get("fee_rate", 0)
    fee = max(total * fee_rate, 5) if fee_rate > 0 else 0
    pay = session.get("pay", "contado")
    plazo = session.get("plazo", 0)
    items = []
    for item in cart:
        items.append({"id": "INFO", "main-content": {"title": f"{item['qty']}x {item['name']}", "description": f"S/{item['sub']:.2f}"}})
    if pay == "circa":
        items.append({"id": "INFO2", "main-content": {"title": f"Credito Circa {plazo} dias", "description": f"Fee: S/{fee:.2f}"}})
    items.append({"id": "CONFIRM", "main-content": {"title": "Confirmar pedido", "description": f"Total: S/{total+fee:.2f}"}})
    items.append({"id": "BACK_PAY", "main-content": {"title": "Cambiar pago", "description": ""}})
    return _make_response(items, bodega_id)
