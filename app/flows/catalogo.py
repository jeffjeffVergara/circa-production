"""
WhatsApp Flow Endpoint — Single-Screen Catálogo.
Cart state stored in Supabase (no cart_state field needed in Flow).
"""

import logging
import json
from app.services import db
from app.services.representante_comms import nombre_para_comunicar_representante

logger = logging.getLogger("circa.flows.catalogo")


def _normalize_unit_key(s: str) -> str:
    """Alphanumeric uppercase key for fuzzy match (UND x 1 vs UNDX1)."""
    return "".join(c for c in (s or "").upper() if c.isalnum())


def _sanitize(text, max_len=30):
    """Remove chars that break WhatsApp Flows and truncate."""
    t = text.replace("&", "y").replace("'", "").replace('"', "").replace("\n", " ")
    t = t.replace("·", "-").replace("—", "-").replace("—", "-").replace("·", "-")
    return t[:max_len]

from app.services import fees as circa_fees

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

    bodega_id = (data.get("bodega_id") or "").strip()
    if not bodega_id:
        return _make_response(
            [{"id": "ERR", "main-content": {"title": "Abre el catálogo desde WhatsApp", "description": "Falta bodega"}}],
            "",
        )

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

    if selected in ("IGNORADO_PAY_CASH", "PAY_CASH"):
        session["pay"] = "contado"
        session["fee_rate"] = 0
        session["plazo"] = 0
        _save_session(bodega_id, session)
        return _build_confirm(bodega_id, session)

    if selected == "PAY_CIRCA":
        return _build_plazos(bodega_id, session)

    if selected.startswith("PLAZO_"):
        dias = int(selected.split("_")[1])
        q = circa_fees.calcular_comision_por_plan(
            sum(i.get("sub", 0) for i in session.get("cart", [])), dias
        )
        session["pay"] = "circa"
        session["plazo"] = dias
        session["fee_rate"] = q["rate"]
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
    # Catálogo: DIMAX para todos; pedido: Zoom si es_test (ver distribuidor_routing)
    from app.services.distribuidor_routing import (
        distribuidor_id_para_catalogo,
        distribuidor_id_para_pedido,
    )

    bodega_row = db.get_bodega_routing(bodega_id)
    dist_cat = distribuidor_id_para_catalogo(bodega_row)
    dist_ped = distribuidor_id_para_pedido(bodega_row) if bodega_row else ""
    session["dist"] = dist_ped
    session["dist_catalogo"] = dist_cat
    logger.info(
        "Bodega %s: catalogo=%s pedido=%s es_test=%s",
        bodega_id, dist_cat, dist_ped, (bodega_row or {}).get("es_test"),
    )
    dist = dist_cat
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
        dist_id = db.get_distribuidor_de_bodega(bodega_id)
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
        dist_id = db.get_distribuidor_de_bodega(bodega_id)
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
        # Second pass: normalized alphanumeric (handles subtle key mismatches)
        if not precio and unidades:
            want = _normalize_unit_key(unit_key_safe)
            for uk, up in unidades.items():
                if _normalize_unit_key(uk) == want:
                    precio = up
                    unit_label = uk
                    break
        # Never silently pick "first unit" — avoids 1 UND + 1 CAJA -> 2x wrong unit
        if not precio and unidades:
            logger.warning(
                "Cart add: no unit match for product=%s unit_key_safe=%s keys=%s",
                product_id,
                unit_key_safe,
                list(unidades.keys()),
            )
            return await _build_product_detail(bodega_id, session, product_id)

    if precio <= 0:
        logger.warning(
            "Cart add: precio<=0 product=%s bodega=%s (sin unidad válida o catálogo incompleto)",
            product_id,
            bodega_id,
        )
        if p:
            return await _build_product_detail(bodega_id, session, product_id)
        return _build_categories(bodega_id, session)

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

    fee = circa_fees.calcular_comision_por_plan(total, 7)["fee"]
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
    from app.services.distribuidor_routing import distribuidor_id_para_pedido

    bodega_row = db.get_bodega_routing(bodega_id)
    dist = distribuidor_id_para_pedido(bodega_row) if bodega_row else session.get("dist")

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


