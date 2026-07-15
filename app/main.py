"""
Circa MVP - FastAPI Application (Full Button UX + PIN Web)
===========================================================
Run: uvicorn main:app --reload --port 8000
Expose: ngrok http 8000
"""
from fastapi import FastAPI, Request, Form, HTTPException, Depends
from fastapi.responses import PlainTextResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from app.routes.distribuidor import router as distribuidor_router
from app.routes.support_inbox import router as support_inbox_router
from app.routes.vendedor import router as vendedor_router
from app.routes.backoffice import router as backoffice_router
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
from app.services.fees import calculate_fee, format_rate_pct, fee_regimen_para_pedido_nuevo
from app.services.internal_auth import verify_admin_token
from app.services.meta_commerce_handlers import MetaWaContext, normalize_wa_phone, try_handle_commerce_interactive
from pydantic import BaseModel
from app.config import TWILIO_FROM
from datetime import date, timedelta
from contextlib import asynccontextmanager
import asyncio
import logging, json, os

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("circa")


@asynccontextmanager
async def _circa_lifespan(app: FastAPI):
    task = None
    try:
        from app.support.realtime_redis import redis_pubsub_enabled, spawn_subscriber_if_needed
        from app.support.ws_hub import hub

        if redis_pubsub_enabled():
            task = spawn_subscriber_if_needed(hub.deliver_local)
            logger.info("Support realtime: Redis Pub/Sub bridge enabled")
    except Exception as e:
        logger.warning("lifespan init (support redis): %s", e)
    yield
    try:
        from app.support.realtime_redis import shutdown_redis_async

        await shutdown_redis_async(task)
    except Exception as e:
        logger.warning("lifespan shutdown (support redis): %s", e)


