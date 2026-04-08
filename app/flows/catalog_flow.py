"""
Catálogo WhatsApp Flow — Backend endpoint
"""
import os, json, base64, hashlib, secrets
from datetime import datetime, timezone
from cryptography.hazmat.primitives.asymmetric.padding import OAEP, MGF1
from cryptography.hazmat.primitives.hashes import SHA256
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.serialization import load_pem_private_key
from cryptography.hazmat.backends import default_backend
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter()
CARTS = {}

def get_private_key():
    pem = os.getenv("FLOW_PRIVATE_KEY", "").replace("\\n", "\n")
    if not pem: raise ValueError("FLOW_PRIVATE_KEY not set")
    return load_pem_private_key(pem.encode(), password=None, backend=default_backend())

def decrypt_request(encrypted_flow_data, encrypted_aes_key, initial_vector):
    pk = get_private_key()
    aes_key = pk.decrypt(base64.b64decode(encrypted_aes_key), OAEP(mgf=MGF1(algorithm=SHA256()), algorithm=SHA256(), label=None))
    iv = base64.b64decode(initial_vector)
    enc = base64.b64decode(encrypted_flow_data)
    tag, ct = enc[-16:], enc[:-16]
    dec = Cipher(algorithms.AES(aes_key), modes.GCM(iv, tag), backend=default_backend()).decryptor()
    return json.loads(dec.update(ct) + dec.finalize()), aes_key, iv

def encrypt_response(data, aes_key, iv):
    flipped = bytes(~b & 0xFF for b in iv)
    enc = Cipher(algorithms.AES(aes_key), modes.GCM(flipped), backend=default_backend()).encryptor()
    ct = enc.update(json.dumps(data).encode()) + enc.finalize()
    return base64.b64encode(ct + enc.tag).decode()

def get_demo_products():
    return [
        {"id":"NES-001","nombre":"Inca Kola 500ml","categoria":"Bebidas","precio_6":9.60,"precio_12":18.00,"precio_24":34.00},
        {"id":"NES-002","nombre":"Coca-Cola 500ml","categoria":"Bebidas","precio_6":9.60,"precio_12":18.00,"precio_24":34.00},
        {"id":"NES-003","nombre":"Cristal 620ml","categoria":"Bebidas","precio_6":15.00,"precio_12":28.00,"precio_24":52.00},
        {"id":"NES-004","nombre":"Pilsen 620ml","categoria":"Bebidas","precio_6":15.60,"precio_12":29.00,"precio_24":54.00},
        {"id":"NES-005","nombre":"Leche Gloria 400g","categoria":"Lácteos","precio_6":24.00,"precio_12":46.00,"precio_24":88.00},
        {"id":"NES-006","nombre":"Aceite Primor 1L","categoria":"Abarrotes","precio_6":52.80,"precio_12":103.20,"precio_24":200.00},
        {"id":"NES-007","nombre":"Fideos Don Vittorio 500g","categoria":"Abarrotes","precio_6":16.80,"precio_12":32.00,"precio_24":60.00},
        {"id":"NES-008","nombre":"Ajinomén Pollo 80g","categoria":"Abarrotes","precio_6":12.00,"precio_12":22.00,"precio_24":40.00},
        {"id":"NES-009","nombre":"Pampers RN x40","categoria":"Cuidado","precio_6":138.00,"precio_12":264.00,"precio_24":500.00},
        {"id":"NES-010","nombre":"Ariel 400g","categoria":"Cuidado","precio_6":16.80,"precio_12":30.00,"precio_24":55.00},
        {"id":"NES-011","nombre":"Sprite 500ml","categoria":"Bebidas","precio_6":9.60,"precio_12":18.00,"precio_24":34.00},
        {"id":"NES-012","nombre":"Fanta 500ml","categoria":"Bebidas","precio_6":9.60,"precio_12":18.00,"precio_24":34.00},
        {"id":"NES-013","nombre":"Milo 400g","categoria":"Lácteos","precio_6":30.00,"precio_12":56.00,"precio_24":108.00},
        {"id":"NES-014","nombre":"Nescafé Tradición 50g","categoria":"Abarrotes","precio_6":21.00,"precio_12":40.00,"precio_24":76.00},
        {"id":"NES-015","nombre":"Maggi Cubitos x24","categoria":"Abarrotes","precio_6":10.80,"precio_12":20.00,"precio_24":38.00},
    ]

def load_products(supabase):
    try:
        r = supabase.table("catalogo").select("*").eq("activo", True).order("categoria").execute()
        if r.data: return r.data
    except: pass
    return get_demo_products()