def _f_linea(v) -> float:
    try:
        return float(v if v is not None else 0)
    except (TypeError, ValueError):
        return 0.0


async def _send_payment_options(phone, pedido_id, total, items_text, bodega_id=None):
    """Send financing options. Plazo único: 7 días (sin menú 15/30)."""
    import asyncio
    from datetime import datetime, timedelta
    await asyncio.sleep(2)
    from app.services import meta_client

    linea = 0.0
    bodega_row = None
    tipo_op = "venta"
    if bodega_id:
        try:
            b = db.sb.table("bodegas").select(
                "linea_disponible, nombre_comercial, razon_social, "
                "representante_legal, representante_nombre_corto"
            ).eq("id", bodega_id).limit(1).execute()
            if b.data:
                bodega_row = b.data[0]
                linea = _f_linea(bodega_row.get("linea_disponible"))
        except Exception as e:
            logger.error(f"bodega load for payment options: {e}", exc_info=True)
    try:
        pe = db.sb.table("pedidos").select("tipo_operacion").eq("id", str(pedido_id)).limit(1).execute()
        if pe.data:
            tipo_op = pe.data[0].get("tipo_operacion") or "venta"
    except Exception:
        pass

    nick_rep = nombre_para_comunicar_representante(bodega_row, None)
    saludo_pedido = f"{nick_rep}, tu" if nick_rep else "Tu"

    pid = str(pedido_id)[:8]
    fecha_pago = (datetime.now() + timedelta(days=7)).strftime("%d/%m/%Y")
    is_preventa = tipo_op == "preventa"

    # Máximo financiable a 7 días (única opción de financiamiento principal)
    financiable = round(min(total, linea), 2)
    tiers = []
    if financiable > 0:
        fee_max = circa_fees.calcular_comision_por_plan(financiable, 7)["fee"]
        paga_hoy_max = round(total - financiable, 2)
        paga_7d_max = round(financiable + fee_max, 2)
        if financiable >= total:
            title_max = f"\U0001f4b3 Financiar todo S/{financiable:.2f}"
        else:
            title_max = f"\U0001f4b3 Financiar S/{financiable:.2f} (m\u00e1x.)"
        tiers.append({
            "id": f"FIN100_{pid}",
            "monto": financiable,
            "title": title_max,
            "description": f"\U0001f4b0Hoy S/{paga_hoy_max:.2f} | Cuota S/{paga_7d_max:.2f} en 7d",
        })

    # En preventa: flujo simple (máx 7d + contado). En venta: tiers fijos menores.
    if not is_preventa:
        for monto_fin in [500, 400, 300, 200, 100]:
            if monto_fin < financiable and monto_fin <= total:
                fee = circa_fees.calcular_comision_por_plan(monto_fin, 7)["fee"]
                paga_hoy = round(total - monto_fin, 2)
                paga_7d = round(monto_fin + fee, 2)
                tiers.append({
                    "id": f"FINFIJO{monto_fin}_{pid}",
                    "monto": monto_fin,
                    "title": f"Financiar S/{monto_fin}",
                    "description": f"\U0001f4b0Hoy S/{paga_hoy:.2f} | \U0001f4b3Cuota S/{paga_7d:.2f} en 7d",
                })

    header = (
        f"\U0001f6d2 *{saludo_pedido} {'pre-venta está lista' if is_preventa else 'pedido está listo'} para confirmar*\n"
        f"\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n"
        f"{items_text}\n"
        f"\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n"
        f"*TOTAL: S/{total:.2f}*"
        + (f"\n\U0001f4c5 Plazo Circa: *7 días* (vence {fecha_pago})" if is_preventa and financiable > 0 else "")
    )

    if linea > 0 and tiers:
        sent = await meta_client.send_text(phone, header)
        if sent is None:
            logger.warning(f"payment options text failed for {phone} (posible fuera de ventana 24h)")
            return False

        rows = []
        for t in tiers:
            rows.append({"id": t["id"], "title": t["title"], "description": t["description"]})
        rows.append({"id": f"CONTADO_{pid}", "title": f"\U0001f4b5 Pagar todo al contado", "description": f"S/{total:.2f} al chofer"})
        if not is_preventa:
            rows.append({"id": f"EDITAR_{pid}", "title": "\u270f\ufe0f Editar carrito", "description": "Volver al catalogo"})

        lst = await meta_client.send_list(
            to=phone,
            body="¿Cómo quieres pagar? (financiamiento a 7 días)",
            button_text="Ver opciones",
            sections=[{"title": "Opciones de pago", "rows": rows}])
        logger.info(f"Payment options sent to {phone}, linea={linea}, preventa={is_preventa}")
        return lst is not None
    elif linea <= 0:
        tel_fmt = f"+{phone}" if not phone.startswith("+") else phone
        db.sb.table("pedidos").update({"estado": "preventa_borrador"}).eq(
            "id", str(pedido_id)
        ).eq("estado", "preventa_confirmada").execute()
        db.sb.table("sesiones").delete().eq("telefono", tel_fmt).execute()
        db.sb.table("sesiones").insert({
            "telefono": tel_fmt, "fase": "pin_pago",
            "datos": json.dumps({"pedido_id": str(pedido_id), "dias": 0, "rate": 0, "monto": total}),
            "bodega_id": bodega_id,
        }).execute()
        sent = await meta_client.send_text(phone,
            f"{header}\n"
            f"Sin credito disponible. Solo contado.\n\n"
            f"Ingresa tu clave Circa para confirmar:")
        return sent is not None
    else:
        sent = await meta_client.send_text(phone, header)
        if sent is None:
            return False
        rows = [{"id": f"CONTADO_{pid}", "title": f"Pago todo hoy S/{total:.0f}", "description": "Sin financiamiento"}]
        if total <= linea:
            fee = circa_fees.calcular_comision_por_plan(total, 7)["fee"]
            paga_7d = round(total + fee, 2)
            desc7 = f"Hoy S/0, cuota S/{paga_7d:.2f} el {fecha_pago} (fee S/{fee:.2f})"
            rows.append({
                "id": f"FIN100_{pid}",
                "title": "Pago total a 7 días",
                "description": desc7[:72],
            })
        if not is_preventa:
            rows.append({"id": f"EDITAR_{pid}", "title": "Editar carrito", "description": "Volver al catalogo"})
        lst = await meta_client.send_list(
            to=phone,
            body="¿Cómo quieres pagar? (financiamiento a 7 días)",
            button_text="Ver opciones",
            sections=[{"title": "Opciones de pago", "rows": rows}])
        logger.info(f"Payment options sent to {phone}, linea={linea}")
        return lst is not None