app = FastAPI(title="Circa MVP", version="2.3.0", lifespan=_circa_lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.mount("/static", StaticFiles(directory="static"), name="static")
app.include_router(distribuidor_router)
app.include_router(support_inbox_router)
app.include_router(vendedor_router)
app.include_router(backoffice_router)


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
    elif sig == "PREVENTA_PAYMENT_OPTIONS":
        from app.flows.catalogo import _send_payment_options
        items = signal["items"]
        lines_items = []
        for it in items:
            cat = it.get("catalogo_distribuidor") or {}
            prod = cat.get("productos_circa") or {}
            nombre = (prod.get("nombre") or "Producto")[:38]
            cant = it.get("cantidad", 0)
            sub = float(it.get("subtotal") or 0)
            if sub == 0:
                lines_items.append(f"▸ {cant}x *{nombre}* 🎁")
            else:
                lines_items.append(f"▸ {cant}x *{nombre}*\n   S/{sub:.2f}")
        items_text = "\n".join(lines_items)
        asyncio.create_task(_send_payment_options(
            telefono, signal["pedido_id"], signal["total"], items_text, signal["bodega_id"]
        ))
    elif sig == "MONTO":
        send_monto_financiar(telefono, signal["linea"], signal["total"], signal["financiable"])
    elif sig == "PLAZO":
        send_plazo(telefono, signal["monto"], signal["fee7"], signal["total7"], signal["fee15"], signal["total15"], signal["fee30"], signal["total30"])
    elif sig == "MENU":
        send_menu(telefono, signal["linea"])
    elif sig == "FLYER_LINK":
        base = os.getenv("APP_BASE_URL", "https://circa-production-c517.up.railway.app").rstrip("/")
        send_whatsapp(
            telefono,
            "📄 *Flyer y promos Circa*\n\n"
            f"Abre aquí: {base}/flyer\n\n"
            "Cuando termines, escribe *MENU* para volver.",
        )
    elif sig == "VEND_NOTIFY_BODEGA":
        dest = signal.get("to") or ""
        if dest:
            send_whatsapp(dest, signal.get("body") or "")
    elif sig == "CONTACT_CIRCA":
        # Twilio (legacy): texto plano. Si SUPPORT_INBOX_DISABLED, fallback wa.me (CIRCA_SOPORTE_WHATSAPP).
        link = signal.get("wa_link") or ""
        if link:
            send_whatsapp(
                telefono,
                "📞 *Habla con Circa*\n\n"
                f"Abre: {link}\n\n"
                "Cuando termines, escribe MENU para volver.",
            )
        else:
            send_whatsapp(
                telefono,
                "📞 Contacto Circa aún no configurado. Escribe MENU o habla con tu distribuidor.",
            )
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
        # Misma cola de soporte humano que Meta (inbox interno), antes del state machine.
        tel_sup = telefono.strip()
        if not tel_sup.startswith("+"):
            tel_sup = f"+{tel_sup}"
        bodega_tw = db.get_bodega_by_phone(telefono) or db.get_bodega_by_phone(tel_sup)
        from app.support.webhook_gate import process_meta_inbound

        sup_tw = await process_meta_inbound(
            telefono=tel_sup,
            body_text=body,
            msg={"message_id": "", "type": "text", "list_id": body},
            bodega_id=bodega_tw.get("id") if bodega_tw else None,
            contact_name=None,
        )
        if sup_tw.skip_remaining_handlers:
            twiml = MessagingResponse()
            return PlainTextResponse(str(twiml), media_type="text/xml")

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

@app.get("/privacy")
async def privacy():
    return PlainTextResponse("""
POLÍTICA DE PRIVACIDAD — CIRCA (PALI S.A.C.)
Última actualización: 28 de abril de 2026

Circa, operado por PALI S.A.C. (RUC 20600627806), recopila datos personales (RUC, DNI, nombre, dirección, teléfono, historial de pedidos y pagos) exclusivamente para la evaluación crediticia, gestión de pedidos y cobranza. Los datos son almacenados en servidores seguros y no se comparten con terceros sin consentimiento, salvo requerimiento legal. El usuario puede ejercer sus derechos ARCO escribiendo a contacto@circa.pe. Cumplimos con la Ley 29733 de Protección de Datos Personales del Perú.

Contacto: contacto@circa.pe | +51 986 311 567
""", media_type="text/plain; charset=utf-8")

@app.get("/terms")
async def terms():
    return PlainTextResponse("""
CONDICIONES DEL SERVICIO — CIRCA (PALI S.A.C.)
Última actualización: 20 de mayo de 2026

Circa es una plataforma de crédito embebido para bodegas peruanas operada por PALI S.A.C. Al usar el servicio, el usuario acepta las condiciones del contrato de línea de crédito revolving. En nuevas operaciones, la comisión se fija al confirmar el pedido según el plan elegido: 7 días (1.4%), 15 días (3%), 30 días (6%), con comisión mínima de S/1.00 por operación. El pago dentro del plazo no modifica el monto acordado. Tras el vencimiento del plan, aplica mora de 0.03% diaria sobre el saldo adeudado. Las operaciones ya originadas conservan los montos acordados en su confirmación. Jurisdicción: Lima, Perú.

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
async def debug_check(_admin: bool = Depends(verify_admin_token)):
    """Debug endpoint — requiere X-Admin-Token."""
    results = {"tables": {}}
    for t in ["sesiones", "bodegas"]:
        try:
            r = db.sb.table(t).select("id").limit(1).execute()
            results["tables"][t] = {"ok": True, "rows": len(r.data)}
        except Exception as e:
            results["tables"][t] = {"ok": False, "error": str(e)[:200]}
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
    from app.services.meta_webhook import parse_incoming, parse_status_updates, verify_signature
    from app.services import meta_client
    from app.services.analytics import track_message
    from app.support.service import apply_wa_status

    raw_body = await request.body()
    signature = request.headers.get("X-Hub-Signature-256", "")
    if not verify_signature(raw_body, signature):
        raise HTTPException(status_code=403, detail="Invalid signature")

    try:
        body = json.loads(raw_body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    for st in parse_status_updates(body):
        await apply_wa_status(st)
    
    # Parse incoming messages
    messages = parse_incoming(body)
    
    for msg in messages:
        telefono = normalize_wa_phone(msg["from"])
        body_text = msg["body"]
        media_url = None
        wa_ctx = MetaWaContext.from_phone(telefono)
        bodega_id_msg = wa_ctx.bodega_id
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
                "media_id": msg.get("media_id", ""),
                "mime_type": msg.get("mime_type", ""),
                "caption": msg.get("caption", ""),
                "filename": msg.get("filename", ""),
            },
        )
        
        # Handle image (selfie for biometria / fotos prospecto)
        if msg["type"] == "image" and msg["media_id"]:
            media_url = msg["media_id"]  # Pass media_id to state machine
            # 2.2: número sin bodega → persistir YA (Meta purge ~2-3 semanas),
            # aunque soporte humano tome el hilo después.
            if not bodega_id_msg:
                try:
                    from app.services import prospect_media as pm
                    sess = db.get_session(telefono)
                    datos = pm.session_datos(sess) if sess and sess.get("fase") == "prospecto" else {}
                    paso = datos.get("paso") or "esperando_datos"
                    if paso == "esperando_local_foto":
                        kind = "local"
                    elif paso == "esperando_dni_foto":
                        kind = "dni"
                    elif not datos.get("dni_foto_path"):
                        kind = "dni"
                    elif not datos.get("local_foto_path"):
                        kind = "local"
                    else:
                        kind = "otro"
                    already = any(
                        (f or {}).get("media_id") == media_url
                        for f in (datos.get("fotos") or [])
                    )
                    if not already:
                        saved = await pm.persist_image_from_media_id_async(
                            telefono, media_url, kind, msg.get("mime_type") or None,
                        )
                        if saved:
                            datos = pm.ensure_prospecto_session(telefono, sess)
                            sess2 = db.get_session(telefono)
                            datos = pm.session_datos(sess2)
                            datos = pm.record_foto(datos, saved, media_url)
                            db.upsert_session(telefono, "prospecto", datos, None)
                except Exception as e:
                    logger.warning("prospect_media early persist failed: %s", e)

        # Human support inbox: bot + commerce handlers stand down while agent owns thread
        from app.support.webhook_gate import process_meta_inbound

        sup_decision = await process_meta_inbound(
            telefono=telefono,
            body_text=body_text,
            msg=msg,
            bodega_id=bodega_id_msg,
            contact_name=msg.get("name") or "",
        )
        if sup_decision.skip_remaining_handlers:
            if msg.get("message_id"):
                await meta_client.mark_as_read(msg["message_id"])
            continue
        
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
                    bodega = wa_ctx.bodega
                    if bodega:
                        await meta_client.send_pin_request(telefono, "create", bodega["id"])
                elif len(pin) != 4 or not pin.isdigit():
                    await meta_client.send_text(telefono, "❌ La clave debe ser 4 dígitos. Intenta de nuevo.")
                else:
                    # Valid PIN — activate account
                    from app.services.pin import hash_pin
                    bodega = wa_ctx.bodega
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
                bodega = wa_ctx.bodega
                linea = bodega.get("linea_disponible", 500) if bodega else 500
                _pv_pend = db.get_preventa_pendiente(bodega["id"]) if bodega else None
                await meta_client.send_menu(to=telefono, linea_disponible=linea, preventa_pendiente=_pv_pend)
            
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
        if await try_handle_commerce_interactive(btn, body_text, wa_ctx, msg, meta_client):
            continue

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
                    elif signal == "DNI_PREFILL_CONFIRM":
                        await meta_client.send_dni_prefill_confirm(
                            telefono,
                            resp.get("dni", ""),
                            resp.get("nombre", ""),
                        )
                    elif signal == "DNI_FOTO_ASK":
                        await meta_client.send_dni_foto_ask(
                            telefono,
                            resp.get("dni", ""),
                            resp.get("nombre", ""),
                        )
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
                        _bodega_menu = db.get_bodega_by_phone(telefono)
                        _pv_pend = db.get_preventa_pendiente(_bodega_menu["id"]) if _bodega_menu else None
                        await meta_client.send_menu(telefono, resp.get("linea", 500), preventa_pendiente=_pv_pend)
                    elif signal == "FLYER_LINK":
                        await meta_client.send_flyer_link(telefono)
                    elif signal == "LINEA_INFO":
                        await meta_client.send_linea_info(
                            telefono, resp.get("aprobada", 500),
                            resp.get("disponible", 500), resp.get("scoring", 0)
                        )
                    elif signal == "CONTACT_CIRCA":
                        await meta_client.send_contacto_circa(
                            telefono, resp.get("wa_link"),
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
                    elif signal == "PREVENTA_PAYMENT_OPTIONS":
                        from app.flows.catalogo import _send_payment_options
                        items = resp.get("items") or []
                        lines_items = []
                        for it in items:
                            cat = it.get("catalogo_distribuidor") or {}
                            prod = cat.get("productos_circa") or {}
                            nombre = (prod.get("nombre") or "Producto")[:38]
                            cant = it.get("cantidad", 0)
                            sub = float(it.get("subtotal") or 0)
                            if sub == 0:
                                lines_items.append(f"▸ {cant}x *{nombre}* 🎁")
                            else:
                                lines_items.append(f"▸ {cant}x *{nombre}*\n   S/{sub:.2f}")
                        items_text = "\n".join(lines_items)
                        await _send_payment_options(
                            telefono, resp["pedido_id"], resp["total"], items_text, resp["bodega_id"]
                        )
                    elif signal == "VEND_NOTIFY_BODEGA":
                        dest = resp.get("to") or ""
                        if dest:
                            await meta_client.send_text(dest, resp.get("body") or "")
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
async def list_pedidos(estado: str = None, _admin: bool = Depends(verify_admin_token)):
    q = db.sb.table("pedidos").select("*, bodegas(nombre_comercial, telefono_whatsapp), distribuidores(nombre_comercial)")
    if estado:
        q = q.eq("estado", estado)
    return q.order("created_at", desc=True).limit(50).execute().data


@app.get("/api/test-notify/{pedido_id}")
async def test_notify(pedido_id: str, _admin: bool = Depends(verify_admin_token)):
    """Diagnóstico: dispara notificar_preventa_bodeguero manualmente."""
    from app.flows.catalogo import notificar_preventa_bodeguero
    try:
        await notificar_preventa_bodeguero(pedido_id)
        return {"ok": True, "sent": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}

@app.get("/api/pedidos/{pedido_id}")
async def get_pedido(pedido_id: str, _admin: bool = Depends(verify_admin_token)):
    pedido = db.sb.table("pedidos").select("*, bodegas(nombre_comercial, telefono_whatsapp)").eq("id", pedido_id).single().execute().data
    items = db.sb.table("items_pedido").select("*, catalogo(nombre, marca)").eq("pedido_id", pedido_id).execute().data
    return {"pedido": pedido, "items": items}

@app.post("/api/pedidos/{pedido_id}/estado")
async def update_estado(pedido_id: str, estado: str = Form(...), actor: str = Form(default="distribuidor"),
                         notas: str = Form(default=None), estimado_entrega: str = Form(default=None),
                         _admin: bool = Depends(verify_admin_token)):
    """Update order status with tracking notifications."""
    from app.services.tracking import update_order_status
    result = await update_order_status(pedido_id, estado, actor, notas, estimado_entrega)
    if not result["ok"]:
        raise HTTPException(400, result["message"])
    return result

@app.get("/api/pedidos/{pedido_id}/timeline")
async def get_timeline(pedido_id: str, _admin: bool = Depends(verify_admin_token)):
    """Get order event timeline."""
    from app.services.tracking import get_order_timeline
    return await get_order_timeline(pedido_id)

# ── Cobranza ──

@app.post("/api/cobranza/confirmar-pago")
async def confirmar_pago(financiamiento_id: str = Form(...), monto: float = Form(default=None),
                          metodo: str = Form(default="yape"), actor: str = Form(default="backoffice"),
                          _admin: bool = Depends(verify_admin_token)):
    """Confirm a payment and renew credit line (backoffice)."""
    from app.services.cobranza import confirm_payment
    result = await confirm_payment(financiamiento_id, monto, metodo, actor)
    if not result["ok"]:
        raise HTTPException(400, result["message"])
    return result

@app.get("/api/cobranza/pendientes")
async def pagos_pendientes(bodega_id: str = None, _admin: bool = Depends(verify_admin_token)):
    """List pending payments, optionally filtered by bodega."""
    query = db.sb.table("financiamientos").select(
        "*, pedidos(numero), bodegas(nombre_comercial, telefono_whatsapp)"
    ).in_("estado", ["activo", "verificando", "vencido"])
    if bodega_id:
        query = query.eq("bodega_id", bodega_id)
    return query.order("fecha_vencimiento").execute().data

@app.post("/api/cobranza/check-overdue")
async def check_overdue(_admin: bool = Depends(verify_admin_token)):
    """Check and mark overdue loans. Call daily."""
    from app.services.cobranza import check_overdue_loans
    overdue = await check_overdue_loans()
    return {"overdue_count": len(overdue), "overdue": overdue}

@app.post("/api/cobranza/send-reminders")
async def send_reminders(_admin: bool = Depends(verify_admin_token)):
    """Send pending payment reminders. Call daily."""
    from app.services.cobranza import send_pending_reminders
    count = await send_pending_reminders()
    return {"reminders_sent": count}

@app.get("/api/bodegas")
async def list_bodegas(_admin: bool = Depends(verify_admin_token)):
    return db.sb.table("bodegas").select("id, ruc, razon_social, nombre_comercial, estado, linea_aprobada, linea_disponible, scoring").order("created_at", desc=True).execute().data

@app.get("/api/bodegas/{bodega_id}")
async def get_bodega(bodega_id: str, _admin: bool = Depends(verify_admin_token)):
    return db.sb.table("bodegas").select("*").eq("id", bodega_id).single().execute().data

@app.get("/api/catalogo")
async def list_catalogo(distribuidor_id: str = None, bodega_id: str = None, marca: str = None, categoria: str = None):
    from app.services.distribuidor_routing import DIMAX_DISTRIBUIDOR_ID

    # Catálogo multi-distribuidor (12-jun-2026): una bodega puede tener
    # varios distribuidores activos (tabla bodega_distribuidores).
    # Sin bodega_id: default legacy DIMAX.
    try:
        if bodega_id:
            dist_ids = db.get_distribuidores_de_bodega(bodega_id)
        else:
            dist_ids = [DIMAX_DISTRIBUIDOR_ID]
    except Exception:
        dist_ids = [DIMAX_DISTRIBUIDOR_ID]
    # Si bodega es test, mostrar todo el catálogo (incluyendo Nestlé inactivo)
    es_test = False
    if bodega_id:
        try:
            bod = db.sb.table("bodegas").select("es_test").eq("id", bodega_id).single().execute().data
            es_test = bod.get("es_test", False) if bod else False
        except Exception:
            pass
    q = db.sb.table("catalogo_distribuidor").select("*, productos_circa(*)").in_("distribuidor_id", dist_ids)
    if not es_test:
        q = q.eq("activo", True)
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
            "distribuidor_id": row.get("distribuidor_id"),
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
    from app.services.pin import validate_pin_format, hash_pin

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
    from app.services.pin import check_pin

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

        dist_pedido = db.get_distribuidor_pedido_de_bodega(bodega["id"])
        if not dist_pedido:
            return {"ok": False, "error": "Bodega no encontrada"}
        pedido = db.create_pedido(
            bodega_id=bodega["id"],
            distribuidor_id=dist_pedido,
            items=cart,
            monto_productos=cart_total,
            monto_financiado=fin_amt,
            monto_contado=contado,
            fee_tasa=term["rate"],
            fee_monto=term["fee"],
            plazo_dias=term["days"],
            fee_regimen=fee_regimen_para_pedido_nuevo(),
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
async def reset_pin(data: PinReset, _admin: bool = Depends(verify_admin_token)):
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
    # Modo vendedor (preventa presencial armada desde la app del vendedor)
    vendedor_token: str | None = None
    origen: str | None = None


class AnalyticsEventIn(BaseModel):
    bodega_id: str
    event_type: str
    metadata: dict | None = None

# -- Promociones: se aplican al guardar el pedido (parche 22-may-2026) --
async def _aplicar_promociones_a_cart(bodega_id: str, items_list: list) -> tuple:
    """
    Corre el motor de promociones sobre el carrito ANTES de guardar el pedido.
    Reescribe precio/subtotal de cada linea con el valor con descuento.

    Devuelve (items_list, total_neto, descuento_total).

    Si el motor falla por cualquier razon, devuelve el carrito intacto y
    descuento 0 -- un pedido a precio de lista es preferible a un pedido fallido.
    """
    bruto = round(sum(float(i.get("subtotal") or 0) for i in items_list), 2)
    if not items_list:
        return items_list, bruto, 0.0

    # Resolver formato string desde pack_size numerico + catalogo.unidades.
    # El motor de promos matchea contra keys del JSONB (ej "CJA x 12"), no
    # contra el numero pack_size. Sin esta conversion NINGUNA promo aplica.
    formatos_resueltos = {}
    try:
        _cat_ids = list({i.get("catalogo_id") for i in items_list if i.get("catalogo_id")})
        if _cat_ids:
            _rows = db.sb.table("catalogo_distribuidor").select(
                "id, unidades"
            ).in_("id", _cat_ids).execute().data or []
            _unidades_por_catid = {r["id"]: (r.get("unidades") or {}) for r in _rows}
            for _it in items_list:
                _cid = _it.get("catalogo_id")
                _pack = _it.get("pack_size")
                if not _cid or _pack is None:
                    continue
                _unid = _unidades_por_catid.get(_cid) or {}
                _suffix = f" x {_pack}"
                _cands = [k for k in _unid.keys() if k.endswith(_suffix)]
                if len(_cands) == 1:
                    formatos_resueltos[(_cid, _pack)] = _cands[0]
                elif len(_cands) > 1:
                    _prc = float(_it.get("precio") or 0)
                    _match = None
                    for _k in _cands:
                        _v = _unid.get(_k)
                        if _v is not None and abs(float(_v) - _prc) < 0.01:
                            _match = _k
                            break
                    formatos_resueltos[(_cid, _pack)] = _match or _cands[0]
    except Exception as _e:
        logger.error(
            "submit-cart: resolver formato fallo (%s); usando pack_size raw", _e
        )

    def _formato_para(i):
        _cid = i.get("catalogo_id")
        _pack = i.get("pack_size")
        _f = formatos_resueltos.get((_cid, _pack))
        if _f:
            return _f
        # Fallback: comportamiento previo (guarda sin descuento si el motor rechaza)
        return str(_pack) if _pack is not None else ""

    try:
        req = _EvaluarPromocionesReq(
            bodega_id=bodega_id,
            cart=[
                _CartItem(
                    catalogo_id=i.get("catalogo_id"),
                    cantidad=int(i.get("cantidad") or 1),
                    formato=_formato_para(i),
                    precio_unitario_formato=float(i.get("precio") or 0),
                )
                for i in items_list
            ],
        )
        resultado = await api_evaluar_promociones(req)
        res_items = resultado.get("items") or []

        # El motor devuelve un item por linea, en el mismo orden del carrito.
        # Si la cantidad no coincide, no arriesgamos: guardamos a precio de lista.
        if len(res_items) != len(items_list):
            logger.error(
                "submit-cart: motor devolvio %d items para carrito de %d; "
                "se guarda sin descuento", len(res_items), len(items_list)
            )
            return items_list, bruto, 0.0

        for item, res in zip(items_list, res_items):
            desc = res.get("descuento_aplicado")
            if not desc:
                continue
            pct = float(desc.get("porcentaje") or 0)
            cant = int(item.get("cantidad") or 1)
            precio_neto = round(float(item.get("precio") or 0) * (1 - pct), 2)
            item["precio"] = precio_neto
            item["subtotal"] = round(precio_neto * cant, 2)

        total_neto = round(sum(float(i.get("subtotal") or 0) for i in items_list), 2)
        descuento = round(bruto - total_neto, 2)
        return items_list, total_neto, descuento

    except Exception as e:
        logger.error(
            "submit-cart: motor de promociones fallo, se guarda sin descuento (%s)",
            e, exc_info=True,
        )
        return items_list, bruto, 0.0


@app.post("/api/catalogo/submit-cart")
async def submit_cart(data: CartSubmission):
    from app.services.analytics import track_event
    from app.services import meta_client
    items_list = [dict(i) if not isinstance(i, dict) else i for i in data.items]

    # === MODO VENDEDOR: validar token y preparar campos extra ===
    vendedor_id = None
    is_vendedor_mode = False
    link_token = None
    if data.vendedor_token:
        v_rows = db.sb.table("vendedores").select("id,activo,nombre").eq(
            "access_token", data.vendedor_token
        ).limit(1).execute()
        if v_rows.data and v_rows.data[0].get("activo"):
            vendedor_id = v_rows.data[0]["id"]
            is_vendedor_mode = True
            import secrets
            link_token = secrets.token_hex(6)
        else:
            return {"ok": False, "error": "Token de vendedor invalido"}
    # === FIN MODO VENDEDOR ===

    # Aplicar promociones ANTES de guardar: reescribe items_list con los
    # precios con descuento y devuelve total neto + descuento prorrateado.
    items_list, total, descuento = await _aplicar_promociones_a_cart(
        data.bodega_id, items_list
    )
    tipo = "preventa" if data.tipo_operacion == "preventa" else "venta"

    # En modo vendedor: siempre preventa y estado confirmada (saltea borrador,
    # el vendedor ya confirmo). Sin modo vendedor: comportamiento original.
    if is_vendedor_mode:
        tipo = "preventa"
        estado_inicial = "preventa_confirmada"
    else:
        estado_inicial = "preventa_borrador" if tipo == "preventa" else "borrador"

    # Validación de bodega + fallback legacy (ítems sin catalogo_id).
    dist_fallback = db.get_distribuidor_pedido_de_bodega(data.bodega_id)
    if not dist_fallback:
        return {"ok": False, "error": "Bodega no encontrada"}

    # 12-jun-2026: el distribuidor del pedido se resuelve desde los productos
    # del carrito. OJO: el frontend manda en 'catalogo_id' el UUID de
    # productos_circa (no el de catalogo_distribuidor); se resuelve contra los
    # distribuidores activos de la bodega. Si un producto lo venden varios,
    # gana DIMAX como principal (determinístico) — el fix real es que el
    # frontend mande el UUID de catalogo_distribuidor (Paquete 2).
    # Guardia temporal: carritos que mezclan distribuidores se rechazan hasta
    # que exista el split por grupo de compra (pedidos.grupo_compra_id).
    from app.services.distribuidor_routing import DIMAX_DISTRIBUIDOR_ID as _DIMAX_ID
    dist_bodega = db.get_distribuidores_de_bodega(data.bodega_id)
    producto_ids = [i.get("catalogo_id") for i in items_list if i.get("catalogo_id")]
    prod_map = db.get_distribuidores_de_productos(producto_ids, dist_bodega)

    dist_set = set()
    for pid in producto_ids:
        candidatos = sorted(prod_map.get(pid) or [])
        if not candidatos:
            continue
        if _DIMAX_ID in candidatos:
            dist_set.add(_DIMAX_ID)
        else:
            dist_set.add(candidatos[0])

    if len(dist_set) > 1:
        return {
            "ok": False,
            "error": "Tu pedido mezcla productos de dos proveedores. Por ahora confírmalos como pedidos separados.",
        }
    dist_pedido = dist_set.pop() if dist_set else dist_fallback

    # Create order in pedidos
    pedido_payload = {
        "bodega_id": data.bodega_id,
        "distribuidor_id": dist_pedido,
        "items_json": json.dumps(items_list),
        "monto_productos": total,
        "total_pedido": total,
        "descuento_prorrateado": descuento,
        "estado": estado_inicial,
        "tipo_operacion": tipo,
    }
    if is_vendedor_mode:
        pedido_payload["vendedor_id"] = vendedor_id
        pedido_payload["link_token"] = link_token
        pedido_payload["origen"] = "preventa_vendedor_app"

    pedido = db.sb.table("pedidos").insert(pedido_payload).execute()
    pedido_id = pedido.data[0]["id"] if pedido.data else None
    pedido_numero = pedido.data[0].get("numero") if pedido.data else None

    if pedido_id:
        db.cerrar_borradores_abiertos(
            data.bodega_id, tipo, except_pedido_id=str(pedido_id)
        )
        # Persist cart so "Editar carrito" (edit=1) can reload line items.
        db.save_carrito(data.bodega_id, items_list)
        track_event(
            "preventa_created" if tipo == "preventa" else "order_created",
            bodega_id=data.bodega_id,
            pedido_id=pedido_id,
            source="vendedor_app" if is_vendedor_mode else "catalog_web",
            metadata={
                "tipo_operacion": tipo,
                "items_count": len(items_list),
                "total": round(total, 2),
                "vendedor_id": vendedor_id,
                "link_token": link_token,
            },
        )

    # === MODO VENDEDOR: enviar notificación automática al bodeguero (06-jul-2026) ===
    if is_vendedor_mode:
        try:
            import asyncio as _aio
            from app.flows.catalogo import notificar_preventa_bodeguero
            _aio.ensure_future(notificar_preventa_bodeguero(str(pedido_id)))
        except Exception as _ne:
            logger.warning(f"Auto-notify preventa vendedor: {_ne}")
        # Sigue devolviendo el link_token para la pantalla /share (fallback)
        return {
            "ok": True,
            "pedido_id": str(pedido_id) if pedido_id else None,
            "numero": pedido_numero,
            "link_token": link_token,
        }
    # === FIN MODO VENDEDOR ===

    # Comportamiento original para bodeguero (catalog_web):
    # For venta: send proactive payment options right after cart submit.
    # For preventa: ask explicit confirm step (no payment options yet).
    if tipo == "venta":
        bodega = db.sb.table("bodegas").select("telefono_whatsapp").eq("id", data.bodega_id).limit(1).execute()
        if bodega.data and pedido_id:
            phone = bodega.data[0]["telefono_whatsapp"].replace("+", "")
            items_text = "\n".join(f"{i.get('cantidad',1)}x {i.get('nombre','')} \u2014 S/{i.get('subtotal',0):.2f}" for i in items_list)
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
                f"\U0001f5d3\ufe0f *Pre-venta armada*\n\n"
                f"Total referencial: S/{total:.2f}\n"
                f"C\u00f3digo temporal: *PRV-{pid}*\n\n"
                f"Si todo est\u00e1 bien, confirma tu pre-venta con tu clave Circa.",
            )
            await meta_client.send_buttons(
                to=phone,
                body="\u00bfQu\u00e9 deseas hacer ahora?",
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


@app.post("/api/carrito/save")
async def save_carrito_api(data: dict):
    """Persist cart while browsing (same shape as submit-carrito items / get_carrito)."""
    bodega_id = data.get("bodega_id", "")
    raw = data.get("items")
    if not bodega_id or not isinstance(raw, list):
        return {"ok": False, "error": "bodega_id e items requeridos"}
    items_out = []
    for i in raw:
        if not isinstance(i, dict):
            continue
        cid = i.get("catalogo_id") or i.get("id")
        if not cid:
            continue
        pack = i.get("pack_size") or i.get("unit") or ""
        qty = int(i.get("cantidad") or i.get("qty") or 1)
        pr = float(i.get("precio") or 0)
        items_out.append({
            "catalogo_id": cid,
            "pack_size": pack,
            "nombre": i.get("nombre") or i.get("producto") or "",
            "marca": i.get("marca") or "",
            "cantidad": qty,
            "precio": pr,
            "subtotal": float(i.get("subtotal") or round(pr * qty, 2)),
        })
    db.save_carrito(bodega_id, items_out)
    return {"ok": True}


@app.get("/api/carrito/{bodega_id}")
async def get_carrito(bodega_id: str):
    cart = db.get_carrito(bodega_id)
    if not cart:
        return {"items": []}
    cart["items"] = db.normalize_carrito_items(cart.get("items"))
    return cart

@app.get("/catalogo")
async def catalogo_page():
    return FileResponse("static/catalogo.html")

@app.get("/catalogo-v2")
async def catalogo_v2_page():
    return FileResponse("static/catalogo_v2.html")

@app.get("/flyer")
async def flyer_page():
    return FileResponse("static/flyer.html")


@app.get("/support")
async def support_inbox_page(embedded: str | None = None):
    """Inbox embebido en backoffice; acceso directo redirige al portal unificado."""
    if embedded == "1":
        return FileResponse("static/support_inbox.html")
    from fastapi.responses import RedirectResponse

    return RedirectResponse(url="/backoffice#soporte", status_code=302)


@app.get("/admin")
async def admin_legacy_redirect():
    """Panel admin legacy → backoffice unificado."""
    from fastapi.responses import RedirectResponse

    return RedirectResponse(url="/backoffice", status_code=302)


@app.get("/backoffice")
async def backoffice_page():
    """Backoffice unificado Circa — operaciones y soporte."""
    return FileResponse("static/backoffice.html")


@app.get("/api/cobranza")
async def cobranza_pendiente(_admin: bool = Depends(verify_admin_token)):
    return db.sb.table("pagos").select("*, pedidos(numero, bodega_id, monto_total_credito, bodegas(nombre_comercial, telefono_whatsapp))").eq("estado", "pendiente").order("fecha_vencimiento").execute().data

# ── DEMO SIMULATION ──

@app.post("/api/demo/simulate-flow/{pedido_id}")
async def simulate_full_flow(pedido_id: str, _admin: bool = Depends(verify_admin_token)):
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
async def reset_demo(bodega_id: str, _admin: bool = Depends(verify_admin_token)):
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
async def debug_catalogo_response(_admin: bool = Depends(verify_admin_token)):
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
from app.services.promociones import evaluar_promociones as _evaluar_promociones, evaluar_bonificaciones as _evaluar_bonificaciones


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
    reglas_bonif = db.get_bonificaciones_activas(distribuidor_id)
    if not reglas and not reglas_bonif:
        items = [{
            "sku_distribuidor": i.sku_distribuidor,
            "subtotal": round(i.cantidad * i.precio_unitario_formato, 2),
            "descuento_aplicado": None,
            "siguiente_escalon": None,
        } for i in req.cart]
        subtotal = sum(it["subtotal"] for it in items)
        return {
            "items": items, "ahorro_total": 0,
            "subtotal_total": subtotal, "total_final": subtotal,
            "bonificaciones_aplicables": [], "bonificaciones_proximas": [],
            "valor_bonificaciones": 0
        }

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

    resultado = _evaluar_promociones(cart_enriched, reglas)

    # Evaluar bonificaciones (productos regalo)
    if reglas_bonif:
        bonif = _evaluar_bonificaciones(cart_enriched, reglas_bonif)
        resultado["bonificaciones_aplicables"] = bonif["aplicables"]
        resultado["bonificaciones_proximas"] = bonif["proximas"]
        resultado["valor_bonificaciones"] = bonif["valor_total_estimado"]
    else:
        resultado["bonificaciones_aplicables"] = []
        resultado["bonificaciones_proximas"] = []
        resultado["valor_bonificaciones"] = 0

    return resultado