def fmt_dropdown(products):
    emojis = {"Bebidas":"🥤","Lácteos":"🥛","Abarrotes":"🛒","Cuidado":"🧴"}
    return [{"id":p["id"],"title":f'{emojis.get(p.get("categoria",""),"📦")} {p["nombre"]}',"description":f'6u S/{p["precio_6"]:.2f} · 12u S/{p["precio_12"]:.2f} · 24u S/{p["precio_24"]:.2f}'} for p in products]

def get_price(p, pack):
    return float(p.get(f'precio_{pack.replace("pk","")}', 0))

def add_to_cart(token, product, pack, qty):
    if token not in CARTS: CARTS[token] = []
    cart = CARTS[token]
    for item in cart:
        if item["product_id"] == product["id"] and item["pack"] == pack:
            item["qty"] += qty
            item["line_total"] = get_price(product, pack) * item["qty"]
            return cart
    price = get_price(product, pack)
    cart.append({"product_id":product["id"],"nombre":product["nombre"],"pack":pack,"qty":qty,"unit_price":price,"line_total":price*qty})
    return cart

def fmt_summary(cart):
    if not cart: return "🛒 Carrito vacío"
    total = sum(i["line_total"] for i in cart)
    return f'🛒 {len(cart)} productos · {sum(i["qty"] for i in cart)} packs · S/{total:.2f}'

def fmt_items(cart):
    if not cart: return "Carrito vacío"
    return "\n".join([f'📦 {i["qty"]}x pk{i["pack"].replace("pk","")} {i["nombre"]} — S/{i["line_total"]:.2f}' for i in cart])

def fmt_totals(cart, linea=500.0):
    total = sum(i["line_total"] for i in cart)
    t = f"━━━━━━━━━━━━━━━━\nTOTAL: S/{total:.2f}\n\n💳 Línea: S/{linea:.2f}"
    if total <= linea: t += "\n✅ Todo financiable"
    else: t += f"\n💰 Financiar: S/{linea:.2f}\n💵 Contado: S/{(total-linea):.2f}"
    return t

def handle_exchange(data, supabase):
    action = data.get("action","")
    token = data.get("flow_token","x")
    products = load_products(supabase) if supabase else get_demo_products()
    dd = fmt_dropdown(products)
    by_id = {p["id"]:p for p in products}

    if action == "INIT":
        return {"screen":"CATALOG","data":{"products":dd,"cart_text":fmt_summary(CARTS.get(token,[]))}}

    if action == "add_item":
        pid = data.get("product","")
        pack = data.get("pack","pk12")
        try: qty = max(1, min(99, int(data.get("qty","1"))))
        except: qty = 1
        prod = by_id.get(pid)
        if not prod:
            return {"screen":"CATALOG","data":{"products":dd,"cart_text":"⚠️ Producto no encontrado"}}
        cart = add_to_cart(token, prod, pack, qty)
        go = isinstance(data.get("go_cart",[]), list) and "yes" in data.get("go_cart",[])
        if go:
            return {"screen":"CART","data":{"cart_items_text":fmt_items(cart),"totals_text":fmt_totals(cart)}}
        pk_label = pack.replace("pk","")
        price = get_price(prod, pack)
        added = f'✅ {qty}x pk{pk_label} {prod["nombre"]} (S/{price*qty:.2f})'
        return {"screen":"CATALOG","data":{"products":dd,"cart_text":f"{added}\n{fmt_summary(cart)}"}}

    return {"screen":"CATALOG","data":{"products":dd,"cart_text":fmt_summary(CARTS.get(token,[]))}}

@router.post("/flows/catalog")
async def catalog_endpoint(request: Request):
    try:
        body = await request.json()
        ef, ek, iv = body.get("encrypted_flow_data",""), body.get("encrypted_aes_key",""), body.get("initial_vector","")
        if not all([ef,ek,iv]): return JSONResponse({"error":"Missing fields"}, status_code=400)
        dec, aes_key, iv_bytes = decrypt_request(ef, ek, iv)
        print(f'[CATALOG] action={dec.get("action")} screen={dec.get("screen")}')
        sb = getattr(request.app.state, "supabase", None)
        resp = handle_exchange(dec, sb)
        return JSONResponse(content=encrypt_response(resp, aes_key, iv_bytes), media_type="text/plain")
    except Exception as e:
        print(f"[CATALOG] Error: {e}")
        import traceback; traceback.print_exc()
        return JSONResponse({"error":str(e)}, status_code=500)