def _hours_since_last_inbound(telefono: str) -> float | None:
    """Horas desde el último mensaje inbound del bodeguero. None si nunca escribió."""
    from datetime import datetime, timezone
    tel = telefono if telefono.startswith("+") else f"+{telefono.lstrip('+')}"
    tel_alt = tel.lstrip("+")
    try:
        rows = (
            db.sb.table("messages")
            .select("created_at")
            .eq("direction", "inbound")
            .or_(f"telefono.eq.{tel},telefono.eq.{tel_alt},telefono.eq.+{tel_alt}")
            .order("created_at", desc=True)
            .limit(1)
            .execute()
            .data
            or []
        )
        if not rows:
            return None
        raw = rows[0]["created_at"]
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - dt).total_seconds() / 3600.0
    except Exception as e:
        logger.warning(f"_hours_since_last_inbound: {e}")
        return None


async def _send_preventa_template(phone: str, bodega: dict, total: float, pedido_id: str) -> bool:
    """Plantilla Meta para avisar fuera de la ventana de 24h de sesión."""
    import os
    from app.services import meta_client
    from app.services.representante_comms import nombre_para_comunicar_representante

    template = (os.getenv("PREVENTA_NOTIFY_TEMPLATE") or "preventa_lista_v1").strip()
    if not template:
        return False

    nombre = nombre_para_comunicar_representante(bodega) or (
        bodega.get("nombre_comercial") or bodega.get("razon_social") or "Hola"
    )
    total_txt = f"{total:.2f}"
    # Body vars típicas: {{1}} nombre, {{2}} total, {{3}} plazo
    components = [{
        "type": "body",
        "parameters": [
            {"type": "text", "text": str(nombre)[:60]},
            {"type": "text", "text": total_txt},
            {"type": "text", "text": "7 días"},
        ],
    }]
    # Probar idiomas comunes (como cobranza)
    for lang in ("es", "es_MX", "es_ES"):
        data = await meta_client.send_template(phone, template, language=lang, components=components)
        if data:
            logger.info(f"preventa template OK {template}/{lang} -> {phone} pedido={pedido_id}")
            return True
    logger.error(f"preventa template FAILED {template} -> {phone} (¿plantilla aprobada en Meta?)")
    return False


