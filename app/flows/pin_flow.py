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
    
    logger.info(f"PIN Flow: screen={screen}, action={action}")
    
    # Health check ping from Meta
    if action == "ping":
        return {"data": {"status": "active"}}
    
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
    """Validate PIN and proceed to confirmation."""
    pin = (data.get("pin") or "").strip()
    bodega_id = data.get("bodega_id", "")
    
    if len(pin) != 4 or not pin.isdigit():
        return {
            "screen": "PIN_CREATE",
            "data": {
                "bodega_id": bodega_id,
                "error_msg": "La clave debe ser exactamente 4 dígitos.",
            }
        }
    
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
    
    # Pass hash to confirmation screen (PIN never stored in plaintext)
    return {
        "screen": "PIN_CONFIRM",
        "data": {
            "bodega_id": bodega_id,
            "pin_hash_temp": hashlib.sha256(pin.encode()).hexdigest(),
        }
    }


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
