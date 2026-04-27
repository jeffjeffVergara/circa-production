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
from app.routes.distribuidor import router as distribuidor_router
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
from app.services.fees import calculate_fee
from pydantic import BaseModel
from app.config import TWILIO_FROM
from datetime import date, timedelta
import logging, json, os

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("circa")

app = FastAPI(title="Circa MVP", version="2.3.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.mount("/static", StaticFiles(directory="static"), name="static")
app.include_router(distribuidor_router)


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

async def _gen_order_number(bodega_id, tipo_operacion: str = "venta"):
    """Generate next order number by operation type."""
    prefix = "PRV" if tipo_operacion == "preventa" else "CRC"
    try:
        r = (
            db.sb.table("pedidos")
            .select("numero")
            .eq("bodega_id", bodega_id)
            .eq("tipo_operacion", tipo_operacion)
            .not_.is_("numero", "null")
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        if r.data and r.data[0].get("numero"):
            last = r.data[0]["numero"]
            n = int(last.split("-")[1]) + 1
        else:
            n = 1
        return f"{prefix}-{n:03d}"
    except:
        return f"{prefix}-{__import__('random').randint(100,999)}"


def _is_draft_status(estado: str) -> bool:
    return estado in ("borrador", "preventa_borrador")


def _confirmed_status_for(tipo_operacion: str) -> str:
    return "preventa_confirmada" if tipo_operacion == "preventa" else "confirmado"


@app.get("/api/health")
async def health():
    return {"status": "ok", "service": "circa-mvp", "version": "2.3.0"}

@app.get("/privacy")
async def privacy():
    return PlainTextResponse("""
POLÍTICA DE PRIVACIDAD — CIRCA (PALI S.A.C.)
Última actualización: 6 de abril de 2026

Circa, operado por PALI S.A.C. (RUC 20600627806), recopila datos personales (RUC, DNI, nombre, dirección, teléfono, historial de pedidos y pagos) exclusivamente para la evaluación crediticia, gestión de pedidos y cobranza. Los datos son almacenados en servidores seguros y no se comparten con terceros sin consentimiento, salvo requerimiento legal. El usuario puede ejercer sus derechos ARCO escribiendo a contacto@circa.pe. Cumplimos con la Ley 29733 de Protección de Datos Personales del Perú.

Contacto: contacto@circa.pe | +51 986 311 567
""", media_type="text/plain; charset=utf-8")

@app.get("/terms")
async def terms():
    return PlainTextResponse("""
CONDICIONES DEL SERVICIO — CIRCA (PALI S.A.C.)
Última actualización: 6 de abril de 2026

Circa es una plataforma de crédito embebido para bodegas peruanas operada por PALI S.A.C. Al usar el servicio, el usuario acepta las condiciones del contrato de línea de crédito revolving, incluyendo comisiones (3% a 7 días, 5% a 15 días, 7% a 30 días), interés moratorio (0.30% diario), y las políticas de cobranza. El servicio está sujeto a las leyes de la República del Perú, jurisdicción de Lima.

Contacto: contacto@circa.pe | +51 986 311 567
""", media_type="text/plain; charset=utf-8")

@app.get("/data-deletion")
@app.post("/data-deletion")
async def data_deletion(request: Request = None):
    return PlainTextResponse("""
ELIMINACIÓN DE DATOS — CIRCA (PALI S.A.C.)

Para solicitar la eliminación de tus datos personales, envía un mensaje a contacto@circa.pe con tu RUC y número de teléfono. Procesaremos tu solicitud en un plazo máximo de 30 días hábiles conforme a la Ley 29733.

Contacto: contacto@circa.pe | +51 986 311 567
""", media_type="text/plain; charset=utf-8")

@app.get("/delete")
@app.post("/delete")
async def data_deletion_short(request: Request = None):
    return await data_deletion(request)

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
        logger.info(f"RESPONSE TO ENCRYPT: {json.dumps(response_data, default=str)}")
        
        # Encrypt and return
        encrypted = encrypt_response(response_data, aes_key, iv)
        return PlainTextResponse(encrypted)
    
    except Exception as e:
        logger.error(f"Flow catalogo error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/flows/pin")
async def flow_pin(request: Request):
    """Dynamic endpoint for the PIN creation WhatsApp Flow."""
    from app.flows.crypto import decrypt_request, encrypt_response
    from app.flows.pin_flow import handle_pin_flow
    
    try:
        body = await request.json()
        flow_data, aes_key, iv = decrypt_request(
            body["encrypted_flow_data"],
            body["encrypted_aes_key"],
            body["initial_vector"],
        )
        
        response_data = await handle_pin_flow(flow_data)
        
        encrypted = encrypt_response(response_data, aes_key, iv)
        return PlainTextResponse(encrypted)
    
    except Exception as e:
        logger.error(f"Flow PIN error: {e}", exc_info=True)
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
    from app.services.analytics import track_message
    
    body = await request.json()
    
    # Parse incoming messages
    messages = parse_incoming(body)
    
    for msg in messages:
        telefono = msg["from"]
        # Meta sends "51993557282", DB stores "+51993557282"
        if not telefono.startswith("+"):
            telefono = f"+{telefono}"
        body_text = msg["body"]
        media_url = None
        bodega_msg = db.get_bodega_by_phone(telefono) or db.get_bodega_by_phone(f"+{telefono}")
        bodega_id_msg = bodega_msg.get("id") if bodega_msg else None
        track_message(
            telefono=telefono,
            direction="inbound",
            bodega_id=bodega_id_msg,
            message_id=msg.get("message_id", ""),
            message_type=msg.get("type", ""),
            content=body_text,
            metadata={
                "button_id": msg.get("button_id", ""),
                "list_id": msg.get("list_id", ""),
                "has_flow_data": bool(msg.get("flow_data")),
            },
        )
        
        # Handle image (selfie for biometria)
        if msg["type"] == "image" and msg["media_id"]:
            media_url = msg["media_id"]  # Pass media_id to state machine
        
        # Handle Flow response
        if body_text == "__FLOW_RESPONSE__" and msg["flow_data"]:
            flow_data = msg["flow_data"]
            logger.info(f"Flow response from {telefono}: {flow_data}")
            
            # ── PIN Flow response ──
            if "pin" in flow_data and "pin_confirm" in flow_data:
                pin = flow_data["pin"]
                pin_confirm = flow_data["pin_confirm"]
                
                if pin != pin_confirm:
                    await meta_client.send_text(telefono, "❌ Las claves no coinciden. Intenta de nuevo.")
                    # Re-send PIN flow
                    bodega = db.get_bodega_by_phone(telefono)
                    if bodega:
                        await meta_client.send_pin_request(telefono, "create", bodega["id"])
                elif len(pin) != 4 or not pin.isdigit():
                    await meta_client.send_text(telefono, "❌ La clave debe ser 4 dígitos. Intenta de nuevo.")
                else:
                    # Valid PIN — activate account
                    from app.services.pin import hash_pin
                    bodega = db.get_bodega_by_phone(telefono)
                    if bodega:
                        pin_hashed = hash_pin(pin)
                        db.update_bodega(bodega["id"], {
                            "estado": "activo",
                            "pin_hash": pin_hashed,
                            "pin_intentos": 0,
                        })
                        import hashlib
                        contract_hash = hashlib.sha256(f"{bodega['id']}|{telefono}|pin_flow".encode()).hexdigest()
                        db.sign_contract(bodega["id"], contract_hash[:16])
                        db.upsert_session(telefono, "menu", {}, bodega["id"])
                        await meta_client.send_cuenta_activa(telefono, bodega.get("linea_disponible", 500))
                        logger.info(f"Bodega {bodega['id']} activated via PIN Flow")
            
            # ── Order confirmation ──
            elif flow_data.get("status") == "order_confirmed":
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
        
        # ── Handle payment replies (buttons or list) ──
        btn = msg.get("button_id", "") or msg.get("list_id", "") or ""
        if btn.startswith("EDITAR_"):
            try:
                bod = db.sb.table("bodegas").select("id").eq("telefono_whatsapp", telefono).limit(1).execute()
                bod_id = bod.data[0]["id"] if bod.data else None
                if bod_id:
                    await meta_client.send_catalogo_flow(telefono, bod_id)
            except Exception as e:
                logger.error(f"EDITAR error: {e}", exc_info=True)
            if msg.get("message_id"):
                await meta_client.mark_as_read(msg["message_id"])
            continue

        if btn.startswith("PRECONF_"):
            try:
                bod = db.sb.table("bodegas").select("id").eq("telefono_whatsapp", telefono).limit(1).execute()
                bod_id = bod.data[0]["id"] if bod.data else None
                r = (
                    db.sb.table("pedidos")
                    .select("id, monto_productos")
                    .eq("bodega_id", bod_id)
                    .eq("estado", "preventa_borrador")
                    .order("created_at", desc=True)
                    .limit(1)
                    .execute()
                ) if bod_id else type("X",(),{"data":[]})()
                if r.data:
                    pedido = r.data[0]
                    monto = pedido["monto_productos"]
                    db.sb.table("sesiones").delete().eq("telefono", telefono).execute()
                    db.sb.table("sesiones").insert({
                        "telefono": telefono,
                        "fase": "pin_pago",
                        "datos": json.dumps({"pedido_id": pedido["id"], "dias": 0, "rate": 0, "monto": monto}),
                        "bodega_id": bod_id,
                    }).execute()
                    await meta_client.send_text(
                        telefono,
                        f"🔐 *Confirmar pre-venta*\n\n"
                        f"Ingresa tu clave Circa para confirmar la pre-venta por S/{monto:.2f}.",
                    )
                    await meta_client.send_pin_request(telefono, mode="verify", bodega_id=bod_id)
                else:
                    await meta_client.send_text(telefono, "No encontré una pre-venta pendiente.")
            except Exception as e:
                logger.error(f"PRECONF handler error: {e}", exc_info=True)
                await meta_client.send_text(telefono, "Error al confirmar pre-venta. Intenta de nuevo.")
            if msg.get("message_id"):
                await meta_client.mark_as_read(msg["message_id"])
            continue

        if btn.startswith("CONTADO_"):
            try:
                bod = db.sb.table("bodegas").select("id").eq("telefono_whatsapp", telefono).limit(1).execute()
                bod_id = bod.data[0]["id"] if bod.data else None
                r = (
                    db.sb.table("pedidos")
                    .select("id, monto_productos")
                    .eq("bodega_id", bod_id)
                    .in_("estado", ["borrador", "preventa_borrador"])
                    .order("created_at", desc=True)
                    .limit(1)
                    .execute()
                ) if bod_id else type("X",(),{"data":[]})()
                if r.data:
                    pedido = r.data[0]
                    monto = pedido["monto_productos"]
                    # Store intent in session, ask PIN
                    db.sb.table("sesiones").delete().eq("telefono", telefono).execute()
                    db.sb.table("sesiones").insert({
                        "telefono": telefono,
                        "fase": "pin_pago",
                        "datos": json.dumps({"pedido_id": pedido["id"], "dias": 0, "rate": 0, "monto": monto}),
                        "bodega_id": bod_id,
                    }).execute()
                    await meta_client.send_text(telefono,
                        f"💵 *Pago al contado — S/{monto:.2f}*\n\n"
                        f"Ingresa tu clave Circa de 4 dígitos para confirmar:")
                    await meta_client.send_pin_request(telefono, mode="verify", bodega_id=bod_id)
                else:
                    await meta_client.send_text(telefono, "No encontré el pedido.")
            except Exception as e:
                logger.error(f"Contado handler error: {e}", exc_info=True)
                await meta_client.send_text(telefono, "Error al confirmar.")
            if msg["message_id"]:
                await meta_client.mark_as_read(msg["message_id"])
            continue
        if btn == "YA_PAGUE":
            try:
                await meta_client.send_text(telefono,
                    "🎉 *¡Pago registrado!*\n\n"
                    "Verificación en las próximas horas.\n"
                    "Tu tope se renueva cuando Circa confirme el pago.\n\n"
                    "Escribe *MENU* para volver al menú principal.")
            except Exception as e:
                logger.error(f"YA_PAGUE error: {e}")
            if msg["message_id"]:
                await meta_client.mark_as_read(msg["message_id"])
            continue
        if btn.startswith("FINFIJO"):
            try:
                import re as _re
                from datetime import datetime, timedelta
                monto_match = _re.search(r"FINFIJO(\d+)_", btn)
                fin_amt = int(monto_match.group(1)) if monto_match else 0
                bod = db.sb.table("bodegas").select("id, linea_disponible").eq("telefono_whatsapp", telefono).limit(1).execute()
                bod_id = bod.data[0]["id"] if bod.data else None
                r = (
                    db.sb.table("pedidos")
                    .select("id, monto_productos")
                    .eq("bodega_id", bod_id)
                    .in_("estado", ["borrador", "preventa_borrador"])
                    .order("created_at", desc=True)
                    .limit(1)
                    .execute()
                ) if bod_id else type("X",(),{"data":[]})()
                if r.data and fin_amt > 0:
                    pedido = r.data[0]
                    total = pedido["monto_productos"]
                    contado = round(total - fin_amt, 2)
                    dias = 7
                    rate = 0.03
                    fee = max(round(fin_amt * rate, 2), 3.0)
                    fecha_venc = (datetime.now() + timedelta(days=dias)).strftime("%d/%m/%Y")
                    db.sb.table("sesiones").delete().eq("telefono", telefono).execute()
                    db.sb.table("sesiones").insert({
                        "telefono": telefono, "fase": "pin_pago",
                        "datos": json.dumps({"pedido_id": pedido["id"], "dias": dias, "rate": rate, "monto": fin_amt}),
                        "bodega_id": bod_id,
                    }).execute()
                    total_pagar = contado + fin_amt + fee
                    await meta_client.send_text(telefono,
                        f"\U0001f4b3 *Resumen de pago*\n\n"
                        f"\U0001f69a Hoy al contado al repartidor: *S/{contado:.2f}*\n"
                        f"\U0001f4b3 Cuota Circa S/{fin_amt + fee:.2f} — pagar antes del {fecha_venc}\n\n"
                        f"*Total a pagar: S/{total_pagar:.2f}*\n\n"
                        f"Confirma con tu clave de 4 digitos.")
                    await meta_client.send_pin_request(telefono, mode="verify", bodega_id=bod_id)
            except Exception as e:
                logger.error(f"FINFIJO error: {e}")
            if msg.get("message_id"):
                await meta_client.mark_as_read(msg["message_id"])
            continue
        if btn.startswith("FIN100_") or btn.startswith("FIN50_") or btn.startswith("FIN25_"):
            try:
                bod = db.sb.table("bodegas").select("id, linea_disponible").eq("telefono_whatsapp", telefono).limit(1).execute()
                bod_id = bod.data[0]["id"] if bod.data else None
                linea = bod.data[0].get("linea_disponible", 0) if bod.data else 0
                r = (
                    db.sb.table("pedidos")
                    .select("id, monto_productos")
                    .eq("bodega_id", bod_id)
                    .in_("estado", ["borrador", "preventa_borrador"])
                    .order("created_at", desc=True)
                    .limit(1)
                    .execute()
                ) if bod_id else type("X",(),{"data":[]})()
                if r.data:
                    pedido = r.data[0]
                    total = pedido["monto_productos"]
                    if btn.startswith("FIN100_"):
                        fin_amt = min(linea, total)
                    elif btn.startswith("FIN50_"):
                        fin_amt = min(round(linea * 0.5, 2), total)
                    else:
                        fin_amt = min(round(linea * 0.25, 2), total)
                    contado = round(total - fin_amt, 2)
                    fee7 = calculate_fee(fin_amt, 7)["fee"]
                    fee15 = calculate_fee(fin_amt, 15)["fee"]
                    fee30 = calculate_fee(fin_amt, 30)["fee"]
                    pid = str(pedido["id"])[:8]
                    db.sb.table("sesiones").delete().eq("telefono", telefono).execute()
                    db.sb.table("sesiones").insert({
                        "telefono": telefono, "fase": "fin_plazo",
                        "datos": json.dumps({"pedido_id": pedido["id"], "fin_amt": fin_amt, "contado": contado, "total": total}),
                        "bodega_id": bod_id,
                    }).execute()
                    await meta_client.send_list(
                        to=telefono,
                        body=f"Financiar: *S/{fin_amt:.2f}*\nAl contado: S/{contado:.2f}\n\nElige plazo:",
                        button_text="Ver plazos",
                        sections=[{"title": "Plazo de pago", "rows": [
                            {"id": f"PAY7_{pid}", "title": "7 días (3%)", "description": f"Cargo Circa S/{fee7:.2f} · Total S/{fin_amt+fee7:.2f}"},
                            {"id": f"PAY15_{pid}", "title": "15 días (5%)", "description": f"Cargo Circa S/{fee15:.2f} · Total S/{fin_amt+fee15:.2f}"},
                            {"id": f"PAY30_{pid}", "title": "30 días (7%)", "description": f"Cargo Circa S/{fee30:.2f} · Total S/{fin_amt+fee30:.2f}"},
                        ]}],
                    )
                else:
                    await meta_client.send_text(telefono, "No encontré el pedido.")
            except Exception as e:
                logger.error(f"FIN handler error: {e}", exc_info=True)
                await meta_client.send_text(telefono, "Error. Intenta de nuevo.")
            if msg["message_id"]:
                await meta_client.mark_as_read(msg["message_id"])
            continue
        if btn == "ACEPTO":
            try:
                from app.config import now_peru
                from app.services.contract_generator import generate_contract
                bodega_ac = db.get_bodega_by_phone(telefono)
                if bodega_ac:
                    bod_id = bodega_ac["id"]
                    dist_nombre = "Red de distribuidores Circa"
                    if bodega_ac.get("distribuidor_id"):
                        dist_r = db.sb.table("distribuidores").select("nombre_comercial").eq("id", bodega_ac["distribuidor_id"]).limit(1).execute()
                        if dist_r.data:
                            dist_nombre = dist_r.data[0]["nombre_comercial"]
                    now = now_peru()
                    contract_path, contract_hash = generate_contract({
                        "razon_social": bodega_ac.get("razon_social", ""),
                        "ruc": bodega_ac.get("ruc", ""),
                        "representante_legal": bodega_ac.get("representante_legal", ""),
                        "dni_representante": bodega_ac.get("dni_representante", ""),
                        "direccion_fiscal": bodega_ac.get("direccion_fiscal", ""),
                        "direccion_despacho": bodega_ac.get("direccion_despacho", ""),
                        "email": bodega_ac.get("email", ""),
                        "linea_aprobada": bodega_ac.get("linea_aprobada", 500),
                        "nombre_comercial": bodega_ac.get("nombre_comercial", ""),
                        "distribuidor_nombre": dist_nombre,
                        "telefono": telefono.replace("+51", "").replace("+", ""),
                        "fecha_firma": now.strftime("%d/%m/%Y"),
                        "hora_firma": now.strftime("%H:%M:%S"),
                    })
                    nombre = bodega_ac.get("nombre_comercial") or bodega_ac.get("razon_social", "Bodega")
                    await meta_client.send_contract_document(telefono, contract_path, nombre)
                    db.sb.table("bodegas").update({
                        "contrato_hash": contract_hash,
                        "contrato_firmado_at": now.isoformat(),
                    }).eq("id", bod_id).execute()
                    import os
                    try: os.remove(contract_path)
                    except: pass
                    await meta_client.send_pin_request(telefono, mode="create", bodega_id=bod_id)
                    # Update session so state machine doesn't interfere
                    db.upsert_session(telefono, "reg_pin", {"bodega_id": bod_id}, bod_id)
                    logger.info(f"Contract signed for bodega {bod_id}, hash={contract_hash}")
                else:
                    await meta_client.send_text(telefono, "Error. Escribe MENU para empezar.")
            except Exception as e:
                logger.error(f"ACEPTO handler error: {e}", exc_info=True)
                await meta_client.send_text(telefono, "Error al procesar. Intenta de nuevo.")
            if msg["message_id"]:
                await meta_client.mark_as_read(msg["message_id"])
            continue
        if btn == "PEDIDO":
            try:
                bodega_ped = db.get_bodega_by_phone(telefono)
                if bodega_ped:
                    await meta_client.send_catalogo_flow(telefono, bodega_ped["id"], tipo_operacion="venta")
                else:
                    await meta_client.send_text(telefono, "Escribe MENU para empezar.")
            except Exception as e:
                logger.error(f"PEDIDO handler error: {e}", exc_info=True)
            if msg["message_id"]:
                await meta_client.mark_as_read(msg["message_id"])
            continue
        if btn == "PREVENTA":
            try:
                bodega_pv = db.get_bodega_by_phone(telefono)
                if bodega_pv:
                    await meta_client.send_catalogo_flow(telefono, bodega_pv["id"], tipo_operacion="preventa")
                else:
                    await meta_client.send_text(telefono, "Escribe MENU para empezar.")
            except Exception as e:
                logger.error(f"PREVENTA handler error: {e}", exc_info=True)
            if msg["message_id"]:
                await meta_client.mark_as_read(msg["message_id"])
            continue
        if btn == "REPETIR":
            try:
                bodega_rep = db.get_bodega_by_phone(telefono)
                if bodega_rep:
                    # Check if there's a last order
                    last = db.sb.table("pedidos").select("items_json").eq("bodega_id", bodega_rep["id"]).not_.is_("items_json", "null").order("created_at", desc=True).limit(1).execute()
                    if last.data and last.data[0].get("items_json"):
                        await meta_client.send_text(telefono, "📋 Tu ultimo pedido. Abre el catalogo para repetirlo:")
                    await meta_client.send_catalogo_flow(telefono, bodega_rep["id"])
                else:
                    await meta_client.send_text(telefono, "No tienes pedidos anteriores. Escribe MENU.")
            except Exception as e:
                logger.error(f"REPETIR handler error: {e}", exc_info=True)
            if msg["message_id"]:
                await meta_client.mark_as_read(msg["message_id"])
            continue
        if btn.startswith("PAY7_") or btn.startswith("PAY15_") or btn.startswith("PAY30_"):
            pedido_short = btn.split("_", 1)[1]
            if btn.startswith("PAY7"):
                dias, rate = 7, 0.03
            elif btn.startswith("PAY15"):
                dias, rate = 15, 0.05
            else:
                dias, rate = 30, 0.07
            try:
                # Find pedido by bodega phone (most recent borrador)
                bod = db.sb.table("bodegas").select("id").eq("telefono_whatsapp", telefono).limit(1).execute()
                bod_id = bod.data[0]["id"] if bod.data else None
                r = (
                    db.sb.table("pedidos")
                    .select("id, monto_productos, total, items_json")
                    .eq("bodega_id", bod_id)
                    .in_("estado", ["borrador", "preventa_borrador"])
                    .order("created_at", desc=True)
                    .limit(1)
                    .execute()
                ) if bod_id else type("X",(),{"data":[]})()
                if r.data:
                    pedido = r.data[0]
                    # Check session for fin_amt
                    ses_fin = db.sb.table("sesiones").select("datos").eq("telefono", telefono).limit(1).execute()
                    fin_amt = pedido["monto_productos"]
                    contado = 0
                    if ses_fin.data and ses_fin.data[0].get("datos"):
                        sd = json.loads(ses_fin.data[0]["datos"]) if isinstance(ses_fin.data[0]["datos"], str) else ses_fin.data[0]["datos"]
                        if sd.get("fin_amt"):
                            fin_amt = sd["fin_amt"]
                            contado = sd.get("contado", 0)
                    monto = fin_amt
                    _qfee = calculate_fee(float(monto), int(dias))
                    fee = _qfee["fee"]
                    rate = _qfee["rate"]
                    from datetime import datetime, timedelta
                    venc = (datetime.now() + timedelta(days=dias)).strftime("%d/%m/%Y")
                    # Store intent in session, ask PIN
                    db.sb.table("sesiones").delete().eq("telefono", telefono).execute()
                    db.sb.table("sesiones").insert({
                        "telefono": telefono,
                        "fase": "pin_pago",
                        "datos": json.dumps({"pedido_id": pedido["id"], "dias": dias, "rate": rate, "monto": monto, "fee": round(fee, 2), "venc": venc}),
                        "bodega_id": bod_id,
                    }).execute()
                    # Send summary then PIN Flow
                    await meta_client.send_text(
                        telefono,
                        f"💳 *Circa {dias} dias*\n"
                        f"Financiar: S/{monto:.2f}\n"
                        f"Fee ({int(rate*100)}%): S/{fee:.2f}\n"
                        f"*TOTAL: S/{monto+fee:.2f}*\n"
                        f"Vence: {venc}"
                    )
                    await meta_client.send_pin_request(telefono, mode="verify", bodega_id=bod_id)
                    logger.info(f"Order {pedido['id']} confirmed: {dias}d, fee={fee}")
                else:
                    await meta_client.send_text(telefono, "No encontre el pedido. Intenta de nuevo.")
            except Exception as e:
                logger.error(f"Payment handler error: {e}", exc_info=True)
                await meta_client.send_text(telefono, "Error al confirmar. Intenta de nuevo.")
            if msg["message_id"]:
                await meta_client.mark_as_read(msg["message_id"])
            continue
        
        # ── Handle PIN for payment confirmation ──
        if body_text and len(body_text) == 4 and body_text.isdigit():
            try:
                ses = db.sb.table("sesiones").select("fase, datos, bodega_id").eq("telefono", telefono).limit(1).execute()
                if ses.data and ses.data[0].get("fase") == "pin_pago":
                    datos = json.loads(ses.data[0]["datos"]) if isinstance(ses.data[0]["datos"], str) else ses.data[0]["datos"]
                    bod_id = ses.data[0]["bodega_id"]
                    bodega = db.sb.table("bodegas").select("pin_hash, pin_intentos").eq("id", bod_id).limit(1).execute()
                    if bodega.data:
                        import bcrypt
                        pin_hash = bodega.data[0].get("pin_hash", "")
                        if pin_hash and bcrypt.checkpw(body_text.encode(), pin_hash.encode()):
                            # PIN correct → confirm order (idempotente + tope disponible)
                            pedido_id = datos["pedido_id"]
                            dias = int(datos.get("dias", 0) or 0)
                            monto = float(datos["monto"])
                            contado = float(datos.get("contado", 0) or 0)
                            venc = datos.get("venc", "")

                            pe = db.sb.table("pedidos").select("id, estado").eq("id", pedido_id).limit(1).execute()
                            if not pe.data:
                                await meta_client.send_text(
                                    telefono, "No encontramos ese pedido. Escribe MENU.")
                                db.sb.table("sesiones").update(
                                    {"fase": "menu", "datos": "{}"}).eq("telefono", telefono).execute()
                            elif not _is_draft_status(pe.data[0].get("estado")):
                                await meta_client.send_text(
                                    telefono,
                                    "Este pedido ya estaba confirmado. Escribe MENU si necesitas otra cosa.",
                                )
                                db.sb.table("sesiones").update(
                                    {"fase": "menu", "datos": "{}"}).eq("telefono", telefono).execute()
                            else:
                                if dias > 0:
                                    bod_line = db.sb.table("bodegas").select(
                                        "linea_disponible, linea_aprobada").eq("id", bod_id).limit(1).execute()
                                    ld = float(bod_line.data[0].get("linea_disponible") or 0) if bod_line.data else 0.0
                                    if monto > ld + 1e-6:
                                        await meta_client.send_text(
                                            telefono,
                                            f"⚠️ Tu tope disponible ya no alcanza (tienes S/{ld:.2f}). "
                                            "Escribe MENU, arma el pedido de nuevo o elige menos financiamiento.",
                                        )
                                        db.sb.table("sesiones").update(
                                            {"fase": "menu", "datos": "{}"}).eq("telefono", telefono).execute()
                                    else:
                                        qfee = calculate_fee(monto, dias)
                                        fee = qfee["fee"]
                                        rate = qfee["rate"]
                                        ped_t = db.sb.table("pedidos").select("tipo_operacion").eq("id", pedido_id).limit(1).execute()
                                        tipo_op = ped_t.data[0].get("tipo_operacion", "venta") if ped_t.data else "venta"
                                        num = await _gen_order_number(bod_id, tipo_op)
                                        db.sb.table("pedidos").update({
                                            "numero": num,
                                            "fee_tasa": rate, "fee_monto": fee,
                                            "monto_financiado": round(monto, 2), "plazo_dias": dias,
                                            "monto_contado": round(contado, 2),
                                            "total": round(monto + fee, 2), "estado": _confirmed_status_for(tipo_op),
                                        }).eq("id", pedido_id).execute()
                                        lap = float(bod_line.data[0].get("linea_aprobada") or ld)
                                        new_ld = max(0.0, ld - monto)
                                        new_ld = min(new_ld, lap)
                                        db.sb.table("bodegas").update(
                                            {"linea_disponible": new_ld}).eq("id", bod_id).execute()
                                        from app.services.analytics import track_event
                                        track_event(
                                            "order_confirmed" if tipo_op == "venta" else "preventa_confirmada",
                                            bodega_id=bod_id,
                                            pedido_id=pedido_id,
                                            telefono=telefono,
                                            source="pin_verify",
                                            metadata={
                                                "numero": num,
                                                "tipo_operacion": tipo_op,
                                                "monto_financiado": round(monto, 2),
                                                "fee_monto": round(fee, 2),
                                                "dias": dias,
                                            },
                                        )
                                        track_event(
                                            "credit_used",
                                            bodega_id=bod_id,
                                            pedido_id=pedido_id,
                                            telefono=telefono,
                                            source="pin_verify",
                                            metadata={"monto": round(monto, 2), "dias": dias},
                                        )
                                        await meta_client.send_text(
                                            telefono,
                                            f"✅ *Pedido {num} confirmado*\n"
                                            f"Financiado con Circa\n\n"
                                            f"Nro: *#{num}*\n"
                                            f"Financiado: *S/{monto:.2f}*\n"
                                            f"Cargo Circa ({int(rate * 100)}%): S/{fee:.2f}\n"
                                            f"Total a pagar a Circa: *S/{monto + fee:.2f}*\n"
                                            f"Al distribuidor (contado): S/{contado:.2f}\n"
                                            f"Plazo: {dias} días\n"
                                            f"Vence: {venc}\n\n"
                                            "Recibirás novedades por WhatsApp.",
                                        )
                                        db.sb.table("sesiones").update(
                                            {"fase": "menu", "datos": "{}"}).eq("telefono", telefono).execute()
                                        logger.info(f"Order {pedido_id} confirmed via PIN (financiado)")
                                else:
                                    ped_t = db.sb.table("pedidos").select("tipo_operacion").eq("id", pedido_id).limit(1).execute()
                                    tipo_op = ped_t.data[0].get("tipo_operacion", "venta") if ped_t.data else "venta"
                                    num = await _gen_order_number(bod_id, tipo_op)
                                    db.sb.table("pedidos").update({
                                        "numero": num,
                                        "fee_tasa": 0, "fee_monto": 0,
                                        "monto_financiado": 0, "monto_contado": round(monto, 2),
                                        "total": round(monto, 2), "estado": _confirmed_status_for(tipo_op),
                                    }).eq("id", pedido_id).execute()
                                    from app.services.analytics import track_event
                                    track_event(
                                        "order_confirmed" if tipo_op == "venta" else "preventa_confirmada",
                                        bodega_id=bod_id,
                                        pedido_id=pedido_id,
                                        telefono=telefono,
                                        source="pin_verify",
                                        metadata={
                                            "numero": num,
                                            "tipo_operacion": tipo_op,
                                            "monto_contado": round(monto, 2),
                                        },
                                    )
                                    await meta_client.send_text(
                                        telefono,
                                        f"✅ *Pedido {num} confirmado — Contado*\n\n"
                                        f"Total: S/{monto:.2f}\n"
                                        "Pagas al recibir tu pedido, sin cargo extra de plazo.\n\n"
                                        "Tu distribuidor preparará tu pedido.",
                                    )
                                    db.sb.table("sesiones").update(
                                        {"fase": "menu", "datos": "{}"}).eq("telefono", telefono).execute()
                                    logger.info(f"Order {pedido_id} confirmed via PIN (contado)")
                        else:
                            intentos = bodega.data[0].get("pin_intentos", 0) + 1
                            db.sb.table("bodegas").update({"pin_intentos": intentos}).eq("id", bod_id).execute()
                            if intentos >= 3:
                                db.sb.table("sesiones").update({"fase": "menu", "datos": "{}"}).eq("telefono", telefono).execute()
                                await meta_client.send_text(telefono, "❌ Clave incorrecta 3 veces. Pedido cancelado.")
                            else:
                                await meta_client.send_text(telefono, f"❌ Clave incorrecta. Intento {intentos}/3. Ingresa tu clave:")
                    if msg["message_id"]:
                        await meta_client.mark_as_read(msg["message_id"])
                    continue
            except Exception as e:
                logger.error(f"PIN verify error: {e}", exc_info=True)
        
        # Regular message processing via state machine
        try:
            responses = handle_message(telefono, body_text, media_url)
            
            for resp in responses:
                if isinstance(resp, dict):
                    signal = resp.get("signal", "")
                    
                    # ── Onboarding signals ──
                    if signal == "WELCOME":
                        await meta_client.send_welcome(
                            telefono, resp.get("nombre", ""),
                            resp.get("linea", 500), resp.get("distribuidor", "")
                        )
                    elif signal == "RUC_ASK":
                        await meta_client.send_ruc_request(telefono)
                    elif signal == "RUC_VERIFIED":
                        await meta_client.send_ruc_verified(
                            telefono, resp.get("razon_social", ""),
                            resp.get("ruc", ""), resp.get("direccion", ""),
                            resp.get("representante", "")
                        )
                    elif signal == "DNI_ASK":
                        await meta_client.send_dni_request(telefono)
                    elif signal == "BIOMETRIA_ASK":
                        await meta_client.send_biometria_request(
                            telefono, resp.get("representante", "")
                        )
                    elif signal == "LINEA_OFERTA":
                        await meta_client.send_linea_oferta(
                            telefono, resp.get("nombre", ""),
                            resp.get("linea", 500), resp.get("distribuidor", "")
                        )
                    elif signal == "CONTRATO":
                        await meta_client.send_contrato(
                            telefono, resp.get("linea", 500)
                        )
                    elif signal == "PIN_ASK":
                        await meta_client.send_pin_request(
                            telefono, resp.get("mode", "create"),
                            bodega_id=resp.get("bodega_id", "")
                        )
                    elif signal == "CUENTA_ACTIVA":
                        await meta_client.send_cuenta_activa(
                            telefono, resp.get("linea", 500)
                        )
                    
                    # ── Menu signals ──
                    elif signal == "MENU":
                        await meta_client.send_menu(telefono, resp.get("linea", 500))
                    elif signal == "LINEA_INFO":
                        await meta_client.send_linea_info(
                            telefono, resp.get("aprobada", 500),
                            resp.get("disponible", 500), resp.get("scoring", 0)
                        )
                    
                    # ── Legacy catalog signals → redirect to text for now ──
                    elif signal == "ONBOARDING_FLOW":
                        await meta_client.send_welcome(
                            telefono, resp.get("nombre", ""),
                            resp.get("linea", 500), ""
                        )
                    elif signal == "CATALOGO_FLOW":
                        bodega_cat = db.get_bodega_by_phone(telefono)
                        if bodega_cat:
                            await meta_client.send_catalogo_flow(telefono, bodega_cat["id"])
                    elif signal in ("CATEGORIAS", "PRODUCTOS", "PACK", "CANTIDAD",
                                     "AGREGADO", "CARRITO", "MONTO", "PLAZO"):
                        bodega_leg = db.get_bodega_by_phone(telefono)
                        if bodega_leg:
                            await meta_client.send_catalogo_flow(telefono, bodega_leg["id"])
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
async def update_estado(pedido_id: str, estado: str = Form(...), actor: str = Form(default="distribuidor"),
                         notas: str = Form(default=None), estimado_entrega: str = Form(default=None)):
    """Update order status with tracking notifications."""
    from app.services.tracking import update_order_status
    result = await update_order_status(pedido_id, estado, actor, notas, estimado_entrega)
    if not result["ok"]:
        raise HTTPException(400, result["message"])
    return result

@app.get("/api/pedidos/{pedido_id}/timeline")
async def get_timeline(pedido_id: str):
    """Get order event timeline."""
    from app.services.tracking import get_order_timeline
    return await get_order_timeline(pedido_id)

# ── Cobranza ──

@app.post("/api/cobranza/confirmar-pago")
async def confirmar_pago(financiamiento_id: str = Form(...), monto: float = Form(default=None),
                          metodo: str = Form(default="yape"), actor: str = Form(default="backoffice")):
    """Confirm a payment and renew credit line (backoffice)."""
    from app.services.cobranza import confirm_payment
    result = await confirm_payment(financiamiento_id, monto, metodo, actor)
    if not result["ok"]:
        raise HTTPException(400, result["message"])
    return result

@app.get("/api/cobranza/pendientes")
async def pagos_pendientes(bodega_id: str = None):
    """List pending payments, optionally filtered by bodega."""
    query = db.sb.table("financiamientos").select(
        "*, pedidos(numero), bodegas(nombre_comercial, telefono_whatsapp)"
    ).in_("estado", ["activo", "verificando", "vencido"])
    if bodega_id:
        query = query.eq("bodega_id", bodega_id)
    return query.order("fecha_vencimiento").execute().data

@app.post("/api/cobranza/check-overdue")
async def check_overdue():
    """Check and mark overdue loans. Call daily."""
    from app.services.cobranza import check_overdue_loans
    overdue = await check_overdue_loans()
    return {"overdue_count": len(overdue), "overdue": overdue}

@app.post("/api/cobranza/send-reminders")
async def send_reminders():
    """Send pending payment reminders. Call daily."""
    from app.services.cobranza import send_pending_reminders
    count = await send_pending_reminders()
    return {"reminders_sent": count}

@app.get("/api/bodegas")
async def list_bodegas():
    return db.sb.table("bodegas").select("id, ruc, razon_social, nombre_comercial, estado, linea_aprobada, linea_disponible, scoring").order("created_at", desc=True).execute().data

@app.get("/api/bodegas/{bodega_id}")
async def get_bodega(bodega_id: str):
    return db.sb.table("bodegas").select("*").eq("id", bodega_id).single().execute().data

@app.get("/api/catalogo")
async def list_catalogo(distribuidor_id: str = None, bodega_id: str = None, marca: str = None, categoria: str = None):
    # Si viene bodega_id, resolver su distribuidor automáticamente (modular)
    if bodega_id and not distribuidor_id:
        try:
            distribuidor_id = db.get_distribuidor_de_bodega(bodega_id)
        except Exception:
            pass
    q = db.sb.table("catalogo_distribuidor").select("*, productos_circa(*)").eq("activo", True)
    if distribuidor_id: q = q.eq("distribuidor_id", distribuidor_id)
    rows = q.execute().data
    result = []
    for row in rows:
        pc = row.get("productos_circa") or {}
        if marca and pc.get("marca") != marca: continue
        if categoria and pc.get("categoria") != categoria: continue
        result.append({
            "id": pc.get("id"), "nombre": pc.get("nombre", ""), "marca": pc.get("marca", ""),
            "categoria": pc.get("categoria", ""), "unidades": row.get("unidades") or {},
            "sku": row.get("sku_distribuidor", ""), "activo": row.get("activo", True),
        })
    return result

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
    tipo_operacion: str = "venta"


class AnalyticsEventIn(BaseModel):
    bodega_id: str
    event_type: str
    metadata: dict | None = None

@app.post("/api/catalogo/submit-cart")
async def submit_cart(data: CartSubmission):
    from app.services.analytics import track_event
    from app.services import meta_client
    items_list = [dict(i) if not isinstance(i, dict) else i for i in data.items]
    total = sum(i.get("subtotal", 0) for i in items_list)
    tipo = "preventa" if data.tipo_operacion == "preventa" else "venta"
    estado_inicial = "preventa_borrador" if tipo == "preventa" else "borrador"
    # Create order in pedidos
    pedido = db.sb.table("pedidos").insert({
        "bodega_id": data.bodega_id,
        "distribuidor_id": "a1b2c3d4-0001-4000-8000-000000000001",
        "items_json": json.dumps(items_list),
        "monto_productos": total,
        "estado": estado_inicial,
        "tipo_operacion": tipo,
    }).execute()
    pedido_id = pedido.data[0]["id"] if pedido.data else None
    if pedido_id:
        track_event(
            "preventa_created" if tipo == "preventa" else "order_created",
            bodega_id=data.bodega_id,
            pedido_id=pedido_id,
            source="catalog_web",
            metadata={
                "tipo_operacion": tipo,
                "items_count": len(items_list),
                "total": round(total, 2),
            },
        )
    # For venta: send proactive payment options right after cart submit.
    # For preventa: ask explicit confirm step (no payment options yet).
    if tipo == "venta":
        bodega = db.sb.table("bodegas").select("telefono_whatsapp").eq("id", data.bodega_id).limit(1).execute()
        if bodega.data and pedido_id:
            phone = bodega.data[0]["telefono_whatsapp"].replace("+", "")
            items_text = "\n".join(f"{i.get('cantidad',1)}x {i.get('nombre','')} — S/{i.get('subtotal',0):.2f}" for i in items_list)
            # Send payment options via Meta API (async)
            from app.flows.catalogo import _send_payment_options
            import asyncio
            asyncio.create_task(_send_payment_options(phone, pedido_id, total, items_text, data.bodega_id))
    else:
        bodega = db.sb.table("bodegas").select("telefono_whatsapp").eq("id", data.bodega_id).limit(1).execute()
        if bodega.data and pedido_id:
            phone = bodega.data[0]["telefono_whatsapp"].replace("+", "")
            pid = str(pedido_id)[:8]
            await meta_client.send_text(
                phone,
                f"🗓️ *Pre-venta armada*\n\n"
                f"Total referencial: S/{total:.2f}\n"
                f"Código temporal: *PRV-{pid}*\n\n"
                f"Si todo está bien, confirma tu pre-venta con tu clave Circa.",
            )
            await meta_client.send_buttons(
                to=phone,
                body="¿Qué deseas hacer ahora?",
                buttons=[
                    {"id": f"PRECONF_{pid}", "title": "Confirmar pre-venta"},
                    {"id": f"EDITAR_{pid}", "title": "Editar carrito"},
                ],
            )
    return {"ok": True, "pedido_id": str(pedido_id) if pedido_id else None}


@app.get("/api/analytics/bodega/{bodega_id}")
async def analytics_bodega(bodega_id: str):
    from app.services.analytics import get_bodega_features
    return get_bodega_features(bodega_id)


@app.post("/api/analytics/event")
async def analytics_event(data: AnalyticsEventIn):
    from app.services.analytics import track_event
    track_event(
        data.event_type,
        bodega_id=data.bodega_id,
        source="catalog_web",
        metadata=data.metadata or {},
    )
    return {"ok": True}

@app.post("/api/carrito/clear")
async def clear_carrito_api(data: dict):
    bodega_id = data.get("bodega_id", "")
    if bodega_id:
        db.clear_carrito(bodega_id)
    return {"ok": True}

@app.get("/api/carrito/{bodega_id}")
async def get_carrito(bodega_id: str):
    cart = db.get_carrito(bodega_id)
    if not cart:
        return {"items": []}
    items = cart.get("items", [])
    if isinstance(items, str):
        import json as _json
        try:
            cart["items"] = _json.loads(items)
        except Exception:
            cart["items"] = []
    return cart

@app.get("/catalogo")
async def catalogo_page():
    return FileResponse("static/catalogo.html")

@app.get("/catalogo-v2")
async def catalogo_v2_page():
    return FileResponse("static/catalogo_v2.html")

@app.get("/api/cobranza")
async def cobranza_pendiente():
    return db.sb.table("pagos").select("*, pedidos(numero, bodega_id, monto_total_credito, bodegas(nombre_comercial, telefono_whatsapp))").eq("estado", "pendiente").order("fecha_vencimiento").execute().data

# ── DEMO SIMULATION ──

@app.post("/api/demo/simulate-flow/{pedido_id}")
async def simulate_full_flow(pedido_id: str):
    import asyncio
    from app.services import meta_client as mc
    pedido = db.sb.table("pedidos").select("*, bodegas(telefono_whatsapp, nombre_comercial)").eq("id", pedido_id).single().execute().data
    if not pedido:
        raise HTTPException(404, "Pedido no encontrado")
    tel = pedido["bodegas"]["telefono_whatsapp"].replace("+", "")
    monto = pedido.get("total", 0)
    plazo = pedido.get("plazo_dias", 0)
    items_json = pedido.get("items_json", "[]")
    try:
        items = json.loads(items_json) if isinstance(items_json, str) else items_json
    except:
        items = []
    items_text = "\n".join(f"{it.get('cantidad', it.get('qty',0))}x {it.get('nombre', it.get('name',''))}" for it in items)

    steps = [
        ("confirmado", "📋 *Pedido recibido*\nTu pedido ha sido recibido por el distribuidor."),
        ("despachado", "📦 *Armando pedido*\nTu pedido fue armado y esta listo para despacho."),
        ("en_camino", "🚚 *En camino*\nTu pedido esta en camino. Llegada estimada: hoy 2-4 p.m."),
        ("entregado", "✅ *Entregado*\n¡Tu pedido ha sido entregado!"),
    ]
    for estado, msg_text in steps:
        try:
            db.sb.table("pedidos").update({"estado": estado}).eq("id", pedido_id).execute()
        except:
            pass
        await mc.send_text(tel, msg_text)
        await asyncio.sleep(3)

    # Send payment request
    from datetime import datetime, timedelta
    venc_date = datetime.now() + timedelta(days=plazo if plazo else 7)
    venc = venc_date.strftime("%d/%m/%Y")
    if monto and monto > 0:
        await mc.send_buttons(
            tel,
            f"⏰ *Recordatorio de pago*\n\n"
            f"Pedido *#{pedido.get('numero', '')}*:\n{items_text}\n"
            f"Monto: *S/{monto:.2f}*\n"
            f"Vence: *{venc}*\n\n"
            f"Paga por Yape o Plin al:\n"
            f"📱 *987 654 321*\n"
            f"👤 Circa Pagos S.A.C.\n\n"
            f"Cuando hayas pagado, toca el boton:",
            [{"id": "YA_PAGUE", "title": "Ya pague ✅"}]
        )

    return {"ok": True, "message": "Demo flow completed"}

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

@app.get("/api/debug/catalogo-response")
async def debug_catalogo_response():
    """Debug: show what the catalog flow would return."""
    from app.flows.catalogo import _screen_categorias
    try:
        result = await _screen_categorias({"bodega_id": "b1b2c3d4-0001-4000-8000-000000000001"})
        return result
    except Exception as e:
        return {"error": str(e), "type": type(e).__name__}


# ============================================================
# Endpoint: motor de promociones por distribuidor
# (Sprint promociones DIMAX 22-abr-2026)
# ============================================================
from app.services.promociones import evaluar_promociones as _evaluar_promociones


class _CartItem(BaseModel):
    sku_distribuidor: str | None = None  # Opcional: si no viene, se resuelve desde catalogo_id
    catalogo_id: str | None = None       # UUID de productos_circa (alternativa)
    cantidad: int
    formato: str  # "UND x 1", "TIRA x 10", "CJA x 24"
    precio_unitario_formato: float


class _EvaluarPromocionesReq(BaseModel):
    bodega_id: str
    cart: list[_CartItem]


@app.post("/api/promociones/evaluar")
async def api_evaluar_promociones(req: _EvaluarPromocionesReq):
    """
    Recibe el carrito y devuelve qué promociones aplican y siguientes escalones.
    Llamado por el frontend cada vez que el carrito cambia.
    """
    if not req.cart:
        return {"items": [], "ahorro_total": 0, "subtotal_total": 0, "total_final": 0}

    distribuidor_id = db.get_distribuidor_de_bodega(req.bodega_id)
    if not distribuidor_id:
        return {"error": "Bodega no encontrada o sin distribuidor", "items": []}

    reglas = db.get_promociones_activas(distribuidor_id)
    if not reglas:
        items = [{
            "sku_distribuidor": i.sku_distribuidor,
            "subtotal": round(i.cantidad * i.precio_unitario_formato, 2),
            "descuento_aplicado": None,
            "siguiente_escalon": None,
        } for i in req.cart]
        subtotal = sum(it["subtotal"] for it in items)
        return {"items": items, "ahorro_total": 0, "subtotal_total": subtotal, "total_final": subtotal}

    # Resolver catalogo_id (UUID) → sku_distribuidor si el frontend solo manda UUIDs
    cat_ids_to_resolve = [i.catalogo_id for i in req.cart if i.catalogo_id and not i.sku_distribuidor]
    sku_map = db.get_skus_for_catalogo_ids(distribuidor_id, cat_ids_to_resolve) if cat_ids_to_resolve else {}

    # Construir lista de SKUs efectivos
    skus_efectivos = []
    for i in req.cart:
        sku = i.sku_distribuidor or sku_map.get(i.catalogo_id, "")
        skus_efectivos.append(sku)

    info = db.get_catalogo_info_for_skus(distribuidor_id, [s for s in skus_efectivos if s])

    cart_enriched = []
    for i, sku in zip(req.cart, skus_efectivos):
        ci = info.get(sku, {})
        cart_enriched.append({
            "sku_distribuidor": sku,
            "cantidad": i.cantidad,
            "formato": i.formato,
            "precio_unitario_formato": i.precio_unitario_formato,
            "categoria": ci.get("categoria"),
            "marca": ci.get("marca"),
            "contenido_caja": ci.get("contenido_caja"),
            "contenido_pack": ci.get("contenido_pack"),
        })

    return _evaluar_promociones(cart_enriched, reglas)