async def notificar_preventa_bodeguero(pedido_id: str):
    """Envía opciones de pago al bodeguero cuando se crea una preventa.

    Si el bodeguero no escribió en las últimas 24h (ventana Meta; umbral
    configurable PREVENTA_SESSION_HOURS, default 24; producto pide ~48h),
    usa plantilla aprobada (PREVENTA_NOTIFY_TEMPLATE) para abrir el contacto.
    """
    import json as _json
    import os
    try:
        p = db.sb.table("pedidos").select(
            "id, items_json, monto_productos, total_pedido, bodega_id, tipo_operacion"
        ).eq("id", pedido_id).limit(1).execute()
        if not p.data:
            logger.error(f"notificar_preventa: pedido {pedido_id} not found")
            return
        pedido = p.data[0]

        bodega_id = pedido["bodega_id"]
        total = float(pedido.get("monto_productos") or pedido.get("total_pedido") or 0)
        if total <= 0:
            logger.warning(f"notificar_preventa: pedido {pedido_id} total=0, skip")
            return

        b = db.sb.table("bodegas").select(
            "telefono_whatsapp, pin_hash, nombre_comercial, razon_social, "
            "representante_legal, representante_nombre_corto"
        ).eq("id", bodega_id).limit(1).execute()
        if not b.data:
            logger.error(f"notificar_preventa: bodega {bodega_id} not found")
            return
        bodega = b.data[0]

        phone = (bodega.get("telefono_whatsapp") or "").replace("+", "").replace(" ", "")
        if not phone:
            return
        if len(phone) == 9:
            phone = f"51{phone}"

        items_raw = pedido.get("items_json")
        if isinstance(items_raw, str):
            try:
                items_raw = _json.loads(items_raw)
            except Exception:
                items_raw = []

        item_lines = []
        for item in (items_raw or []):
            qty = item.get("cantidad", 0)
            nombre = item.get("nombre", item.get("descripcion", "?"))
            sub = item.get("subtotal", 0)
            regalo = " \U0001f381" if item.get("es_bonificacion") else ""
            item_lines.append(f"\u25b8 {qty}x {nombre}\n  S/{sub:.2f}{regalo}")
        items_text = "\n".join(item_lines) if item_lines else "(sin detalle de productos)"

        # Dejar menú listo: al responder, verá "Pagar mi preventa"
        try:
            tel_fmt = f"+{phone}" if not phone.startswith("+") else phone
            db.upsert_session(tel_fmt, "menu", {}, bodega_id)
        except Exception as e:
            logger.warning(f"notificar_preventa session: {e}")

        session_hours = float(os.getenv("PREVENTA_SESSION_HOURS") or "24")
        # Producto: avisar aunque no haya escrito ~48h → umbral de sesión Meta es 24h;
        # usamos el menor entre env y 48 para forzar template si está frío.
        cold_hours = float(os.getenv("PREVENTA_COLD_HOURS") or "48")
        hours = _hours_since_last_inbound(phone)
        is_cold = hours is None or hours >= min(session_hours, cold_hours)

        if is_cold:
            logger.info(
                f"notificar_preventa: cold contact hours={hours} -> template "
                f"pedido={pedido_id} phone={phone}"
            )
            ok = await _send_preventa_template(phone, bodega, total, pedido_id)
            if ok:
                return
            # Si no hay plantilla, intentar sesión igual (puede fallar fuera de ventana)
            logger.warning("notificar_preventa: template falló, intento sesión libre")

        if not bodega.get("pin_hash"):
            # Sin PIN: al menos avisar con template o texto corto
            if not is_cold:
                from app.services import meta_client
                await meta_client.send_text(
                    phone,
                    f"🛒 *Tu pre-venta está lista* (S/{total:.2f})\n\n"
                    f"Activa tu clave Circa o escribe *MENU* → *Pagar mi preventa*.",
                )
            logger.info(f"notificar_preventa: bodega {bodega_id} sin PIN, aviso corto")
            return

        ok = await _send_payment_options(phone, pedido_id, total, items_text, bodega_id)
        if not ok and not is_cold:
            # Falló sesión (ventana cerrada) → template
            await _send_preventa_template(phone, bodega, total, pedido_id)
        logger.info(f"notificar_preventa: OK session={ok} -> {phone} pedido {pedido_id}")

    except Exception as e:
        logger.error(f"notificar_preventa error: {e}", exc_info=True)

