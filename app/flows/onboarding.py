"""
WhatsApp Flow Endpoint — Onboarding.

Handles the multi-screen onboarding flow:
  WELCOME → RUC_INPUT → RUC_CONFIRM → TERMS → PIN_CREATE → PIN_CONFIRM

Each request from WhatsApp contains:
  - screen: current screen ID
  - action: "INIT" | "data_exchange" | "BACK"
  - data: user inputs from the current screen
  - flow_token: session identifier

We respond with the next screen's data or a terminal action.
"""
import logging
import hashlib
from app.services import db
from app.services.identity import consultar_ruc, validate_ruc_format, is_ruc_eligible

logger = logging.getLogger("circa.flows.onboarding")


async def handle_onboarding(flow_data: dict) -> dict:
    """
    Route onboarding flow requests to the appropriate handler.
    
    Args:
        flow_data: Decrypted request from WhatsApp
            {
                "screen": "RUC_INPUT",
                "action": "data_exchange",
                "data": {"ruc": "20512345678"},
                "flow_token": "abc123",
                "version": "3.0"
            }
    
    Returns:
        Response dict for the next screen or flow termination
    """
    screen = flow_data.get("screen", "")
    action = flow_data.get("action", "")
    data = flow_data.get("data", {})
    flow_token = flow_data.get("flow_token", "")
    
    logger.info(f"Onboarding: screen={screen}, action={action}")
    
    # ── INIT: First screen ──
    if action == "INIT":
        return _screen_ruc_input()
    
    # ── Data exchange by screen ──
    if screen == "RUC_INPUT":
        return await _handle_ruc_input(data, flow_token)
    
    elif screen == "RUC_CONFIRM":
        return _handle_ruc_confirm(data, flow_token)
    
    elif screen == "TERMS":
        return _handle_terms(data, flow_token)
    
    elif screen == "PIN_CREATE":
        return _handle_pin_create(data, flow_token)
    
    elif screen == "PIN_CONFIRM":
        return await _handle_pin_confirm(data, flow_token)
    
    else:
        logger.warning(f"Unknown onboarding screen: {screen}")
        return _error_response("Pantalla no reconocida. Intenta de nuevo.")


# ══════════════════════════════════════════════
# SCREEN HANDLERS
# ══════════════════════════════════════════════

def _screen_ruc_input() -> dict:
    """Show RUC input screen."""
    return {
        "screen": "RUC_INPUT",
        "data": {
            "title": "Activa tu cuenta Circa",
            "description": "Ingresa el RUC de tu negocio (11 dígitos)",
        }
    }


async def _handle_ruc_input(data: dict, flow_token: str) -> dict:
    """Validate RUC and show confirmation."""
    ruc = (data.get("ruc") or "").strip()
    
    # Format validation
    valid, error_msg = validate_ruc_format(ruc)
    if not valid:
        return {
            "screen": "RUC_INPUT",
            "data": {
                "error_messages": {"ruc": error_msg}
            }
        }
    
    # Check if bodega exists in our system
    bodega = db.get_bodega_by_ruc(ruc)
    if not bodega:
        return {
            "screen": "RUC_INPUT",
            "data": {
                "error_messages": {"ruc": "Este RUC no tiene una línea pre-aprobada en Circa."}
            }
        }
    
    # Try to get fresh data from SUNAT
    sunat_data = None
    try:
        sunat_data = await consultar_ruc(ruc)
    except Exception as e:
        logger.warning(f"SUNAT lookup failed for {ruc}: {e}")
    
    # Check eligibility if we got SUNAT data
    if sunat_data:
        eligible, reason = is_ruc_eligible(sunat_data)
        if not eligible:
            return {
                "screen": "RUC_INPUT",
                "data": {
                    "error_messages": {"ruc": reason}
                }
            }
        razon_social = sunat_data.get("razon_social") or bodega.get("razon_social", "")
        direccion = sunat_data.get("direccion") or bodega.get("direccion_fiscal", "")
        rep_legal = sunat_data.get("rep_legal") or bodega.get("representante_legal", "")
    else:
        # Fallback to pre-loaded data
        razon_social = bodega.get("razon_social", "")
        direccion = bodega.get("direccion_fiscal", "")
        rep_legal = bodega.get("representante_legal", "")
    
    # Navigate to confirmation screen
    return {
        "screen": "RUC_CONFIRM",
        "data": {
            "ruc": ruc,
            "razon_social": razon_social,
            "direccion": direccion,
            "rep_legal": rep_legal or "No disponible",
            "bodega_id": bodega["id"],
            "linea_aprobada": bodega.get("linea_aprobada", 500),
        }
    }


