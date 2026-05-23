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
from app.services.fees import calculate_fee, format_rate_pct, fee_regimen_para_pedido_nuevo

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
    
    elif screen == "PIN_VERIFY":
        # Dedicated verify flow screen: force verify mode and reuse PIN handler
        data["mode"] = "verify"
        return _handle_pin_create(data)
    
    elif screen == "PIN_CONFIRM":
        return await _handle_pin_confirm(data, flow_token)
    
    else:
        logger.warning(f"Unknown PIN screen: {screen}")
        return {"data": {"error_msg": "Pantalla no reconocida."}}


def _handle_pin_create(data: dict) -> dict:
    """Validate PIN — either create new or verify for payment."""
    pin = (data.get("pin") or "").strip()
    bodega_id = data.get("bodega_id", "")
    mode = data.get("mode", "create")
    
    # Override mode based on actual pin_hash — ignore what Flow sends
    if bodega_id and bodega_id != "test":
        try:
            b_check = db.sb.table("bodegas").select("pin_hash").eq("id", bodega_id).limit(1).execute()
            if b_check.data:
                has_pin = bool(b_check.data[0].get("pin_hash"))
                if not has_pin:
                    mode = "create"
                    logger.info(f"PIN: no pin_hash found, forcing mode=create")
        except Exception as e:
            logger.error(f"PIN mode check: {e}")
    
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
            # Find bodega from most recent session (reg_pin or pin_pago)
            ses = db.sb.table("sesiones").select("bodega_id, fase").in_("fase", ["reg_pin", "pin_pago"]).order("last_activity", desc=True).limit(1).execute()
            if ses.data:
                bodega_id = ses.data[0].get("bodega_id", "")
                found_fase = ses.data[0].get("fase", "")
                if found_fase == "pin_pago":
                    mode = "verify"
                else:
                    mode = "create"
                logger.info(f"PIN: recovered bodega={bodega_id} from session fase={found_fase}, mode={mode}")
            else:
                logger.warning(f"PIN: no bodega_id and no session found")
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
                "mode": mode,
                "error_msg": "No puedes usar " + pin + ". Evita numeros repetidos (0000) o consecutivos (1234). Elige otra clave.",
            }
        }
    
    # Create mode: move to explicit confirm step (PIN_CONFIRM)
    if mode == "create":
        pin_hash_temp = hashlib.sha256(pin.encode()).hexdigest()
        return {
            "screen": "PIN_CONFIRM",
            "data": {
                "bodega_id": bodega_id,
                "pin_hash_temp": pin_hash_temp,
            }
        }
    
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
        if not pin_hash:
            # No PIN set yet — create it now
            from app.services.pin import hash_pin
            pin_hashed = hash_pin(pin)
            db.update_bodega(bodega_id, {
                "estado": "activo",
                "pin_hash": pin_hashed,
                "pin_intentos": 0,
            })
            telefono_c = bodega.data[0].get("telefono_whatsapp", "")
            if telefono_c:
                db.upsert_session(telefono_c, "menu", {}, bodega_id)
            return {"screen": "SUCCESS", "data": {"message": "Clave creada con éxito"}}
        if not bcrypt.checkpw(pin.encode(), pin_hash.encode()):
            return {"screen": "PIN_CREATE", "data": {"bodega_id": bodega_id, "mode": "verify", "error_msg": "Clave incorrecta."}}
        
        telefono = bodega.data[0].get("telefono_whatsapp", "")
        ses = db.sb.table("sesiones").select("datos").eq("telefono", telefono).eq("fase", "pin_pago").limit(1).execute()
        if not ses.data:
            return {"screen": "SUCCESS", "data": {"message": "No hay pedido pendiente."}}
        
        datos = json.loads(ses.data[0]["datos"]) if isinstance(ses.data[0]["datos"], str) else ses.data[0]["datos"]
        pedido_id = datos["pedido_id"]
        dias = int(datos.get("dias", 0) or 0)
        monto = float(datos["monto"])
        fee = 0.0
        rate = 0.0

        pe_st = db.sb.table("pedidos").select("id, estado, tipo_operacion").eq("id", pedido_id).limit(1).execute()
        if not pe_st.data:
            db.sb.table("sesiones").update({"fase": "menu", "datos": "{}"}).eq("telefono", telefono).execute()
            return {"screen": "SUCCESS", "data": {"message": "No encontramos ese pedido."}}
        if pe_st.data[0].get("estado") not in ("borrador", "preventa_borrador", "preventa_confirmada"):
            db.sb.table("sesiones").update({"fase": "menu", "datos": "{}"}).eq("telefono", telefono).execute()
            return {"screen": "SUCCESS", "data": {"message": "Este pedido ya estaba confirmado."}}
        tipo_operacion = pe_st.data[0].get("tipo_operacion", "venta")

        # Generate order number
        try:
            num = db.sb.rpc("gen_numero_pedido", {"p_prefijo": ("PRV" if tipo_operacion == "preventa" else "CRC")}).execute().data
        except Exception as e:
            logger.error(f"gen_numero_pedido error: {e}")
            import random
            pref = "PRV" if tipo_operacion == "preventa" else "CRC"
            num = f"{pref}-{random.randint(100,999)}"

        if dias > 0:
            bod_line = db.sb.table("bodegas").select("linea_disponible, linea_aprobada").eq("id", bodega_id).limit(1).execute()
            ld = float(bod_line.data[0].get("linea_disponible") or 0) if bod_line.data else 0.0
            if monto > ld + 1e-6:
                db.sb.table("sesiones").update({"fase": "menu", "datos": "{}"}).eq("telefono", telefono).execute()
                return {
                    "screen": "SUCCESS",
                    "data": {
                        "message": (
                            f"Tu tope disponible (S/{ld:.2f}) ya no alcanza para este financiamiento. "
                            "Cierra el flujo y arma el pedido de nuevo desde el menú."
                        ),
                    },
                }
            qfee = calculate_fee(monto, dias)
            fee = qfee["fee"]
            rate = qfee["rate"]
            _dist_ped = db.get_distribuidor_pedido_de_bodega(bodega_id)
            db.sb.table("pedidos").update({
                "numero": num,
                "distribuidor_id": _dist_ped,
                "fee_tasa": rate, "fee_monto": fee,
                "fee_regimen": fee_regimen_para_pedido_nuevo(),
                "monto_financiado": round(monto, 2), "plazo_dias": dias,
                "monto_total_credito": round(monto + fee, 2),
                "total": round(monto + fee, 2),
                "estado": ("preventa_confirmada" if tipo_operacion == "preventa" else "confirmado"),
            }).eq("id", pedido_id).execute()
            try:
                lap = float(bod_line.data[0].get("linea_aprobada") or ld) if bod_line.data else ld
                new_linea = max(ld - monto, 0.0)
                new_linea = min(new_linea, lap)
                db.sb.table("bodegas").update({"linea_disponible": new_linea}).eq("id", bodega_id).execute()
            except Exception as e:
                logger.error(f"Linea deduct: {e}")
            msg = f"Pedido #{num} confirmado\nFinanciado: S/{monto:.2f}\nCargo Circa: S/{fee:.2f}\nTotal: S/{monto+fee:.2f}\nPlazo: {dias} días"
        else:
            _dist_ped = db.get_distribuidor_pedido_de_bodega(bodega_id)
            db.sb.table("pedidos").update({
                "numero": num,
                "distribuidor_id": _dist_ped,
                "fee_tasa": 0, "fee_monto": 0,
                "monto_contado": round(monto, 2),
                "total": round(monto, 2),
                "estado": ("preventa_confirmada" if tipo_operacion == "preventa" else "confirmado"),
            }).eq("id", pedido_id).execute()
            msg = f"Pedido #{num} confirmado\nContado: S/{monto:.2f}"
        
        if tipo_operacion != "preventa":
            db.snapshot_ultimo_pedido_venta(bodega_id, pedido_id)

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
                from datetime import datetime, timedelta
                fecha_pago_conf = (datetime.now() + timedelta(days=dias)).strftime("%d/%m/%Y")
                conf_msg = (
                    f"\u2705 *Pedido #{num} confirmado*\n"
                    f"Financiado con Circa\n\n"
                    f"Financiado: *S/{monto:.2f}*\n"
                    f"Cuota Circa: *S/{monto+fee:.2f}*\n"
                    f"Plazo maximo: {dias} dias\n\n"
                    f"\U0001f7e3Yape / \U0001f7e2Plin  *986311567*\n"
                    f"Paga antes del {fecha_pago_conf} y escribe *YA PAGUE*"
                )
            else:
                conf_msg = (
                    f"\u2705 *Pedido #{num} confirmado — Contado*\n\n"
                    f"Total: S/{monto:.2f}\n"
                    "Tu distribuidor preparará tu pedido."
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
                    items_str += f" (+{len(items_raw)-3} más)"
                if not items_str:
                    items_str = "Ver detalle en WhatsApp"
                monto_prod = float(datos.get("monto_productos", 0) or datos.get("cart_total", 0) or 0)
                card_bytes = generate_order_confirmed_card(
                    numero=num, items_summary=items_str,
                    monto=monto, fee=fee, total=monto+fee if dias > 0 else monto,
                    dias=dias, vencimiento=venc, monto_productos=monto_prod,
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
                "error_msg": "Las claves no coinciden. Intenta de nuevo.",
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
        linea = bodega.data[0].get("linea_credito") or bodega.data[0].get("linea_disponible") or 500 if bodega.data else 500
        
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
