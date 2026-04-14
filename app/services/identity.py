"""
Identity verification service — SUNAT (RUC) and RENIEC (DNI).

Supports multiple Peruvian API providers:
- apiinti.dev  (free: 200 queries/month)
- peruapi.com  (free: 100/day, 1000/month)  
- apiperu.dev  (paid plans from S/19/month)

All return similar JSON structures. This module normalizes the response.
"""
import httpx
import logging
from app.config import PERU_API_PROVIDER, PERU_API_TOKEN

logger = logging.getLogger("circa.identity")

TIMEOUT = 10.0  # seconds


# ══════════════════════════════════════════════
# PUBLIC API
# ══════════════════════════════════════════════

async def consultar_ruc(ruc: str) -> dict | None:
    """
    Query SUNAT for RUC data. Returns normalized dict or None on failure.
    
    Returns:
        {
            "ruc": "20512345678",
            "razon_social": "BODEGA DON PEPE E.I.R.L.",
            "estado": "ACTIVO",           # ACTIVO | BAJA DE OFICIO | SUSPENSION TEMPORAL
            "condicion": "HABIDO",         # HABIDO | NO HABIDO | NO HALLADO
            "direccion": "JR. LIMA 234",
            "distrito": "SURQUILLO",
            "provincia": "LIMA",
            "departamento": "LIMA",
            "rep_legal": None,             # Not all providers return this
        }
    """
    if not ruc or len(ruc) != 11 or not ruc.isdigit():
        return None
    
    try:
        if PERU_API_PROVIDER == "apiinti":
            return await _ruc_apiinti(ruc)
        elif PERU_API_PROVIDER == "peruapi":
            return await _ruc_peruapi(ruc)
        elif PERU_API_PROVIDER == "apiperu":
            return await _ruc_apiperu(ruc)
        else:
            logger.error(f"Unknown PERU_API_PROVIDER: {PERU_API_PROVIDER}")
            return None
    except Exception as e:
        logger.error(f"Error consulting RUC {ruc}: {e}")
        return None


async def consultar_dni(dni: str) -> dict | None:
    """
    Query RENIEC for DNI data. Returns normalized dict or None on failure.
    
    Returns:
        {
            "dni": "12345678",
            "nombres": "JUAN FERNANDO",
            "apellido_paterno": "PEREZ",
            "apellido_materno": "QUISPE",
            "nombre_completo": "PEREZ QUISPE JUAN FERNANDO",
        }
    """
    if not dni or len(dni) != 8 or not dni.isdigit():
        return None
    
    try:
        if PERU_API_PROVIDER == "apiinti":
            return await _dni_apiinti(dni)
        elif PERU_API_PROVIDER == "peruapi":
            return await _dni_peruapi(dni)
        elif PERU_API_PROVIDER == "apiperu":
            return await _dni_apiperu(dni)
        else:
            logger.error(f"Unknown PERU_API_PROVIDER: {PERU_API_PROVIDER}")
            return None
    except Exception as e:
        logger.error(f"Error consulting DNI {dni}: {e}")
        return None


def validate_ruc_format(ruc: str) -> tuple[bool, str]:
    """Validate RUC format before making API call."""
    if not ruc or not ruc.isdigit():
        return False, "El RUC debe contener solo números."
    if len(ruc) != 11:
        return False, "El RUC debe tener 11 dígitos."
    if not ruc.startswith(("10", "20")):
        return False, "El RUC debe empezar con 10 (persona natural) o 20 (empresa)."
    return True, ""


def validate_dni_format(dni: str) -> tuple[bool, str]:
    """Validate DNI format before making API call."""
    if not dni or not dni.isdigit():
        return False, "El DNI debe contener solo números."
    if len(dni) != 8:
        return False, "El DNI debe tener 8 dígitos."
    return True, ""


def is_ruc_eligible(ruc_data: dict) -> tuple[bool, str]:
    """Check if a RUC is eligible for Circa credit."""
    if not ruc_data:
        return False, "No se encontró el RUC en SUNAT."
    
    estado = (ruc_data.get("estado") or "").upper()
    condicion = (ruc_data.get("condicion") or "").upper()
    
    if estado != "ACTIVO":
        return False, f"Tu RUC tiene estado '{estado}'. Debe estar ACTIVO para usar Circa."
    
    if condicion != "HABIDO":
        return False, f"Tu RUC tiene condición '{condicion}'. Debe ser HABIDO para usar Circa."
    
    return True, ""


# ══════════════════════════════════════════════
# PROVIDER: ApiInti (apiinti.dev)
# ══════════════════════════════════════════════

