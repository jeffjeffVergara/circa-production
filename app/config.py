"""Circa configuration — all settings from environment variables."""
import os
from datetime import datetime
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

load_dotenv()

# Hora mostrada en documentos y operación comercial (Perú = GMT-5, sin DST).
APP_TZ = ZoneInfo(os.getenv("APP_TZ", "America/Lima"))


def now_peru() -> datetime:
    """Fecha y hora actual en zona Perú (p. ej. contratos, firmas)."""
    return datetime.now(APP_TZ)

# ── Supabase ──
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_KEY", "")

# ── Twilio (legacy — being replaced by Meta Cloud API) ──
TWILIO_SID = os.getenv("TWILIO_ACCOUNT_SID", "")
TWILIO_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "")
TWILIO_FROM = os.getenv("TWILIO_WHATSAPP_FROM", "whatsapp:+14155238886")

# ── Meta Cloud API (WhatsApp) ──
META_PHONE_NUMBER_ID = os.getenv("META_PHONE_NUMBER_ID", "")
META_ACCESS_TOKEN = os.getenv("META_ACCESS_TOKEN", "")
META_APP_SECRET = os.getenv("META_APP_SECRET", "")
META_VERIFY_TOKEN = os.getenv("META_VERIFY_TOKEN", "circa-webhook-verify-2026")
META_WABA_ID = os.getenv("META_WABA_ID", "")

# ── WhatsApp Flow IDs ──
FLOW_ONBOARDING_ID = os.getenv("FLOW_ONBOARDING_ID", "")
FLOW_CATALOGO_ID = os.getenv("FLOW_CATALOGO_ID", "")
FLOW_PRIVATE_KEY = os.getenv("FLOW_PRIVATE_KEY", "")

# ── App ──
APP_BASE_URL = os.getenv("APP_BASE_URL", "http://localhost:8000")
YAPE_PHONE = os.getenv("YAPE_PHONE", "986311567")
YAPE_NAME = os.getenv("YAPE_NAME", "Circa Lab S.A.C.")
PLIN_PHONE = os.getenv("PLIN_PHONE", "986311567")

# ── Security ──
PIN_MAX_ATTEMPTS = 3
PIN_BLOCK_MINUTES = 30
SESSION_TIMEOUT_MINUTES = 5
CART_TTL_HOURS = 24

# ── Biometrics ──
# BIOMETRIA_MODE:
# - strict: selfie valida + face match selfie vs DNI (v2)
# - legacy: comportamiento anterior (sin face match y fallbacks permisivos)
BIOMETRIA_MODE = os.getenv("BIOMETRIA_MODE", "strict").strip().lower()
# Umbral selfie vs foto DNI (0–1). Más bajo = menos falsos negativos, más riesgo de falso positivo.
FACE_MATCH_MIN_SCORE = float(os.getenv("FACE_MATCH_MIN_SCORE", "0.56"))
# Si el modelo marca face_match=false pero el score es alto, aceptar (mitiga mismos rechazos por lentes/edad).
FACE_MATCH_SCORE_OVERRIDE = float(os.getenv("FACE_MATCH_SCORE_OVERRIDE", "0.64"))

# ── SUNAT / RENIEC API ──
# Supports: apiinti.dev, peruapi.com, apiperu.dev, apis.net.pe
PERU_API_PROVIDER = os.getenv("PERU_API_PROVIDER", "apiinti")  # apiinti | peruapi | apiperu
PERU_API_TOKEN = os.getenv("PERU_API_TOKEN", "")

# ── Content Template SIDs (Twilio) ──
TWILIO_TEMPLATE_MENU = os.getenv("TWILIO_TEMPLATE_MENU", "")
TWILIO_TEMPLATE_CATEGORIAS = os.getenv("TWILIO_TEMPLATE_CATEGORIAS", "")
TWILIO_TEMPLATE_PRODUCTOS_BEBIDAS = os.getenv("TWILIO_TEMPLATE_PRODUCTOS_BEBIDAS", "")
TWILIO_TEMPLATE_PRODUCTOS_LACTEOS = os.getenv("TWILIO_TEMPLATE_PRODUCTOS_LACTEOS", "")
TWILIO_TEMPLATE_PRODUCTOS_ABARROTES = os.getenv("TWILIO_TEMPLATE_PRODUCTOS_ABARROTES", "")
TWILIO_TEMPLATE_PRODUCTOS_CUIDADO = os.getenv("TWILIO_TEMPLATE_PRODUCTOS_CUIDADO", "")
TWILIO_TEMPLATE_PACK = os.getenv("TWILIO_TEMPLATE_PACK", "")
TWILIO_TEMPLATE_CANTIDAD = os.getenv("TWILIO_TEMPLATE_CANTIDAD", "")
TWILIO_TEMPLATE_ITEM_AGREGADO = os.getenv("TWILIO_TEMPLATE_ITEM_AGREGADO", "")
TWILIO_TEMPLATE_CARRITO = os.getenv("TWILIO_TEMPLATE_CARRITO", "")
TWILIO_TEMPLATE_MONTO = os.getenv("TWILIO_TEMPLATE_MONTO", "")
TWILIO_TEMPLATE_PLAZO = os.getenv("TWILIO_TEMPLATE_PLAZO", "")
TWILIO_TEMPLATE_LINEA = os.getenv("TWILIO_TEMPLATE_LINEA", "")

# ── Distribuidor notifications ──
DISTRIBUIDOR_WA_NUMERO = os.getenv("DISTRIBUIDOR_WA_NUMERO", "")  # Para notificar pedidos
