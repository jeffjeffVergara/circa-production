"""
WhatsApp Flow Endpoint — PIN Creation.

Handles the 2-screen PIN flow:
  PIN_CREATE → PIN_CONFIRM → SUCCESS (terminal)

Each request from WhatsApp contains encrypted:
  - screen: current screen ID
  - action: "INIT" | "data_exchange" | "BACK" | "ping"
  - data: user inputs from the current screen
  - flow_token: session identifier
"""
import logging
import hashlib
from app.services import db

logger = logging.getLogger("circa.flows.pin")


async def handle_pin_flow(flow_data: dict) -> dict:
    """Route PIN flow requests."""
    screen = flow_data.get("screen", "")
    action = flow_data.get("action", "")
    data = flow_data.get("data", {})
    flow_token = flow_data.get("flow_token", "")
    
    logger.info(f"PIN Flow: screen={screen}, action={action}, data_keys={list(data.keys())}, data={data}")
    
    # Health check ping from Meta
    if action == "ping":
        return {"version": "3.0", "data": {"status": "active"}}
    
    # Get result from handler, then add version
    result = await _route_pin(flow_data)
    if "version" not in result:
        result["version"] = "3.0"
    logger.info(f"PIN response: {result}")
    return result

async def _route_pin(flow_data: dict) -> dict:
    """Internal routing."""
    screen = flow_data.get("screen", "")
    action = flow_data.get("action", "")
    data = flow_data.get("data", {})
    flow_token = flow_data.get("flow_token", "")
    
    # INIT: Show first screen
    if action == "INIT":
        return {
            "screen": "PIN_CREATE",
            "data": {
                "bodega_id": data.get("bodega_id", ""),
                "error_msg": "",
            }
        }
    
    # Data exchange by screen
    if screen == "PIN_CREATE":
        return _handle_pin_create(data)
    
    elif screen == "PIN_CONFIRM":
        return await _handle_pin_confirm(data, flow_token)
    
    else:
        logger.warning(f"Unknown PIN screen: {screen}")
        return {"data": {"error_msg": "Pantalla no reconocida."}}


