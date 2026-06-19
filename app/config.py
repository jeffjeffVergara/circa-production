"""Circa configuration — all settings from environment variables."""
import os
import re
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


def circa_soporte_wa_link() -> str | None:
    """
    Enlace wa.me al WhatsApp de soporte Circa (solo dígitos en env, con o sin +).
    Ej.: CIRCA_SOPORTE_WHATSAPP=51999888777
    """
    raw = os.getenv("CIRCA_SOPORTE_WHATSAPP", "").strip()
    digits = re.sub(r"\D", "", raw)
    if len(digits) < 9:
        return None
    return f"https://wa.me/{digits}"


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
# Bodegas es_test=true: aceptar cualquier DNI (8 dígitos) y cualquier foto como DNI/selfie (demos).
BIOMETRIA_RELAX_FOR_TEST_BODEGAS = os.getenv("BIOMETRIA_RELAX_FOR_TEST_BODEGAS", "true").strip().lower() in (
    "1",
    "true",
    "yes",
    "on",
)
# Umbral selfie vs foto DNI (0–1). Más bajo = menos falsos negativos en DNI gris vs selfie color.
FACE_MATCH_MIN_SCORE = float(os.getenv("FACE_MATCH_MIN_SCORE", "0.45"))
# Si el modelo marca face_match=false pero el score es alto, aceptar (mitiga mismos rechazos por lentes/edad).
FACE_MATCH_SCORE_OVERRIDE = float(os.getenv("FACE_MATCH_SCORE_OVERRIDE", "0.64"))
# Claude Vision (DNI/selfie). claude-sonnet-4-20250514 retirado 2026-06-15 → usar 4.6.
ANTHROPIC_VISION_MODEL = os.getenv("ANTHROPIC_VISION_MODEL", "claude-sonnet-4-6").strip()
# Foto anverso DNI: modo pragmático para fotos WhatsApp (ángulo, reflejo, rotación).
DNI_PHOTO_RELAXED = os.getenv("DNI_PHOTO_RELAXED", "true").strip().lower() in (
    "1",
    "true",
    "yes",
    "on",
)
# Selfie: no exigir estudio fotográfico; se comparará luego con foto del DNI (antigua/baja res).
SELFIE_LIVENESS_RELAXED = os.getenv("SELFIE_LIVENESS_RELAXED", "true").strip().lower() in (
    "1",
    "true",
    "yes",
    "on",
)
# Comparación selfie vs foto DNI (monocroma): umbrales y tolerancia a artefactos de impresión.
FACE_MATCH_DNI_GRAYSCALE_RELAXED = os.getenv("FACE_MATCH_DNI_GRAYSCALE_RELAXED", "true").strip().lower() in (
    "1",
    "true",
    "yes",
    "on",
)

# WhatsApp: flujo vendedor de campo (cartera/preventa por WA). false = todos entran como bodega.
VENDEDOR_WA_ENABLED = os.getenv("VENDEDOR_WA_ENABLED", "false").strip().lower() in (
    "1",
    "true",
    "yes",
    "on",
)

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

# ── Environment / secrets policy ──
CIRCA_ENV = os.getenv("CIRCA_ENV", os.getenv("RAILWAY_ENVIRONMENT", "development")).strip().lower()


def is_production() -> bool:
    return CIRCA_ENV in ("production", "prod")


def admin_token_or_raise() -> str:
    """Token admin; en producción es obligatorio vía env."""
    token = (os.getenv("CIRCA_ADMIN_TOKEN") or "").strip()
    if token:
        return token
    if is_production():
        raise HTTPExceptionProductionConfig("CIRCA_ADMIN_TOKEN no configurado")
    return "circa-admin-dev-only"


def backoffice_jwt_secret_or_raise() -> str:
    secret = (os.getenv("BACKOFFICE_JWT_SECRET") or os.getenv("CIRCA_ADMIN_TOKEN") or "").strip()
    if secret:
        return secret
    if is_production():
        raise HTTPExceptionProductionConfig("BACKOFFICE_JWT_SECRET no configurado")
    return "circa-backoffice-dev-only"


def backoffice_password_or_raise() -> str:
    password = (os.getenv("BACKOFFICE_PASSWORD") or "").strip()
    if password:
        return password
    if is_production():
        raise HTTPExceptionProductionConfig("BACKOFFICE_PASSWORD no configurado")
    return "circa-soporte-dev-only"


def backoffice_viewer_password_or_raise() -> str:
    password = (os.getenv("BACKOFFICE_VIEWER_PASSWORD") or "").strip()
    if password:
        return password
    if is_production():
        raise HTTPExceptionProductionConfig("BACKOFFICE_VIEWER_PASSWORD no configurado")
    return "circa-viewer-dev-only"


def backoffice_viewer_accounts() -> list[tuple[str, str]]:
    """Cuentas viewer: BACKOFFICE_VIEWER_CREDENTIALS o EMAIL+PASSWORD."""
    accounts: list[tuple[str, str]] = []
    seen: set[str] = set()

    raw = (os.getenv("BACKOFFICE_VIEWER_CREDENTIALS") or "").strip()
    if raw:
        for chunk in raw.split(","):
            piece = chunk.strip()
            if not piece or ":" not in piece:
                continue
            email, password = piece.split(":", 1)
            email = email.strip().lower()
            password = password.strip()
            if email and password and email not in seen:
                accounts.append((email, password))
                seen.add(email)

    email = (os.getenv("BACKOFFICE_VIEWER_EMAIL") or "").strip().lower()
    if email and email not in seen:
        password = (os.getenv("BACKOFFICE_VIEWER_PASSWORD") or "").strip()
        if not password and not is_production():
            password = "circa-viewer-dev-only"
        if password:
            accounts.append((email, password))
            seen.add(email)

    return accounts


def meta_verify_token_or_raise() -> str:
    token = (os.getenv("META_VERIFY_TOKEN") or "").strip()
    if token:
        return token
    if is_production():
        raise HTTPExceptionProductionConfig("META_VERIFY_TOKEN no configurado")
    return "circa-webhook-verify-dev"


class HTTPExceptionProductionConfig(RuntimeError):
    """Config obligatoria ausente en producción."""