async def _ruc_apiinti(ruc: str) -> dict | None:
    url = f"https://api.apiinti.dev/api/v1/ruc/{ruc}"
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        r = await client.get(url, headers={"Authorization": f"Bearer {PERU_API_TOKEN}"})
        if r.status_code != 200:
            logger.warning(f"ApiInti RUC {ruc}: HTTP {r.status_code}")
            return None
        d = r.json()
        return {
            "ruc": d.get("ruc") or ruc,
            "razon_social": d.get("razonSocial") or d.get("nombre_o_razon_social", ""),
            "estado": d.get("estado", ""),
            "condicion": d.get("condicion", ""),
            "direccion": d.get("direccion", ""),
            "distrito": d.get("distrito", ""),
            "provincia": d.get("provincia", ""),
            "departamento": d.get("departamento", ""),
            "rep_legal": None,
        }


async def _dni_apiinti(dni: str) -> dict | None:
    url = f"https://api.apiinti.dev/api/v1/dni/{dni}"
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        r = await client.get(url, headers={"Authorization": f"Bearer {PERU_API_TOKEN}"})
        if r.status_code != 200:
            logger.warning(f"ApiInti DNI {dni}: HTTP {r.status_code}")
            return None
        d = r.json()
        nombres = d.get("nombres", "")
        ap = d.get("apellidoPaterno") or d.get("apellido_paterno", "")
        am = d.get("apellidoMaterno") or d.get("apellido_materno", "")
        return {
            "dni": dni,
            "nombres": nombres,
            "apellido_paterno": ap,
            "apellido_materno": am,
            "nombre_completo": f"{ap} {am} {nombres}".strip(),
        }


# ══════════════════════════════════════════════
# PROVIDER: PeruAPI (peruapi.com)
# ══════════════════════════════════════════════

async def _ruc_peruapi(ruc: str) -> dict | None:
    url = f"https://api.peruapi.com/ruc/{ruc}"
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        r = await client.get(url, headers={"X-Api-Key": PERU_API_TOKEN})
        if r.status_code != 200:
            return None
        d = r.json().get("data", r.json())
        return {
            "ruc": d.get("ruc", ruc),
            "razon_social": d.get("razon_social", ""),
            "estado": d.get("estado", ""),
            "condicion": d.get("condicion", ""),
            "direccion": d.get("direccion", ""),
            "distrito": d.get("distrito", ""),
            "provincia": d.get("provincia", ""),
            "departamento": d.get("departamento", ""),
            "rep_legal": None,
        }


async def _dni_peruapi(dni: str) -> dict | None:
    url = f"https://api.peruapi.com/dni/{dni}"
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        r = await client.get(url, headers={"X-Api-Key": PERU_API_TOKEN})
        if r.status_code != 200:
            return None
        d = r.json().get("data", r.json())
        nombres = d.get("nombres", "")
        ap = d.get("apellido_paterno", "")
        am = d.get("apellido_materno", "")
        return {
            "dni": dni,
            "nombres": nombres,
            "apellido_paterno": ap,
            "apellido_materno": am,
            "nombre_completo": f"{ap} {am} {nombres}".strip(),
        }


# ══════════════════════════════════════════════
# PROVIDER: ApiPeru (apiperu.dev)
# ══════════════════════════════════════════════

async def _ruc_apiperu(ruc: str) -> dict | None:
    url = f"https://apiperu.dev/api/ruc/{ruc}"
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        r = await client.get(url, headers={
            "Authorization": f"Bearer {PERU_API_TOKEN}",
            "Content-Type": "application/json",
        })
        if r.status_code != 200:
            return None
        d = r.json().get("data", {})
        return {
            "ruc": d.get("ruc", ruc),
            "razon_social": d.get("nombre_o_razon_social", ""),
            "estado": d.get("estado", ""),
            "condicion": d.get("condicion", ""),
            "direccion": d.get("direccion", ""),
            "distrito": d.get("distrito", ""),
            "provincia": d.get("provincia", ""),
            "departamento": d.get("departamento", ""),
            "rep_legal": None,
        }


async def _dni_apiperu(dni: str) -> dict | None:
    url = f"https://apiperu.dev/api/dni/{dni}"
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        r = await client.get(url, headers={
            "Authorization": f"Bearer {PERU_API_TOKEN}",
            "Content-Type": "application/json",
        })
        if r.status_code != 200:
            return None
        d = r.json().get("data", {})
        nombres = d.get("nombres", "")
        ap = d.get("apellido_paterno", "")
        am = d.get("apellido_materno", "")
        return {
            "dni": dni,
            "nombres": nombres,
            "apellido_paterno": ap,
            "apellido_materno": am,
            "nombre_completo": f"{ap} {am} {nombres}".strip(),
        }