def _handle_pin_create(data: dict) -> dict:
    """Validate PIN — either create new or verify for payment."""
    # Check if this is actually a PIN confirmation (Flow reuses PIN_CREATE screen)
    if data.get("pin_hash_temp") and data.get("pin_confirm"):
        import asyncio
        return asyncio.get_event_loop().run_until_complete(
            _handle_pin_confirm(data, data.get("flow_token", ""))
        )
    
    pin = (data.get("pin") or "").strip()
    bodega_id = data.get("bodega_id", "")
    mode = data.get("mode", "create")
    
    logger.info(f"PIN create: mode={mode}, bodega_id={bodega_id}, pin_len={len(pin)}")
    
    if len(pin) != 4 or not pin.isdigit():
        return {
            "screen": "PIN_CREATE",
            "data": {
                "bodega_id": bodega_id,
                "mode": mode,
                "error_msg": "La clave debe ser exactamente 4 digitos.",
            }
        }
    
    # Check for pending session to get bodega_id
    if not bodega_id or bodega_id == "test":
        try:
            ses = db.sb.table("sesiones").select("bodega_id, fase").in_("fase", ["pin_pago", "reg_pin"]).limit(1).execute()
            if ses.data:
                bodega_id = ses.data[0].get("bodega_id", bodega_id)
                found_fase = ses.data[0].get("fase", "")
                if found_fase == "pin_pago":
                    mode = "verify"
                logger.info(f"PIN: found session fase={found_fase}, bodega={bodega_id}")
        except Exception as e:
            logger.error(f"Session lookup: {e}")
    
    # ── VERIFY MODE: check PIN against stored hash ──
    if mode == "verify":
        return _verify_pin_for_payment(pin, bodega_id)
    
    # Reject obvious sequences
    weak = {"0000", "1111", "2222", "3333", "4444", "5555",
            "6666", "7777", "8888", "9999", "1234", "4321",
            "0123", "3210", "1122", "2233"}
    if pin in weak:
        return {
            "screen": "PIN_CREATE",
            "data": {
                "bodega_id": bodega_id,
                "error_msg": "Elige una clave más segura. Evita secuencias.",
            }
        }
    
    # No PIN_CONFIRM screen in Flow — activate directly
    if mode == "create" and bodega_id:
        try:
            from app.services.pin import hash_pin
            pin_hashed = hash_pin(pin)
            db.update_bodega(bodega_id, {
                "estado": "activo",
                "pin_hash": pin_hashed,
                "pin_intentos": 0,
                "pin_bloqueado_hasta": None,
            })
            # Update session
            bodega = db.sb.table("bodegas").select("telefono_whatsapp, linea_disponible").eq("id", bodega_id).execute()
            telefono = bodega.data[0]["telefono_whatsapp"] if bodega.data else ""
            linea = bodega.data[0]["linea_disponible"] if bodega.data else 500
            if telefono:
                db.upsert_session(telefono, "menu", {}, bodega_id)
            # Send activation message via sync requests
            try:
                import requests as req
                import os
                token = os.getenv("META_ACCESS_TOKEN", "")
                phone_id = os.getenv("META_PHONE_NUMBER_ID", "1076586305533033")
                phone = telefono.replace("+", "")
                # Send branded activation card
                try:
                    from app.services.cards import generate_account_activated_card
                    bodega_full = db.sb.table("bodegas").select("nombre_comercial, razon_social, distribuidor_id").eq("id", bodega_id).limit(1).execute()
                    b_name = "Tu bodega"
                    dist_name = "Tu distribuidor"
                    if bodega_full.data:
                        b_name = bodega_full.data[0].get("nombre_comercial") or bodega_full.data[0].get("razon_social", b_name)
                        d_id = bodega_full.data[0].get("distribuidor_id")
                        if d_id:
                            d_r = db.sb.table("distribuidores").select("nombre_comercial").eq("id", d_id).limit(1).execute()
                            if d_r.data:
                                dist_name = d_r.data[0]["nombre_comercial"]
                    card_bytes = generate_account_activated_card(b_name, linea, dist_name)
                    
                    # Upload and send card image
                    import tempfile
                    tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
                    tmp.write(card_bytes)
                    tmp.close()
                    
                    # Upload media
                    upload_r = req.post(
                        f"https://graph.facebook.com/v23.0/{phone_id}/media",
                        headers={"Authorization": f"Bearer {token}"},
                        data={"messaging_product": "whatsapp", "type": "image/png"},
                        files={"file": ("card.png", open(tmp.name, "rb"), "image/png")},
                        timeout=15,
                    )
                    if upload_r.status_code == 200:
                        media_id = upload_r.json().get("id")
                        req.post(
                            f"https://graph.facebook.com/v23.0/{phone_id}/messages",
                            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                            json={"messaging_product": "whatsapp", "to": phone, "type": "image",
                                  "image": {"id": media_id, "caption": "\U0001f512 Clave creada \u2022 \u2705 Cuenta activada\n\nEscribe MENU para empezar a pedir."}},
                            timeout=10,
                        )
                    import os as _os2
                    _os2.unlink(tmp.name)
                except Exception as card_err:
                    logger.error(f"Card generation error: {card_err}")
                    # Fallback to text
                    req.post(
                        f"https://graph.facebook.com/v23.0/{phone_id}/messages",
                        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                        json={"messaging_product": "whatsapp", "to": phone, "type": "text",
                              "text": {"body": f"\U0001f512 *Clave creada con exito*\n\n\u2705 *Cuenta activada*\nCredito disponible: *S/{linea:.2f}*\n\nEscribe MENU para empezar a pedir."}},
                        timeout=10,
                    )
            except Exception as e:
                logger.error(f"Activation msg error: {e}")
            logger.info(f"Bodega {bodega_id} activated via PIN Flow (single step)")
            return {"screen": "SUCCESS", "data": {"message": f"Clave creada. Linea: S/{linea:.2f}"}}
        except Exception as e:
            logger.error(f"PIN activate error: {e}", exc_info=True)
            return {"screen": "PIN_CREATE", "data": {"bodega_id": bodega_id, "error_msg": "Error al activar. Intenta de nuevo."}}
    
    # Fallback — should not reach here
    return {
        "screen": "PIN_CREATE",
        "data": {
            "bodega_id": bodega_id,
            "error_msg": "",
        }
    }