def _handle_ruc_confirm(data: dict, flow_token: str) -> dict:
    """User confirmed RUC data, proceed to terms."""
    import os
    base_url = os.getenv("APP_BASE_URL", "")
    
    return {
        "screen": "TERMS",
        "data": {
            "bodega_id": data.get("bodega_id", ""),
            "ruc": data.get("ruc", ""),
            "razon_social": data.get("razon_social", ""),
            "linea_aprobada": data.get("linea_aprobada", 500),
            "contrato_url": f"{base_url}/static/contrato_circa.pdf",
            "terms_bullets": (
                "• Línea de crédito revolving\n"
                "• Tasas de 5% a 12% según plazo\n"
                "• Plazos: 7, 15 o 30 días\n"
                "• El dinero va directo al distribuidor\n"
                "• Sin costo de apertura ni mantenimiento\n"
                "• Al aceptar, autorizas consulta en centrales de riesgo"
            ),
        }
    }


def _handle_terms(data: dict, flow_token: str) -> dict:
    """User accepted terms, proceed to PIN creation."""
    # TODO: Store contract acceptance in DB
    # db.sign_contract(data["bodega_id"], contract_version, timestamp)
    
    return {
        "screen": "PIN_CREATE",
        "data": {
            "bodega_id": data.get("bodega_id", ""),
            "description": "Crea tu clave Circa de 4 dígitos. Se usará para confirmar cada pedido financiado.",
            "hint": "No uses fechas de nacimiento ni secuencias como 1234.",
        }
    }


def _handle_pin_create(data: dict, flow_token: str) -> dict:
    """User entered PIN, ask to confirm."""
    pin = data.get("pin", "")
    
    # Basic validation
    if len(pin) != 4 or not pin.isdigit():
        return {
            "screen": "PIN_CREATE",
            "data": {
                "error_messages": {"pin": "La clave debe ser exactamente 4 dígitos."},
                "bodega_id": data.get("bodega_id", ""),
            }
        }
    
    # Check for obvious sequences
    if pin in ("0000", "1111", "2222", "3333", "4444", "5555", 
               "6666", "7777", "8888", "9999", "1234", "4321"):
        return {
            "screen": "PIN_CREATE",
            "data": {
                "error_messages": {"pin": "Elige una clave más segura. Evita secuencias repetidas."},
                "bodega_id": data.get("bodega_id", ""),
            }
        }
    
    return {
        "screen": "PIN_CONFIRM",
        "data": {
            "bodega_id": data.get("bodega_id", ""),
            "pin_hash_temp": hashlib.sha256(pin.encode()).hexdigest(),
        }
    }


async def _handle_pin_confirm(data: dict, flow_token: str) -> dict:
    """User confirmed PIN, activate account."""
    pin_confirm = data.get("pin_confirm", "")
    pin_hash_temp = data.get("pin_hash_temp", "")
    bodega_id = data.get("bodega_id", "")
    
    # Verify PINs match
    confirm_hash = hashlib.sha256(pin_confirm.encode()).hexdigest()
    if confirm_hash != pin_hash_temp:
        return {
            "screen": "PIN_CONFIRM",
            "data": {
                "error_messages": {"pin_confirm": "Las claves no coinciden. Intenta de nuevo."},
                "bodega_id": bodega_id,
                "pin_hash_temp": pin_hash_temp,
            }
        }
    
    # Activate the bodega
    try:
        import bcrypt
        pin_hash = bcrypt.hashpw(pin_confirm.encode(), bcrypt.gensalt()).decode()
        db.activate_bodega(bodega_id, pin_hash)
        
        # Store contract acceptance
        db.sign_contract(bodega_id, confirm_hash[:16])
        
        logger.info(f"Bodega {bodega_id} activated successfully")
    except Exception as e:
        logger.error(f"Failed to activate bodega {bodega_id}: {e}")
        return _error_response("Error al activar tu cuenta. Intenta de nuevo.")
    
    # Terminal response — closes the Flow
    return {
        "screen": "SUCCESS",
        "data": {
            "extension_message_response": {
                "params": {
                    "flow_token": flow_token,
                    "status": "activated",
                    "bodega_id": bodega_id,
                }
            }
        }
    }


def _error_response(message: str) -> dict:
    """Return error that keeps user on current screen."""
    return {
        "data": {
            "error": message,
        }
    }
