"""
Circa MVP - FastAPI Application (Full Button UX + PIN Web)
===========================================================
Run: uvicorn main:app --reload --port 8000
Expose: ngrok http 8000
"""
from fastapi import FastAPI, Request, Form, HTTPException
from fastapi.responses import PlainTextResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from twilio.twiml.messaging_response import MessagingResponse
from app.state_machine import handle_message
from app.services.twilio_client import (
    send_whatsapp,
    send_categorias,
    send_productos_bebidas,
    send_productos_lacteos,
    send_productos_abarrotes,
    send_productos_cuidado,
    send_pack_selection,
    send_cantidad,
    send_item_agregado,
    send_carrito_resumen,
    send_monto_financiar,
    send_plazo,
    send_menu,
    CATEGORY_SENDERS,
)
from app.services import db
from pydantic import BaseModel
from app.config import TWILIO_FROM
from datetime import date, timedelta
import logging, json, os

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("circa")

app = FastAPI(title="Circa MVP", version="2.3.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.mount("/static", StaticFiles(directory="static"), name="static")


def _bot_wa_number() -> str:
    return TWILIO_FROM.replace("whatsapp:", "").replace("+", "").strip()

def _pin_url(bodega_id: str, mode: str = "confirm") -> str:
    base = os.getenv("APP_BASE_URL", "http://localhost:8000").rstrip("/")
    return f"{base}/pin?b={bodega_id}&mode={mode}&to={_bot_wa_number()}"



# ══════════════════════════════════════════
# SIGNAL DISPATCHER
# ══════════════════════════════════════════

def dispatch_signal(telefono: str, signal: dict):
    sig = signal.get("signal")

    if sig == "CATEGORIAS":
        send_categorias(telefono)
    elif sig == "PRODUCTOS":
        cat = signal.get("categoria", "bebidas")
        sender = CATEGORY_SENDERS.get(cat, send_productos_bebidas)
        sender(telefono)
    elif sig == "PACK":
        send_pack_selection(telefono, signal["nombre"], signal["p6"], signal["p12"], signal["p24"])
    elif sig == "CANTIDAD":
        send_cantidad(telefono, signal["nombre"], signal["pack_label"], signal["precio"])
    elif sig == "AGREGADO":
        send_item_agregado(telefono, signal["cantidad"], signal["pack_label"], signal["nombre"], signal["subtotal"], signal["cart_total"])
    elif sig == "CARRITO":
        send_carrito_resumen(telefono, signal["items_text"], signal["total"], signal["financiable"])
    elif sig == "MONTO":
        send_monto_financiar(telefono, signal["linea"], signal["total"], signal["financiable"])
    elif sig == "PLAZO":
        send_plazo(telefono, signal["monto"], signal["fee7"], signal["total7"], signal["fee15"], signal["total15"], signal["fee30"], signal["total30"])
    elif sig == "MENU":
        send_menu(telefono, signal["linea"])
    else:
        logger.warning(f"Unknown signal: {sig}")
        send_whatsapp(telefono, "⚠️ Error interno. Escribe MENU para volver.")


# ══════════════════════════════════════════
# TWILIO WEBHOOK
# ══════════════════════════════════════════

@app.post("/webhook/twilio")
async def twilio_webhook(
    From: str = Form(...),
    Body: str = Form(default=""),
    NumMedia: int = Form(default=0),
    MediaUrl0: str = Form(default=None),
    ButtonPayload: str = Form(default=None),
    ButtonText: str = Form(default=None),
    ListReply: str = Form(default=None),
    ListResponseId: str = Form(default=None),
    ListResponseTitle: str = Form(default=None),
):
    telefono = From.replace("whatsapp:", "")
    body = (
        ButtonPayload or ListResponseId or ListReply
        or ButtonText or ListResponseTitle or Body or ""
    ).strip()
    media_url = MediaUrl0

    logger.info(
        f"📩 From: {telefono} | Body: '{body}' | "
        f"ButtonPayload: {ButtonPayload} | ButtonText: {ButtonText} | "
        f"ListReply: {ListReply} | ListResponseId: {ListResponseId} | "
        f"ListResponseTitle: {ListResponseTitle}"
    )

    try:
        responses = handle_message(telefono, body, media_url)

        for resp in responses:
            try:
                if isinstance(resp, dict):
                    dispatch_signal(telefono, resp)
                elif isinstance(resp, str):
                    if resp == "__SHOW_CATEGORIAS__":
                        send_categorias(telefono)
                    elif resp == "__SHOW_PRODUCTOS_BEBIDAS__":
                        send_productos_bebidas(telefono)
                    else:
                        send_whatsapp(telefono, resp)
                else:
                    logger.warning(f"Unknown response type: {type(resp)}")
            except Exception as e:
                logger.error(f"Failed to send: {e}", exc_info=True)

        twiml = MessagingResponse()
        logger.info(f"📤 Sent {len(responses)} message(s)")
        return PlainTextResponse(str(twiml), media_type="text/xml")

    except Exception as e:
        import traceback
        print(f"❌ WEBHOOK ERROR: {type(e).__name__}: {e}", flush=True)
        print(traceback.format_exc(), flush=True)
        logger.error(f"❌ Error: {e}", exc_info=True)
        try:
            send_whatsapp(telefono, "⚠️ Hubo un error. Intenta de nuevo en un momento.")
        except Exception:
            pass
        twiml = MessagingResponse()
        return PlainTextResponse(str(twiml), media_type="text/xml")


# ══════════════════════════════════════════
# API ENDPOINTS
# ══════════════════════════════════════════

@app.get("/api/health")
async def health():
    return {"status": "ok", "service": "circa-mvp", "version": "2.3.0"}

@app.get("/api/debug")
async def debug_check():
    """Temporary debug endpoint — remove after fixing."""
    import os
    key = os.getenv("SUPABASE_SERVICE_KEY", "")
    url = os.getenv("SUPABASE_URL", "")
    results = {
        "_key_info": {
            "length": len(key),
            "first_20": key[:20],
            "last_10": key[-10:] if len(key) > 10 else key,
            "has_newlines": "\n" in key,
            "has_spaces": " " in key,
            "url": url,
        }
    }
    tables = ["sesiones", "bodegas"]
    for t in tables:
        try:
            r = db.sb.table(t).select("*").limit(1).execute()
            results[t] = {"ok": True, "rows": len(r.data)}
        except Exception as e:
            results[t] = {"ok": False, "error": str(e)[:200]}
    return results

# ══════════════════════════════════════════════
# WHATSAPP FLOW ENDPOINTS (Dynamic Data Exchange)
# ══════════════════════════════════════════════

@app.post("/flows/onboarding")
async def flow_onboarding(request: Request):
    """Dynamic endpoint for the Onboarding WhatsApp Flow."""
    from app.flows.crypto import decrypt_request, encrypt_response
    from app.flows.onboarding import handle_onboarding
    
    try:
        body = await request.json()
        flow_data, aes_key, iv = decrypt_request(
            body["encrypted_flow_data"],
            body["encrypted_aes_key"],
            body["initial_vector"],
        )
        
        # Handle the flow logic
        response_data = await handle_onboarding(flow_data)
        
        # Encrypt and return
        encrypted = encrypt_response(response_data, aes_key, iv)
        return PlainTextResponse(encrypted)
    
    except Exception as e:
        logger.error(f"Flow onboarding error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/flows/catalogo")
async def flow_catalogo(request: Request):
    """Dynamic endpoint for the Catálogo WhatsApp Flow."""
    from app.flows.crypto import decrypt_request, encrypt_response
    from app.flows.catalogo import handle_catalogo
    
    try:
        body = await request.json()
        flow_data, aes_key, iv = decrypt_request(
            body["encrypted_flow_data"],
            body["encrypted_aes_key"],
            body["initial_vector"],
        )
        
        # Handle the flow logic
        response_data = await handle_catalogo(flow_data)
        
        # Encrypt and return
        encrypted = encrypt_response(response_data, aes_key, iv)
        return PlainTextResponse(encrypted)
    
    except Exception as e:
        logger.error(f"Flow catalogo error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ══════════════════════════════════════════════
# META CLOUD API WEBHOOK (replaces Twilio webhook)
# ══════════════════════════════════════════════

@app.get("/webhook/meta")
async def meta_webhook_verify(request: Request):
    """Verify webhook subscription from Meta."""
    from app.services.meta_webhook import verify_webhook
    
    mode = request.query_params.get("hub.mode", "")
    token = request.query_params.get("hub.verify_token", "")
    challenge = request.query_params.get("hub.challenge", "")
    
    result = verify_webhook(mode, token, challenge)
    if result:
        return PlainTextResponse(result)
    raise HTTPException(status_code=403, detail="Verification failed")


@app.post("/webhook/meta")
async def meta_webhook_incoming(request: Request):
    """Handle incoming messages from Meta Cloud API."""
    from app.services.meta_webhook import parse_incoming, verify_signature
    from app.services import meta_client
    
    body = await request.json()
    
    # Parse incoming messages
    messages = parse_incoming(body)
    
    for msg in messages:
        telefono = msg["from"]
        body_text = msg["body"]
        media_url = None
        
        # Handle image (DNI photo)
        if msg["type"] == "image" and msg["media_id"]:
            # TODO: Download and store DNI image
            pass
        
        # Handle Flow response
        if body_text == "__FLOW_RESPONSE__" and msg["flow_data"]:
            flow_data = msg["flow_data"]
            logger.info(f"Flow response from {telefono}: {flow_data}")
            
            # Check if it's an order confirmation
            if flow_data.get("status") == "order_confirmed":
                await meta_client.send_order_confirmation(
                    to=telefono,
                    order_number=flow_data.get("order_number", ""),
                    total_credito=flow_data.get("total_credito", 0),
                    pago_contado=flow_data.get("pago_contado", 0),
                )
            elif flow_data.get("status") == "activated":
                bodega = db.get_bodega_by_phone(telefono) or db.get_bodega_by_phone(f"+{telefono}")
                linea = bodega.get("linea_disponible", 500) if bodega else 500
                await meta_client.send_menu(to=telefono, linea_disponible=linea)
            
            # Mark as read
            if msg["message_id"]:
                await meta_client.mark_as_read(msg["message_id"])
            continue
        
        # Handle catalog order (cart submission)
        if body_text == "__ORDER__" and msg["order"]:
            # TODO: Process catalog cart order
            logger.info(f"Catalog order from {telefono}: {msg['order']}")
            continue
        
        # Regular message processing via state machine
        try:
            responses = handle_message(telefono, body_text, media_url)
            
            for resp in responses:
                if isinstance(resp, dict):
                    signal = resp.get("signal", "")
                    
                    # Handle signals — send appropriate message type
                    if signal == "MENU":
                        await meta_client.send_menu(telefono, resp.get("linea", 500))
                    elif signal == "ONBOARDING_FLOW":
                        await meta_client.send_onboarding_flow(
                            telefono, resp.get("bodega_id", ""),
                            resp.get("nombre", ""), resp.get("linea", 500)
                        )
                    elif signal == "CATALOGO_FLOW":
                        await meta_client.send_catalogo_flow(
                            telefono, resp.get("bodega_id", "")
                        )
                    elif signal in ("CATEGORIAS", "PRODUCTOS", "PACK", "CANTIDAD",
                                     "AGREGADO", "CARRITO", "MONTO", "PLAZO"):
                        # Legacy signals from old state machine → redirect to Flow
                        bodega = db.get_bodega_by_phone(telefono) or db.get_bodega_by_phone(f"+{telefono}")
                        if bodega:
                            await meta_client.send_catalogo_flow(telefono, bodega["id"])
                    else:
                        logger.warning(f"Unknown signal: {signal}")
                
                elif isinstance(resp, str):
                    await meta_client.send_text(telefono, resp)
            
        except Exception as e:
            import traceback
            print(f"❌ META WEBHOOK ERROR: {type(e).__name__}: {e}", flush=True)
            print(traceback.format_exc(), flush=True)
            logger.error(f"❌ Error: {e}", exc_info=True)
            await meta_client.send_text(
                telefono,
                "⚠️ Hubo un error. Intenta de nuevo en un momento."
            )
        
        # Mark as read
        if msg["message_id"]:
            await meta_client.mark_as_read(msg["message_id"])
    
    # Always return 200 to Meta (required)
    return {"status": "ok"}


@app.get("/api/pedidos")
async def list_pedidos(estado: str = None):
    q = db.sb.table("pedidos").select("*, bodegas(nombre_comercial, telefono_whatsapp), distribuidores(nombre_comercial)")
    if estado:
        q = q.eq("estado", estado)
    return q.order("created_at", desc=True).limit(50).execute().data

@app.get("/api/pedidos/{pedido_id}")
async def get_pedido(pedido_id: str):
    pedido = db.sb.table("pedidos").select("*, bodegas(nombre_comercial, telefono_whatsapp)").eq("id", pedido_id).single().execute().data
    items = db.sb.table("items_pedido").select("*, catalogo(nombre, marca)").eq("pedido_id", pedido_id).execute().data
    return {"pedido": pedido, "items": items}

@app.post("/api/pedidos/{pedido_id}/estado")
async def update_estado(pedido_id: str, estado: str = Form(...), actor: str = Form(default="distribuidor")):
    valid_transitions = {
        "aprobado": ["despachado"], "despachado": ["en_camino"], "en_camino": ["entregado"],
    }
    pedido = db.sb.table("pedidos").select("estado, bodega_id, numero").eq("id", pedido_id).single().execute().data
    if not pedido:
        raise HTTPException(404, "Pedido no encontrado")
    if estado not in valid_transitions.get(pedido["estado"], []):
        raise HTTPException(400, f"No se puede cambiar de {pedido['estado']} a {estado}")
    db.update_pedido_estado(pedido_id, estado, actor)
    bodega = db.sb.table("bodegas").select("telefono_whatsapp").eq("id", pedido["bodega_id"]).single().execute().data
    from services import messages as msg
    status_msgs = {"despachado": "📦 Tu pedido fue despachado.", "en_camino": "🚚 En camino. Llegada: 2-4 horas.", "entregado": "🎉 ¡Entregado!"}
    try:
        send_whatsapp(bodega["telefono_whatsapp"], msg.msg_status(pedido["numero"], estado, status_msgs.get(estado, "")))
    except Exception as e:
        logger.error(f"Notify failed: {e}")
    return {"ok": True, "nuevo_estado": estado}

@app.get("/api/bodegas")
async def list_bodegas():
    return db.sb.table("bodegas").select("id, ruc, razon_social, nombre_comercial, estado, linea_aprobada, linea_disponible, scoring").order("created_at", desc=True).execute().data

@app.get("/api/bodegas/{bodega_id}")
async def get_bodega(bodega_id: str):
    return db.sb.table("bodegas").select("*").eq("id", bodega_id).single().execute().data

@app.get("/api/catalogo")
async def list_catalogo(distribuidor_id: str = None, marca: str = None, categoria: str = None):
    q = db.sb.table("catalogo").select("*, distribuidores(nombre_comercial)").eq("activo", True)
    if distribuidor_id: q = q.eq("distribuidor_id", distribuidor_id)
    if marca: q = q.eq("marca", marca)
    if categoria: q = q.eq("categoria", categoria)
    return q.execute().data

# ── PIN (web page) ──

class PinVerification(BaseModel):
    bodega_id: str
    pin: str
    mode: str = "confirm"

class PinCreate(BaseModel):
    bodega_id: str
    pin: str

@app.post("/api/pin/create")
async def create_pin_web(data: PinCreate):
    from services.pin import validate_pin_format, hash_pin

    bodega = db.sb.table("bodegas").select("*").eq("id", data.bodega_id).single().execute().data
    if not bodega:
        return {"ok": False, "error": "Bodega no encontrada"}

    valid, error_msg = validate_pin_format(data.pin)
    if not valid:
        return {"ok": False, "error": error_msg}

    pin_hashed = hash_pin(data.pin)
    db.update_bodega(data.bodega_id, {
        "estado": "activo",
        "pin_hash": pin_hashed,
        "pin_intentos": 0,
        "pin_bloqueado_hasta": None,
    })

    bodega_updated = db.sb.table("bodegas").select("id, estado, pin_hash").eq("id", data.bodega_id).single().execute().data
    if not bodega_updated or not bodega_updated.get("pin_hash"):
        return {"ok": False, "error": "No se pudo guardar la clave"}

    return {"ok": True}

@app.post("/api/pin/verify")
async def verify_pin_web(data: PinVerification):
    from services.pin import check_pin

    bodega = db.sb.table("bodegas").select("*").eq("id", data.bodega_id).single().execute().data
    if not bodega:
        return {"ok": False, "error": "Bodega no encontrada"}

    if not bodega.get("pin_hash"):
        return {"ok": False, "error": "La bodega no tiene una clave registrada"}

    success, error_msg, updates = check_pin(data.pin, bodega)
    if updates:
        db.update_bodega(data.bodega_id, updates)

    if not success:
        return {"ok": False, "error": error_msg}

    if data.mode == "confirm":
        telefono = bodega["telefono_whatsapp"]
        session = db.get_session(telefono)
        if not session:
            return {"ok": False, "error": "No hay una sesión activa para confirmar"}

        datos = json.loads(session["datos"]) if isinstance(session["datos"], str) else (session["datos"] or {})
        if session.get("fase") != "pin_confirm":
            return {"ok": False, "error": "La sesión actual no está esperando confirmación de PIN"}

        if datos.get("pedido_id"):
            return {"ok": True, "pedido_id": datos["pedido_id"]}

        cart = datos.get("cart", [])
        term = datos.get("selected_term")
        fin_amt = datos.get("finance_amount")

        if not cart or not term or fin_amt is None:
            return {"ok": False, "error": "Faltan datos para confirmar el pedido"}

        cart_total = sum(i.get("subtotal", 0) for i in cart)
        contado = cart_total - fin_amt

        pedido = db.create_pedido(
            bodega_id=bodega["id"],
            distribuidor_id=bodega["distribuidor_id"],
            items=cart,
            monto_productos=cart_total,
            monto_financiado=fin_amt,
            monto_contado=contado,
            fee_tasa=term["rate"],
            fee_monto=term["fee"],
            plazo_dias=term["days"],
        )
        db.update_pedido_estado(pedido["id"], "aprobado", "pin_web")
        db.clear_carrito(bodega["id"])

        datos["pedido_id"] = pedido["id"]
        datos["pedido_numero"] = pedido["numero"]
        datos["pin_web_confirmed"] = True
        db.upsert_session(telefono, "pin_confirm", datos, bodega["id"])

        return {"ok": True, "pedido_id": pedido["id"], "pedido_numero": pedido["numero"]}

    return {"ok": True}

@app.get("/pin")
async def pin_page():
    return FileResponse("static/pin.html")

# ── PIN RESET ──

class PinReset(BaseModel):
    bodega_id: str

@app.post("/api/pin/reset")
async def reset_pin(data: PinReset):
    bodega = db.sb.table("bodegas").select("telefono_whatsapp").eq("id", data.bodega_id).single().execute().data
    if not bodega:
        return {"ok": False, "error": "Bodega no encontrada"}

    tel = bodega["telefono_whatsapp"]
    db.update_bodega(data.bodega_id, {"pin_hash": None, "pin_intentos": 0, "pin_bloqueado_hasta": None})
    db.upsert_session(tel, "reg_pin", {"bodega_id": data.bodega_id, "ruc": "reset", "is_reset": True}, data.bodega_id)

    try:
        send_whatsapp(
            tel,
            f"🔐 Tu clave fue reseteada.\n\nUsa el teclado seguro para crear una nueva:\n👉 {_pin_url(data.bodega_id, 'create')}"
        )
    except Exception as e:
        logger.error(f"PIN reset notify failed: {e}")

    return {"ok": True}

# ── CART (web catalog → WhatsApp) ──

class CartSubmission(BaseModel):
    bodega_id: str
    items: list

@app.post("/api/catalogo/submit-cart")
async def submit_cart(data: CartSubmission):
    items_list = [dict(i) if not isinstance(i, dict) else i for i in data.items]
    db.save_carrito(data.bodega_id, items_list)
    bodega = db.sb.table("bodegas").select("telefono_whatsapp, linea_disponible").eq("id", data.bodega_id).single().execute().data
    if bodega:
        tel = bodega["telefono_whatsapp"]
        db.upsert_session(tel, "cart_review", {"cart": items_list}, data.bodega_id)
        total = sum(i.get("subtotal", 0) for i in items_list)
        from services import messages as msg
        try:
            send_whatsapp(tel, msg.msg_carrito(items_list, total, bodega["linea_disponible"]))
        except Exception as e:
            logger.error(f"Cart notify failed: {e}")
    return {"ok": True}

@app.get("/api/carrito/{bodega_id}")
async def get_carrito(bodega_id: str):
    cart = db.get_carrito(bodega_id)
    return cart if cart else {"items": []}

@app.get("/catalogo")
async def catalogo_page():
    return FileResponse("static/catalogo.html")

@app.get("/api/cobranza")
async def cobranza_pendiente():
    return db.sb.table("pagos").select("*, pedidos(numero, bodega_id, monto_total_credito, bodegas(nombre_comercial, telefono_whatsapp))").eq("estado", "pendiente").order("fecha_vencimiento").execute().data

# ── DEMO SIMULATION ──

@app.post("/api/demo/simulate-flow/{pedido_id}")
async def simulate_full_flow(pedido_id: str):
    import asyncio
    pedido = db.sb.table("pedidos").select("*, bodegas(telefono_whatsapp, nombre_comercial)").eq("id", pedido_id).single().execute().data
    if not pedido:
        raise HTTPException(404, "Pedido no encontrado")
    tel = pedido["bodegas"]["telefono_whatsapp"]
    from services import messages as msg
    for estado, detalle in [("despachado","📦 Despachado"),("en_camino","🚚 En camino"),("entregado","🎉 ¡Entregado!")]:
        db.update_pedido_estado(pedido_id, estado, "demo")
        try:
            send_whatsapp(tel, msg.msg_status(pedido["numero"], estado, detalle))
        except:
            pass
        await asyncio.sleep(3)
    try:
        send_whatsapp(tel, msg.msg_recordatorio(pedido["bodegas"]["nombre_comercial"], pedido["monto_total_credito"], pedido["fecha_vencimiento"], 5))
    except:
        pass
    return {"ok": True, "message": "Flow simulated"}

# ── RESET DEMO ──

@app.post("/api/demo/reset/{bodega_id}")
async def reset_demo(bodega_id: str):
    db.sb.table("sesiones").delete().eq("bodega_id", bodega_id).execute()
    db.clear_carrito(bodega_id)
    bodega = db.sb.table("bodegas").select("telefono_whatsapp, linea_aprobada").eq("id", bodega_id).single().execute().data
    if bodega:
        db.sb.table("sesiones").delete().eq("telefono", bodega["telefono_whatsapp"]).execute()
    db.sb.table("bodegas").update({
        "estado": "inactivo",
        "pin_hash": None,
        "pin_intentos": 0,
        "pin_bloqueado_hasta": None,
        "contrato_hash": None,
        "contrato_firmado_at": None,
        "linea_disponible": bodega["linea_aprobada"] if bodega else 500,
    }).eq("id", bodega_id).execute()
    return {"ok": True, "message": "Bodega reset for demo"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=True)