def _verify_pin_for_payment(pin: str, bodega_id: str) -> dict:
    """Verify PIN and confirm the pending order."""
    import bcrypt, json
    try:
        bodega = db.sb.table("bodegas").select("pin_hash, telefono_whatsapp").eq("id", bodega_id).limit(1).execute()
        if not bodega.data:
            return {"screen": "PIN_CREATE", "data": {"bodega_id": bodega_id, "mode": "verify", "error_msg": "Bodega no encontrada."}}
        
        pin_hash = bodega.data[0].get("pin_hash", "")
        if not pin_hash or not bcrypt.checkpw(pin.encode(), pin_hash.encode()):
            return {"screen": "PIN_CREATE", "data": {"bodega_id": bodega_id, "mode": "verify", "error_msg": "Clave incorrecta."}}
        
        telefono = bodega.data[0].get("telefono_whatsapp", "")
        ses = db.sb.table("sesiones").select("datos").eq("telefono", telefono).eq("fase", "pin_pago").limit(1).execute()
        if not ses.data:
            return {"screen": "SUCCESS", "data": {"message": "No hay pedido pendiente."}}
        
        datos = json.loads(ses.data[0]["datos"]) if isinstance(ses.data[0]["datos"], str) else ses.data[0]["datos"]
        pedido_id = datos["pedido_id"]
        dias = datos.get("dias", 0)
        rate = datos.get("rate", 0)
        monto = datos["monto"]
        fee = datos.get("fee", 0)
        
        # Generate order number
        existing = db.sb.table("pedidos").select("numero").eq("bodega_id", bodega_id).not_.is_("numero", "null").order("created_at", desc=True).limit(1).execute()
        n = 1
        if existing.data and existing.data[0].get("numero"):
            try:
                n = int(existing.data[0]["numero"].split("-")[1]) + 1
            except:
                n = 1
        num = f"CRC-{n:03d}"
        
        if dias > 0:
            db.sb.table("pedidos").update({
                "numero": num, "fee_tasa": rate, "fee_monto": fee,
                "monto_financiado": round(monto, 2), "plazo_dias": dias,
                "total": round(monto + fee, 2), "estado": "confirmado",
            }).eq("id", pedido_id).execute()
            # Deduct line
            try:
                bod = db.sb.table("bodegas").select("linea_disponible").eq("id", bodega_id).limit(1).execute()
                new_linea = max((bod.data[0]["linea_disponible"] or 0) - monto, 0) if bod.data else 0
                db.sb.table("bodegas").update({"linea_disponible": new_linea}).eq("id", bodega_id).execute()
            except Exception as e:
                logger.error(f"Linea deduct: {e}")
            msg = f"Pedido #{num} confirmado\nFinanciado: S/{monto:.2f}\nFee: S/{fee:.2f}\nTotal: S/{monto+fee:.2f}\nPlazo: {dias} dias"
        else:
            db.sb.table("pedidos").update({
                "numero": num, "fee_tasa": 0, "fee_monto": 0,
                "monto_contado": round(monto, 2), "total": round(monto, 2), "estado": "confirmado",
            }).eq("id", pedido_id).execute()
            msg = f"Pedido #{num} confirmado\nContado: S/{monto:.2f}"
        
        # Mark session as done - WA message will be sent by webhook handler
        db.sb.table("sesiones").update({"fase": "menu", "datos": json.dumps({"num": num, "pedido_id": pedido_id, "dias": dias, "monto": monto, "fee": fee, "rate": rate})}).eq("telefono", telefono).execute()
        
        logger.info(f"Order {pedido_id} confirmed via PIN Flow: {num}")
        
        # Send WhatsApp confirmation (sync, using requests directly)
        try:
            import requests as req
            import os
            token = os.getenv("META_ACCESS_TOKEN", "")
            phone_id = os.getenv("PHONE_NUMBER_ID", "1076586305533033")
            phone = telefono.replace("+", "")
            if dias > 0:
                conf_msg = (
                    f"\u2705 *Pedido #{num} confirmado*\n"
                    f"Financiado con Circa\n\n"
                    f"Financiado: *S/{monto:.2f}*\n"
                    f"Fee ({int(rate*100)}%): S/{fee:.2f}\n"
                    f"Total credito: *S/{monto+fee:.2f}*\n"
                    f"Plazo: {dias} dias\n\n"
                    f"Recibiras actualizaciones por WhatsApp."
                )
            else:
                conf_msg = (
                    f"\u2705 *Pedido #{num} confirmado — Contado*\n\n"
                    f"Total: S/{monto:.2f}\n"
                    f"Tu distribuidor preparara tu pedido."
                )
            req.post(
                f"https://graph.facebook.com/v23.0/{phone_id}/messages",
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                json={"messaging_product": "whatsapp", "to": phone, "type": "text", "text": {"body": conf_msg}},
                timeout=10,
            )
            logger.info(f"Confirmation sent to {phone}")
            # Send branded order confirmation card
            try:
                from app.services.cards import generate_order_confirmed_card
                from datetime import datetime, timedelta
                venc = (datetime.now() + timedelta(days=dias)).strftime("%d/%m/%Y") if dias > 0 else "Contado"
                items_raw = datos.get("items", [])
                items_str = ", ".join([i.get("nombre", i.get("producto", "?"))[:20] for i in items_raw][:3])
                if len(items_raw) > 3:
                    items_str += f" (+{len(items_raw)-3} mas)"
                if not items_str:
                    items_str = "Ver detalle en WhatsApp"
                card_bytes = generate_order_confirmed_card(
                    numero=num, items_summary=items_str,
                    monto=monto, fee=fee, total=monto+fee if dias > 0 else monto,
                    dias=dias, vencimiento=venc,
                )
                import tempfile
                tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
                tmp.write(card_bytes)
                tmp.close()
                upload_r = req.post(
                    f"https://graph.facebook.com/v23.0/{phone_id}/media",
                    headers={"Authorization": f"Bearer {token}"},
                    data={"messaging_product": "whatsapp", "type": "image/png"},
                    files={"file": ("order_card.png", open(tmp.name, "rb"), "image/png")},
                    timeout=15,
                )
                if upload_r.status_code == 200:
                    media_id = upload_r.json().get("id")
                    req.post(
                        f"https://graph.facebook.com/v23.0/{phone_id}/messages",
                        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                        json={"messaging_product": "whatsapp", "to": phone, "type": "image",
                              "image": {"id": media_id}},
                        timeout=10,
                    )
                    logger.info(f"Order card sent for {num}")
                import os as _os3
                _os3.unlink(tmp.name)
            except Exception as card_err:
                logger.error(f"Order card error: {card_err}")
        except Exception as e:
            logger.error(f"Confirmation msg error: {e}")
        
        return {"screen": "SUCCESS", "data": {"message": msg}}
    
    except Exception as e:
        logger.error(f"PIN verify error: {e}", exc_info=True)
        return {"screen": "PIN_CREATE", "data": {"bodega_id": bodega_id, "mode": "verify", "error_msg": "Error. Intenta de nuevo."}}