# ── Payment & Confirmation ──

def _build_payment(bodega_id, session):
    total = sum(i.get("sub", 0) for i in session.get("cart", []))
    items = [
        {"id": "PAY_CASH", "main-content": {"title": "Pagar al contado", "description": "Sin fee adicional"}},
        {"id": "PAY_CIRCA", "main-content": {"title": "Pagar con Circa", "description": "Plazos 7 a 30 días"}},
        {"id": "BACK_CART", "main-content": {"title": "Volver al carrito", "description": f"Total: S/{total:.2f}"}},
    ]
    return _make_response(items, bodega_id)

def _build_plazos(bodega_id, session):
    total = sum(i.get("sub", 0) for i in session.get("cart", []))
    q7 = circa_fees.calcular_comision_por_plan(total, 7)
    q15 = circa_fees.calcular_comision_por_plan(total, 15)
    q30 = circa_fees.calcular_comision_por_plan(total, 30)
    items = [
        {"id": "PLAZO_7", "main-content": {"title": "7 días", "description": f"Cargo Circa S/{q7['fee']:.2f} ({q7['rate_pct']}) · Total S/{q7['total']:.2f}"}},
        {"id": "PLAZO_15", "main-content": {"title": "15 días", "description": f"Cargo Circa S/{q15['fee']:.2f} ({q15['rate_pct']}) · Total S/{q15['total']:.2f}"}},
        {"id": "PLAZO_30", "main-content": {"title": "30 días", "description": f"Cargo Circa S/{q30['fee']:.2f} ({q30['rate_pct']}) · Total S/{q30['total']:.2f}"}},
        {"id": "BACK_PAY", "main-content": {"title": "Opciones de pago", "description": ""}},
    ]
    return _make_response(items, bodega_id)

def _build_confirm(bodega_id, session):
    cart = session.get("cart", [])
    total = sum(i.get("sub", 0) for i in cart)
    fee_rate = session.get("fee_rate", 0)
    fee = circa_fees.calcular_comision_por_plan(total, plazo)["fee"] if fee_rate > 0 and plazo else 0
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