# ══════════════════════════════════════════════
# SYNC VERSIONS (for state_machine.py)
# ══════════════════════════════════════════════

def consultar_ruc_sync(ruc: str) -> dict | None:
    """Sync version of consultar_ruc for state machine."""
    if not ruc or len(ruc) != 11 or not ruc.isdigit():
        return None
    try:
        if PERU_API_PROVIDER == "apiinti":
            return _ruc_apiinti_sync(ruc)
        elif PERU_API_PROVIDER == "apiperu":
            return _ruc_apiperu_sync(ruc)
        else:
            return None
    except Exception as e:
        logger.error(f"Sync RUC error {ruc}: {e}")
        return None


def consultar_dni_sync(dni: str) -> dict | None:
    """Sync version of consultar_dni for state machine."""
    if not dni or len(dni) != 8 or not dni.isdigit():
        return None
    try:
        if PERU_API_PROVIDER == "apiinti":
            return _dni_apiinti_sync(dni)
        elif PERU_API_PROVIDER == "apiperu":
            return _dni_apiperu_sync(dni)
        else:
            return None
    except Exception as e:
        logger.error(f"Sync DNI error {dni}: {e}")
        return None


def _ruc_apiinti_sync(ruc: str) -> dict | None:
    url = f"https://api.apiinti.dev/api/v1/ruc/{ruc}"
    r = httpx.get(url, headers={"Authorization": f"Bearer {PERU_API_TOKEN}"}, timeout=TIMEOUT)
    if r.status_code != 200:
        logger.warning(f"ApiInti RUC sync {ruc}: HTTP {r.status_code}")
        return None
    d = r.json()
    return {
        "ruc": d.get("ruc") or ruc,
        "razon_social": d.get("razonSocial") or d.get("nombre_o_razon_social", ""),
        "estado": d.get("estado", ""),
        "condicion": d.get("condicion", ""),
        "direccion": d.get("direccion", ""),
        "distrito": d.get("distrito", ""),
        "provincia": d.get("provincia", ""),
        "departamento": d.get("departamento", ""),
        "rep_legal": d.get("representante_legal") or d.get("rep_legal"),
    }


def _dni_apiinti_sync(dni: str) -> dict | None:
    url = f"https://api.apiinti.dev/api/v1/dni/{dni}"
    r = httpx.get(url, headers={"Authorization": f"Bearer {PERU_API_TOKEN}"}, timeout=TIMEOUT)
    if r.status_code != 200:
        logger.warning(f"ApiInti DNI sync {dni}: HTTP {r.status_code}")
        return None
    d = r.json()
    nombres = d.get("nombres", "")
    ap = d.get("apellidoPaterno") or d.get("apellido_paterno", "")
    am = d.get("apellidoMaterno") or d.get("apellido_materno", "")
    return {
        "dni": dni,
        "nombres": nombres,
        "apellido_paterno": ap,
        "apellido_materno": am,
        "nombre_completo": f"{ap} {am} {nombres}".strip(),
    }


def _ruc_apiperu_sync(ruc: str) -> dict | None:
    url = f"https://apiperu.dev/api/ruc/{ruc}"
    r = httpx.get(url, headers={"Authorization": f"Bearer {PERU_API_TOKEN}", "Content-Type": "application/json"}, timeout=TIMEOUT)
    if r.status_code != 200:
        return None
    d = r.json().get("data", {})
    return {
        "ruc": d.get("ruc", ruc),
        "razon_social": d.get("nombre_o_razon_social", ""),
        "estado": d.get("estado", ""),
        "condicion": d.get("condicion", ""),
        "direccion": d.get("direccion", ""),
        "distrito": d.get("distrito", ""),
        "provincia": d.get("provincia", ""),
        "departamento": d.get("departamento", ""),
        "rep_legal": None,
    }


def _dni_apiperu_sync(dni: str) -> dict | None:
    url = f"https://apiperu.dev/api/dni/{dni}"
    r = httpx.get(url, headers={"Authorization": f"Bearer {PERU_API_TOKEN}", "Content-Type": "application/json"}, timeout=TIMEOUT)
    if r.status_code != 200:
        return None
    d = r.json().get("data", {})
    nombres = d.get("nombres", "")
    ap = d.get("apellido_paterno", "")
    am = d.get("apellido_materno", "")
    return {
        "dni": dni,
        "nombres": nombres,
        "apellido_paterno": ap,
        "apellido_materno": am,
        "nombre_completo": f"{ap} {am} {nombres}".strip(),
    }