async def _handle_pin_confirm(data: dict, flow_token: str) -> dict:
    """Verify PINs match and activate account."""
    pin_confirm = (data.get("pin_confirm") or "").strip()
    pin_hash_temp = data.get("pin_hash_temp", "")
    bodega_id = data.get("bodega_id", "")
    
    # Verify match
    confirm_hash = hashlib.sha256(pin_confirm.encode()).hexdigest()
    if confirm_hash != pin_hash_temp:
        return {
            "screen": "PIN_CONFIRM",
            "data": {
                "bodega_id": bodega_id,
                "pin_hash_temp": pin_hash_temp,
            }
        }
    
    # Activate the bodega
    try:
        from app.services.pin import hash_pin
        pin_hashed = hash_pin(pin_confirm)
        db.update_bodega(bodega_id, {
            "estado": "activo",
            "pin_hash": pin_hashed,
            "pin_intentos": 0,
            "pin_bloqueado_hasta": None,
        })
        
        # Sign contract
        contract_hash = hashlib.sha256(f"{bodega_id}|pin_flow".encode()).hexdigest()
        db.sign_contract(bodega_id, contract_hash[:16])
        
        # Update session to menu
        bodega = db.sb.table("bodegas").select("telefono_whatsapp, linea_disponible").eq("id", bodega_id).execute()
        telefono = bodega.data[0]["telefono_whatsapp"] if bodega.data else ""
        linea = bodega.data[0]["linea_disponible"] if bodega.data else 500
        
        if telefono:
            db.upsert_session(telefono, "menu", {}, bodega_id)
        
        logger.info(f"Bodega {bodega_id} activated via PIN Flow")
        
        # Terminal response — closes the Flow
        return {
            "screen": "SUCCESS",
            "data": {
                "message": "Tu clave fue creada correctamente.",
                "linea": f"S/{linea:.2f}",
                "extension_message_response": {
                    "params": {
                        "flow_token": flow_token,
                        "status": "activated",
                        "bodega_id": bodega_id,
                    }
                }
            }
        }
        
    except Exception as e:
        logger.error(f"Failed to activate bodega {bodega_id}: {e}", exc_info=True)
        return {
            "screen": "PIN_CREATE",
            "data": {
                "bodega_id": bodega_id,
                "error_msg": "Error al activar. Intenta de nuevo.",
            }
        }
