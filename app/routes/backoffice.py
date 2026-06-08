"""Backoffice unificado Circa — soporte operativo."""
from __future__ import annotations

import json
import logging
import os
import secrets
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

import httpx
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel, Field

from app.routes import distribuidor as dist
from app.services import db
from app.services.backoffice_audit import log_action
from app.services.backoffice_auth import (
    _bearer,
    bootstrap_credentials,
    create_token,
    get_backoffice_user,
    verify_password,
    verify_reauth_password,
)
from app.services.distribuidor_routing import DIMAX_DISTRIBUIDOR_ID, ZOOM_DISTRIBUIDOR_ID
from app.services import dimax_bodega_excel as dimax_bod
from app.services import excel_import as xls

logger = logging.getLogger("circa.backoffice")
router = APIRouter(prefix="/api/backoffice", tags=["backoffice"])

_sb_get = dist._sb_get
_sb_patch = dist._sb_patch
STATUS_FLOW = dist.STATUS_FLOW
PREVENTA_CANCEL_STATES = frozenset({
    "preventa_borrador", "preventa_confirmada", "preventa_aceptada",
    "preventa_en_preparacion", "preventa_despachada",
})
VENTA_CANCEL_STATES = frozenset({
    "borrador", "confirmado", "recibido", "en_preparacion", "despachado", "en_camino",
})
DEFAULT_LINEA_APROBADA = 500.0


class LoginRequest(BaseModel):
    email: str
    password: str


class ReauthMixin(BaseModel):
    comentario: str = Field(..., min_length=8, max_length=500)
    password: str = Field(..., min_length=1)


@router.post("/auth/login")
async def login(body: LoginRequest):
    email = body.email.strip().lower()
    boot_email, _ = bootstrap_credentials()
    if email != boot_email:
        raise HTTPException(status_code=401, detail="Credenciales inválidas")
    if not verify_password(body.password):
        raise HTTPException(status_code=401, detail="Credenciales inválidas")
    token = create_token("bootstrap-support", email)
    return {
        "ok": True,
        "token": token,
        "user": {"id": "bootstrap-support", "email": email, "role": "support"},
        "expires_in": int(os.getenv("BACKOFFICE_TOKEN_TTL_SEC", str(8 * 3600))),
    }


@router.get("/auth/me")
async def me(user: dict = Depends(get_backoffice_user)):
    return {"user": {**user, "role": "support"}}


@router.get("/support-bridge")
async def support_bridge(
    user: dict = Depends(get_backoffice_user),
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
):
    """Puente legacy: el inbox embebido usa el JWT del backoffice (misma sesión)."""
    tok = creds.credentials if creds else None
    return {
        "token": tok,
        "inbox_url": "/support?embedded=1",
        "user": user["email"],
        "auth_mode": "backoffice",
    }


@router.get("/resumen")
async def resumen(test: Optional[str] = None, user: dict = Depends(get_backoffice_user)):
    return await dist.admin_resumen(test=test, admin=True)


@router.get("/analytics-resumen")
async def analytics_resumen(test: Optional[str] = None, user: dict = Depends(get_backoffice_user)):
    return await dist.admin_analytics_resumen(test=test, admin=True)


@router.get("/alerts/sobregiro")
async def alerts_sobregiro(test: Optional[str] = None, user: dict = Depends(get_backoffice_user)):
    return await dist.admin_alerts_sobregiro(test=test, admin=True)


@router.get("/bodegas")
async def list_bodegas(
    test: Optional[str] = None,
    estado: Optional[str] = None,
    search: Optional[str] = None,
    user: dict = Depends(get_backoffice_user),
):
    return await dist.admin_list_bodegas(test=test, estado=estado, search=search, admin=True)


@router.get("/bodega/{bodega_id}")
async def bodega_detalle(bodega_id: str, user: dict = Depends(get_backoffice_user)):
    return await dist.admin_bodega_detalle(bodega_id, admin=True)


@router.get("/bodega/{bodega_id}/perfil")
async def bodega_perfil(bodega_id: str, user: dict = Depends(get_backoffice_user)):
    """Perfil completo de bodega con features analíticas y score."""
    from app.services.analytics import get_bodega_features
    from app.services.bodega_score import compute_bodega_score

    detalle = await dist.admin_bodega_detalle(bodega_id, admin=True)
    features = get_bodega_features(bodega_id)
    score = compute_bodega_score(
        bodega=detalle.get("bodega") or {},
        features=features,
        stats=detalle.get("stats") or {},
        pedidos=detalle.get("pedidos") or [],
    )
    return {
        **detalle,
        "features": features,
        "score": score,
    }


@router.get("/pedidos")
async def list_pedidos(
    bodega: Optional[str] = None,
    distribuidor: Optional[str] = None,
    estado: Optional[str] = None,
    tipo: Optional[str] = None,
    test: Optional[str] = None,
    user: dict = Depends(get_backoffice_user),
):
    return await dist.admin_list_pedidos(
        bodega=bodega, distribuidor=distribuidor, estado=estado, tipo=tipo, test=test, admin=True,
    )


@router.get("/cobranzas")
async def cobranzas(
    bodega: Optional[str] = None,
    distribuidor: Optional[str] = None,
    estado: Optional[str] = None,
    fecha_desde: Optional[str] = None,
    fecha_hasta: Optional[str] = None,
    test: Optional[str] = None,
    user: dict = Depends(get_backoffice_user),
):
    return await dist.admin_cobranzas(
        bodega=bodega,
        distribuidor=distribuidor,
        estado=estado,
        fecha_desde=fecha_desde,
        fecha_hasta=fecha_hasta,
        test=test,
        admin=True,
    )


@router.get("/export-pagos-distribuidor")
async def export_pagos(
    fecha_desde: Optional[str] = None,
    fecha_hasta: Optional[str] = None,
    test: Optional[str] = None,
    user: dict = Depends(get_backoffice_user),
):
    return await dist.admin_export_pagos(
        fecha_desde=fecha_desde, fecha_hasta=fecha_hasta, test=test, admin=True,
    )


@router.get("/audit")
async def audit_log(limit: int = 50, user: dict = Depends(get_backoffice_user)):
    try:
        rows = (
            db.sb.table("backoffice_audit_log")
            .select("*")
            .order("created_at", desc=True)
            .limit(min(limit, 200))
            .execute()
            .data
            or []
        )
        return {"entries": rows, "total": len(rows)}
    except Exception:
        return {"entries": [], "total": 0, "note": "Ejecuta migrations/20260520_backoffice.sql"}


class BodegaCreate(ReauthMixin):
    ruc: str = Field(..., min_length=8, max_length=11)
    razon_social: str = Field(..., min_length=2, max_length=200)
    nombre_comercial: Optional[str] = None
    telefono_whatsapp: str
    representante_legal: Optional[str] = None
    dni_representante: Optional[str] = None
    direccion_fiscal: Optional[str] = None
    distrito: Optional[str] = None
    provincia: Optional[str] = None
    estado: str = "preaprobada"
    es_test: bool = False
    solo_dni_sin_ruc: bool = False


class BodegasImportConfirm(ReauthMixin):
    rows: list[dict[str, Any]] = Field(..., min_length=1)


class BodegasRevalidateRows(BaseModel):
    rows: list[dict[str, Any]] = Field(..., min_length=1)
    filename: Optional[str] = None


class DimaxBodegaRevalidate(BaseModel):
    fila: Optional[int] = None
    codigo_dimax: Optional[str] = None
    ruc: str = Field(..., min_length=8, max_length=11)
    solo_dni_sin_ruc: bool = False
    razon_social: str = Field(..., min_length=2, max_length=200)
    nombre_comercial: Optional[str] = None
    telefono_whatsapp: str
    representante_legal: Optional[str] = None
    dni_representante: Optional[str] = None
    direccion_fiscal: Optional[str] = None
    distrito: Optional[str] = None
    provincia: Optional[str] = None
    vendedor_codigo: Optional[str] = None
    vendedor_nombre: Optional[str] = None
    filename: Optional[str] = None


class DimaxBodegaConfirm(BaseModel):
    comentario: str = Field(..., min_length=8, max_length=500)
    ruc: str = Field(..., min_length=8, max_length=11)
    razon_social: str = Field(..., min_length=2, max_length=200)
    nombre_comercial: Optional[str] = None
    telefono_whatsapp: str
    representante_legal: Optional[str] = None
    dni_representante: Optional[str] = None
    direccion_fiscal: Optional[str] = None
    distrito: Optional[str] = None
    provincia: Optional[str] = None
    estado: str = "preaprobada"
    es_test: bool = False
    solo_dni_sin_ruc: bool = False
    codigo_dimax: Optional[str] = None
    vendedor_codigo: Optional[str] = None
    vendedor_nombre: Optional[str] = None
    fila_excel: Optional[int] = None


class BodegaUpdate(ReauthMixin):
    razon_social: Optional[str] = None
    nombre_comercial: Optional[str] = None
    telefono_whatsapp: Optional[str] = None
    representante_legal: Optional[str] = None
    dni_representante: Optional[str] = None
    linea_aprobada: Optional[float] = Field(default=None, ge=0)
    linea_disponible: Optional[float] = Field(default=None, ge=0)
    estado: Optional[str] = None
    es_test: Optional[bool] = None
    en_piloto: Optional[bool] = None


class SessionReset(ReauthMixin):
    fase: str = "menu"
    clear_datos: bool = True


def _normalizar_telefono(tel: str) -> str:
    t = "".join(c for c in str(tel) if c.isdigit() or c == "+")
    if t.startswith("+51"):
        return t
    if t.startswith("51") and len(t) == 11:
        return "+" + t
    if len(t) == 9:
        return "+51" + t
    if tel.strip().startswith("+"):
        return tel.strip()
    raise HTTPException(status_code=400, detail="Teléfono WhatsApp inválido (Perú)")


def _insert_bodega_record(
    *,
    ruc: str,
    razon_social: str,
    nombre_comercial: str,
    telefono_whatsapp: str,
    representante_legal: str | None,
    dni_representante: str | None,
    direccion_fiscal: str | None,
    distrito: str | None,
    provincia: str | None,
    estado: str,
    es_test: bool,
    solo_dni_sin_ruc: bool,
) -> tuple[str, dict[str, Any]]:
    bodega_id = str(uuid.uuid4())
    dist_id = ZOOM_DISTRIBUIDOR_ID if es_test else DIMAX_DISTRIBUIDOR_ID
    payload = {
        "id": bodega_id,
        "ruc": ruc,
        "razon_social": razon_social,
        "nombre_comercial": nombre_comercial,
        "telefono_whatsapp": telefono_whatsapp,
        "representante_legal": representante_legal,
        "dni_representante": dni_representante,
        "direccion_fiscal": direccion_fiscal,
        "distrito": distrito,
        "provincia": provincia,
        "linea_aprobada": DEFAULT_LINEA_APROBADA,
        "linea_disponible": 0,
        "estado": estado,
        "distribuidor_id": dist_id,
        "es_test": es_test,
        "solo_dni_sin_ruc": solo_dni_sin_ruc,
        "en_piloto": True,
    }
    db.sb.table("bodegas").insert(payload).execute()
    return bodega_id, payload


@router.post("/bodegas")
async def create_bodega(body: BodegaCreate, user: dict = Depends(get_backoffice_user)):
    verify_reauth_password(body.password)
    tel = _normalizar_telefono(body.telefono_whatsapp)
    ruc = body.ruc.strip()

    if db.get_bodega_by_ruc(ruc):
        raise HTTPException(status_code=409, detail="Ya existe una bodega con ese RUC")
    if db.get_bodega_by_phone(tel):
        raise HTTPException(status_code=409, detail="Ya existe una bodega con ese teléfono")

    bodega_id, payload = _insert_bodega_record(
        ruc=ruc,
        razon_social=body.razon_social.strip(),
        nombre_comercial=(body.nombre_comercial or body.razon_social).strip(),
        telefono_whatsapp=tel,
        representante_legal=body.representante_legal,
        dni_representante=body.dni_representante,
        direccion_fiscal=body.direccion_fiscal,
        distrito=body.distrito,
        provincia=body.provincia,
        estado=body.estado,
        es_test=body.es_test,
        solo_dni_sin_ruc=body.solo_dni_sin_ruc,
    )
    log_action(
        user=user,
        action="bodega_create",
        entity_type="bodega",
        entity_id=bodega_id,
        comment=body.comentario,
        after=payload,
        bodega_id=bodega_id,
    )
    return {"ok": True, "bodega_id": bodega_id, "telefono_whatsapp": tel}


@router.patch("/bodega/{bodega_id}")
async def update_bodega(bodega_id: str, body: BodegaUpdate, user: dict = Depends(get_backoffice_user)):
    verify_reauth_password(body.password)
    rows = _sb_get("bodegas", {"select": "*", "id": f"eq.{bodega_id}"})
    if not rows:
        raise HTTPException(status_code=404, detail="Bodega no encontrada")
    before = rows[0]
    updates = {k: v for k, v in body.model_dump(exclude={"comentario", "password"}).items() if v is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="Sin campos para actualizar")
    if "telefono_whatsapp" in updates:
        updates["telefono_whatsapp"] = _normalizar_telefono(updates["telefono_whatsapp"])
    db.update_bodega(bodega_id, updates)
    log_action(
        user=user,
        action="bodega_update",
        entity_type="bodega",
        entity_id=bodega_id,
        comment=body.comentario,
        before={k: before.get(k) for k in updates},
        after=updates,
        bodega_id=bodega_id,
    )
    return {"ok": True, "bodega_id": bodega_id, "updated": list(updates.keys())}


@router.post("/bodega/{bodega_id}/sesion/reset")
async def reset_sesion(bodega_id: str, body: SessionReset, user: dict = Depends(get_backoffice_user)):
    verify_reauth_password(body.password)
    rows = _sb_get("bodegas", {"select": "id,telefono_whatsapp", "id": f"eq.{bodega_id}"})
    if not rows:
        raise HTTPException(status_code=404, detail="Bodega no encontrada")
    tel = rows[0].get("telefono_whatsapp")
    if not tel:
        raise HTTPException(status_code=400, detail="Bodega sin teléfono WhatsApp")

    ses = db.get_session(tel)
    before = {"fase": ses.get("fase") if ses else None, "datos": ses.get("datos") if ses else None}
    datos: dict = {}
    if not body.clear_datos and ses:
        raw = ses.get("datos")
        if isinstance(raw, str):
            try:
                datos = json.loads(raw)
            except Exception:
                datos = {}
        elif isinstance(raw, dict):
            datos = raw
    db.upsert_session(tel, body.fase, datos, bodega_id)
    log_action(
        user=user,
        action="sesion_reset",
        entity_type="sesion",
        entity_id=tel,
        comment=body.comentario,
        before=before,
        after={"fase": body.fase, "clear_datos": body.clear_datos},
        bodega_id=bodega_id,
    )
    return {"ok": True, "telefono": tel, "fase": body.fase}


class BackofficePinSet(ReauthMixin):
    pin: str
    pin_confirm: str


@router.post("/bodega/{bodega_id}/pin/set")
async def pin_set(bodega_id: str, body: BackofficePinSet, user: dict = Depends(get_backoffice_user)):
    verify_reauth_password(body.password)
    payload = dist.AdminPinSet(
        comentario=body.comentario,
        autorizacion=dist.ADMIN_TOKEN,
        pin=body.pin,
        pin_confirm=body.pin_confirm,
    )
    result = await dist.admin_set_pin(bodega_id, payload, admin=True)
    log_action(user=user, action="pin_set", entity_type="bodega", entity_id=bodega_id, comment=body.comentario, bodega_id=bodega_id)
    return result


@router.post("/bodega/{bodega_id}/pin/reset")
async def pin_reset(bodega_id: str, body: ReauthMixin, user: dict = Depends(get_backoffice_user)):
    verify_reauth_password(body.password)
    payload = dist.AdminPinAction(comentario=body.comentario, autorizacion=dist.ADMIN_TOKEN)
    result = await dist.admin_reset_pin(bodega_id, payload, admin=True)
    log_action(user=user, action="pin_reset", entity_type="bodega", entity_id=bodega_id, comment=body.comentario, bodega_id=bodega_id)
    return result


class PedidoEstadoUpdate(ReauthMixin):
    estado: str
    force: bool = False


@router.post("/pedido/{pedido_id}/estado")
async def update_pedido_estado(
    pedido_id: str, body: PedidoEstadoUpdate, user: dict = Depends(get_backoffice_user),
):
    verify_reauth_password(body.password)
    rows = _sb_get("pedidos", {"select": "*", "id": f"eq.{pedido_id}"})
    if not rows:
        raise HTTPException(status_code=404, detail="Pedido no encontrado")
    pedido = rows[0]
    current = pedido.get("estado")
    nuevo = body.estado.strip()

    if not body.force:
        expected = STATUS_FLOW.get(current)
        if expected != nuevo and current != nuevo:
            raise HTTPException(
                status_code=400,
                detail=f"Transición no permitida: '{current}' → '{nuevo}'. Siguiente: '{expected}'. Usa force=true.",
            )

    patch: dict[str, Any] = {"estado": nuevo}
    if not nuevo.startswith("preventa_"):
        patch[f"fecha_{nuevo}"] = datetime.now(timezone.utc).isoformat()
    _sb_patch("pedidos", patch, {"id": f"eq.{pedido_id}"})

    if nuevo == "entregado":
        try:
            plazo_d = pedido.get("plazo_dias") or 7
            from datetime import timedelta as td
            fv = (datetime.now(timezone.utc) + td(days=plazo_d)).strftime("%Y-%m-%d")
            _sb_patch("pedidos", {"fecha_vencimiento": fv}, {"id": f"eq.{pedido_id}"})
        except Exception:
            pass

    log_action(
        user=user,
        action="pedido_estado",
        entity_type="pedido",
        entity_id=pedido_id,
        comment=body.comentario,
        before={"estado": current},
        after={"estado": nuevo, "force": body.force},
        bodega_id=pedido.get("bodega_id"),
        pedido_id=pedido_id,
    )
    return {"ok": True, "pedido_id": pedido_id, "estado_anterior": current, "estado": nuevo}


@router.post("/pedido/{pedido_id}/cancelar")
async def cancelar_pedido(pedido_id: str, body: ReauthMixin, user: dict = Depends(get_backoffice_user)):
    verify_reauth_password(body.password)
    rows = _sb_get("pedidos", {"select": "*", "id": f"eq.{pedido_id}"})
    if not rows:
        raise HTTPException(status_code=404, detail="Pedido no encontrado")
    pedido = rows[0]
    estado = pedido.get("estado") or ""
    if pedido.get("tipo_operacion") == "preventa":
        if estado not in PREVENTA_CANCEL_STATES:
            raise HTTPException(status_code=400, detail=f"No se puede cancelar preventa en estado '{estado}'")
        nuevo = "preventa_cancelada"
    else:
        if estado not in VENTA_CANCEL_STATES:
            raise HTTPException(status_code=400, detail=f"No se puede cancelar pedido en estado '{estado}'")
        nuevo = "rechazado"
    _sb_patch("pedidos", {"estado": nuevo}, {"id": f"eq.{pedido_id}"})
    log_action(
        user=user,
        action="pedido_cancel",
        entity_type="pedido",
        entity_id=pedido_id,
        comment=body.comentario,
        before={"estado": estado},
        after={"estado": nuevo},
        bodega_id=pedido.get("bodega_id"),
        pedido_id=pedido_id,
    )
    return {"ok": True, "estado": nuevo}


@router.post("/preventa/{pedido_id}/aceptar")
async def aceptar_preventa(pedido_id: str, user: dict = Depends(get_backoffice_user)):
    return await dist.admin_aceptar_preventa(pedido_id, admin=True)


@router.post("/cobranza/{pedido_id}/verificar-pago")
async def verificar_pago(pedido_id: str, payload: dict, user: dict = Depends(get_backoffice_user)):
    result = await dist.admin_verificar_pago(pedido_id, payload, admin=True)
    log_action(user=user, action="verificar_pago", entity_type="pedido", entity_id=pedido_id, pedido_id=pedido_id)
    return result


@router.post("/cobranza/{pedido_id}/recordatorio")
async def enviar_recordatorio(pedido_id: str, user: dict = Depends(get_backoffice_user)):
    return await dist.admin_send_cobranza(pedido_id, admin=True)


class VendedorCreate(ReauthMixin):
    codigo: str
    nombre: str
    distribuidor_id: Optional[str] = None
    es_admin: bool = False


class VendedorUpdate(ReauthMixin):
    nombre: Optional[str] = None
    activo: Optional[bool] = None
    es_admin: Optional[bool] = None


class CarteraAssign(ReauthMixin):
    bodega_id: str
    activo: bool = True


@router.get("/vendedores")
async def list_vendedores(user: dict = Depends(get_backoffice_user)):
    rows = _sb_get("vendedores", {
        "select": "id,codigo,nombre,distribuidor_id,activo,es_admin,ultimo_acceso,access_token",
        "order": "nombre.asc",
        "limit": "500",
    })
    for v in rows:
        tok = v.get("access_token") or ""
        v["url_app"] = f"/v/{tok}" if tok else None
        v.pop("access_token", None)
    return {"vendedores": rows, "total": len(rows)}


@router.post("/vendedores")
async def create_vendedor(body: VendedorCreate, user: dict = Depends(get_backoffice_user)):
    verify_reauth_password(body.password)
    dist_id = body.distribuidor_id or DIMAX_DISTRIBUIDOR_ID
    token = secrets.token_urlsafe(24)[:32]
    payload = {
        "distribuidor_id": dist_id,
        "codigo": body.codigo.strip(),
        "nombre": body.nombre.strip(),
        "activo": True,
        "es_admin": body.es_admin,
        "access_token": token,
    }
    r = httpx.post(
        f"{dist.SUPABASE_URL}/rest/v1/vendedores",
        headers=dist._sb_headers(),
        json=payload,
        timeout=15,
    )
    if r.status_code >= 400:
        raise HTTPException(status_code=400, detail=r.text[:200])
    row = r.json()[0] if isinstance(r.json(), list) else r.json()
    vid = row.get("id")
    log_action(user=user, action="vendedor_create", entity_type="vendedor", entity_id=vid, comment=body.comentario, after=payload)
    return {"ok": True, "vendedor_id": vid, "url_app": f"/v/{token}"}


@router.patch("/vendedor/{vendedor_id}")
async def update_vendedor(
    vendedor_id: str, body: VendedorUpdate, user: dict = Depends(get_backoffice_user),
):
    verify_reauth_password(body.password)
    updates = {k: v for k, v in body.model_dump(exclude={"comentario", "password"}).items() if v is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="Sin campos para actualizar")
    _sb_patch("vendedores", updates, {"id": f"eq.{vendedor_id}"})
    log_action(user=user, action="vendedor_update", entity_type="vendedor", entity_id=vendedor_id, comment=body.comentario, after=updates)
    return {"ok": True, "vendedor_id": vendedor_id}


@router.get("/vendedor/{vendedor_id}/preventas")
async def vendedor_preventas(vendedor_id: str, user: dict = Depends(get_backoffice_user)):
    pedidos = _sb_get("pedidos", {
        "select": "id,numero,estado,link_token,bodega_id,monto_productos,created_at",
        "vendedor_id": f"eq.{vendedor_id}",
        "tipo_operacion": "eq.preventa",
        "order": "created_at.desc",
        "limit": "100",
    })
    for p in pedidos:
        bid = p.get("bodega_id")
        if bid:
            b = _sb_get("bodegas", {"select": "nombre_comercial,telefono_whatsapp", "id": f"eq.{bid}"})
            p["bodega"] = b[0] if b else {}
    return {"preventas": pedidos, "total": len(pedidos)}


@router.get("/vendedor/{vendedor_id}/cartera")
async def vendedor_cartera(vendedor_id: str, user: dict = Depends(get_backoffice_user)):
    rows = _sb_get("bodega_vendedores", {
        "select": "bodega_id,activo,bodegas(id,nombre_comercial,ruc,telefono_whatsapp,estado)",
        "vendedor_id": f"eq.{vendedor_id}",
        "limit": "500",
    })
    return {"cartera": rows, "total": len(rows)}


@router.post("/vendedor/{vendedor_id}/cartera")
async def assign_cartera(
    vendedor_id: str, body: CarteraAssign, user: dict = Depends(get_backoffice_user),
):
    verify_reauth_password(body.password)
    existing = _sb_get("bodega_vendedores", {
        "select": "id",
        "vendedor_id": f"eq.{vendedor_id}",
        "bodega_id": f"eq.{body.bodega_id}",
        "limit": "1",
    })
    if existing:
        _sb_patch("bodega_vendedores", {"activo": body.activo}, {"id": f"eq.{existing[0]['id']}"})
    else:
        db.sb.table("bodega_vendedores").insert({
            "vendedor_id": vendedor_id,
            "bodega_id": body.bodega_id,
            "activo": body.activo,
        }).execute()
    log_action(
        user=user,
        action="cartera_assign",
        entity_type="vendedor",
        entity_id=vendedor_id,
        comment=body.comentario,
        after={"bodega_id": body.bodega_id, "activo": body.activo},
        bodega_id=body.bodega_id,
    )
    return {"ok": True}


@router.get("/distribuidores")
async def list_distribuidores(user: dict = Depends(get_backoffice_user)):
    rows = _sb_get("distribuidores", {"select": "id,nombre_comercial,ruc,estado", "limit": "50"})
    return {"distribuidores": rows}


# ── Importación Excel ─────────────────────────────────────────────

@router.get("/import/plantilla/bodegas")
async def plantilla_bodegas(user: dict = Depends(get_backoffice_user)):
    data = xls.build_template_xlsx(xls.BODEGAS_HEADERS, xls.BODEGAS_EJEMPLO)
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="circa_plantilla_bodegas.xlsx"'},
    )


@router.get("/import/plantilla/pedidos")
async def plantilla_pedidos(user: dict = Depends(get_backoffice_user)):
    data = xls.build_template_xlsx(xls.PEDIDOS_HEADERS, xls.PEDIDOS_EJEMPLO)
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="circa_plantilla_pedidos.xlsx"'},
    )


@router.post("/import/bodegas/preview")
async def preview_bodegas_excel(
    file: UploadFile = File(...),
    user: dict = Depends(get_backoffice_user),
):
    content = await _read_xlsx_upload(file)
    rows = xls.parse_xlsx(content)
    if not rows:
        raise HTTPException(status_code=400, detail="Sin filas de datos")
    preview = xls.preview_bodegas_rows(rows)
    preview["filename"] = file.filename
    return {"ok": True, "preview": preview}


@router.post("/import/bodegas/revalidate")
async def revalidate_bodegas_rows(
    body: BodegasRevalidateRows,
    user: dict = Depends(get_backoffice_user),
):
    import_rows: list[dict[str, Any]] = []
    for r in body.rows:
        import_rows.append({
            "_fila": r.get("fila", r.get("_fila")),
            "ruc": r.get("ruc"),
            "razon_social": r.get("razon_social"),
            "nombre_comercial": r.get("nombre_comercial"),
            "telefono_whatsapp": r.get("telefono_whatsapp"),
            "representante_legal": r.get("representante_legal"),
            "dni_representante": r.get("dni_representante"),
            "linea_aprobada": r.get("linea_aprobada"),
            "estado": r.get("estado"),
            "es_test": r.get("es_test"),
            "solo_dni_sin_ruc": r.get("solo_dni_sin_ruc"),
            "direccion_fiscal": r.get("direccion_fiscal"),
            "distrito": r.get("distrito"),
            "provincia": r.get("provincia"),
        })
    preview = xls.preview_bodegas_rows(import_rows)
    if body.filename:
        preview["filename"] = body.filename
    return {"ok": True, "preview": preview}


@router.post("/import/bodegas/confirm")
async def confirm_bodegas_import(
    body: BodegasImportConfirm,
    user: dict = Depends(get_backoffice_user),
):
    verify_reauth_password(body.password)
    import_rows: list[dict[str, Any]] = []
    for r in body.rows:
        if not (r.get("can_import") and r.get("status") == "ok"):
            continue
        import_rows.append({
            "_fila": r.get("fila"),
            "ruc": r.get("ruc"),
            "razon_social": r.get("razon_social"),
            "nombre_comercial": r.get("nombre_comercial"),
            "telefono_whatsapp": r.get("telefono_whatsapp"),
            "representante_legal": r.get("representante_legal"),
            "dni_representante": r.get("dni_representante"),
            "linea_aprobada": r.get("linea_aprobada"),
            "estado": r.get("estado"),
            "es_test": r.get("es_test"),
            "solo_dni_sin_ruc": r.get("solo_dni_sin_ruc"),
            "direccion_fiscal": r.get("direccion_fiscal"),
            "distrito": r.get("distrito"),
            "provincia": r.get("provincia"),
        })
    if not import_rows:
        raise HTTPException(status_code=400, detail="No hay filas válidas para importar")

    result = xls.import_bodegas_rows(
        import_rows,
        user=user,
        comentario=body.comentario.strip(),
    )
    log_action(
        user=user,
        action="import_bodegas_excel",
        entity_type="import",
        entity_id="confirm",
        comment=body.comentario.strip(),
        after={"creadas": result["creadas"], "errores": len(result["errores"])},
    )
    return result


@router.post("/import/bodegas")
async def import_bodegas_excel(
    file: UploadFile = File(...),
    password: str = Form(...),
    comentario: str = Form(...),
    respetar_modo: bool = Form(True),
    user: dict = Depends(get_backoffice_user),
):
    verify_reauth_password(password)
    if len(comentario.strip()) < 8:
        raise HTTPException(status_code=400, detail="Comentario mínimo 8 caracteres")
    if not file.filename or not file.filename.lower().endswith((".xlsx", ".xls")):
        raise HTTPException(status_code=400, detail="Sube un archivo .xlsx")

    content = await file.read()
    if len(content) > 5 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Archivo demasiado grande (máx 5 MB)")

    rows = xls.parse_xlsx(content)
    if not rows:
        raise HTTPException(status_code=400, detail="Sin filas de datos")

    mode_test = None
    if respetar_modo:
        # El front puede enviar respetar_modo=false para forzar según columnas es_test
        pass

    result = xls.import_bodegas_rows(rows, user=user, comentario=comentario.strip(), mode_test=mode_test)
    log_action(
        user=user,
        action="import_bodegas_excel",
        entity_type="import",
        entity_id=file.filename,
        comment=comentario.strip(),
        after={"creadas": result["creadas"], "errores": len(result["errores"])},
    )
    return result


async def _read_xlsx_upload(file: UploadFile, max_mb: int = 5) -> bytes:
    if not file.filename or not file.filename.lower().endswith((".xlsx", ".xls")):
        raise HTTPException(status_code=400, detail="Sube un archivo .xlsx")
    content = await file.read()
    if len(content) > max_mb * 1024 * 1024:
        raise HTTPException(status_code=400, detail=f"Archivo demasiado grande (máx {max_mb} MB)")
    return content


@router.post("/import/dimax-bodega/preview")
async def preview_dimax_bodega_excel(
    file: UploadFile = File(...),
    user: dict = Depends(get_backoffice_user),
):
    content = await _read_xlsx_upload(file)
    parsed = dimax_bod.parse_dimax_bodega_excel(content)
    preview = dimax_bod.enrich_preview(parsed)
    preview["filename"] = file.filename
    return {"ok": True, "preview": preview}


@router.post("/import/dimax-bodega/revalidate")
async def revalidate_dimax_bodega_preview(
    body: DimaxBodegaRevalidate,
    user: dict = Depends(get_backoffice_user),
):
    tel = _normalizar_telefono(body.telefono_whatsapp)
    payload = {
        "formato": "dimax_clientes",
        "fila": body.fila,
        "codigo_dimax": body.codigo_dimax,
        "ruc": body.ruc.strip(),
        "solo_dni_sin_ruc": body.solo_dni_sin_ruc,
        "razon_social": body.razon_social.strip(),
        "nombre_comercial": (body.nombre_comercial or body.razon_social).strip(),
        "representante_legal": body.representante_legal,
        "dni_representante": body.dni_representante,
        "telefono_whatsapp": tel,
        "direccion_fiscal": body.direccion_fiscal,
        "distrito": body.distrito,
        "provincia": body.provincia or "Lima",
        "vendedor_codigo": body.vendedor_codigo,
        "vendedor_nombre": body.vendedor_nombre,
        "estado": "preaprobada",
        "linea_aprobada": 500.0,
        "linea_disponible": 0.0,
        "es_test": False,
    }
    preview = dimax_bod.enrich_preview(payload)
    if body.filename:
        preview["filename"] = body.filename
    return {"ok": True, "preview": preview}


@router.post("/import/dimax-bodega/confirm")
async def confirm_dimax_bodega_excel(
    body: DimaxBodegaConfirm,
    user: dict = Depends(get_backoffice_user),
):
    tel = _normalizar_telefono(body.telefono_whatsapp)
    ruc = body.ruc.strip()

    if db.get_bodega_by_ruc(ruc):
        raise HTTPException(status_code=409, detail="Ya existe una bodega con ese documento")
    if db.get_bodega_by_phone(tel):
        raise HTTPException(status_code=409, detail="Ya existe una bodega con ese teléfono")

    bodega_id, payload = _insert_bodega_record(
        ruc=ruc,
        razon_social=body.razon_social.strip(),
        nombre_comercial=(body.nombre_comercial or body.razon_social).strip(),
        telefono_whatsapp=tel,
        representante_legal=body.representante_legal,
        dni_representante=body.dni_representante,
        direccion_fiscal=body.direccion_fiscal,
        distrito=body.distrito,
        provincia=body.provincia,
        estado=body.estado,
        es_test=body.es_test,
        solo_dni_sin_ruc=body.solo_dni_sin_ruc,
    )
    audit_extra = {
        "origen": "dimax_excel",
        "codigo_dimax": body.codigo_dimax,
        "vendedor_codigo": body.vendedor_codigo,
        "vendedor_nombre": body.vendedor_nombre,
        "fila_excel": body.fila_excel,
    }
    log_action(
        user=user,
        action="bodega_import_dimax",
        entity_type="bodega",
        entity_id=bodega_id,
        comment=body.comentario.strip(),
        after={**payload, **audit_extra},
        bodega_id=bodega_id,
    )
    return {
        "ok": True,
        "bodega_id": bodega_id,
        "telefono_whatsapp": tel,
        "linea_aprobada": DEFAULT_LINEA_APROBADA,
    }


@router.post("/import/pedidos")
async def import_pedidos_excel(
    file: UploadFile = File(...),
    password: str = Form(...),
    comentario: str = Form(...),
    crear_bodega_si_falta: bool = Form(False),
    user: dict = Depends(get_backoffice_user),
):
    verify_reauth_password(password)
    if len(comentario.strip()) < 8:
        raise HTTPException(status_code=400, detail="Comentario mínimo 8 caracteres")
    if not file.filename or not file.filename.lower().endswith((".xlsx", ".xls")):
        raise HTTPException(status_code=400, detail="Sube un archivo .xlsx")

    content = await file.read()
    if len(content) > 5 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Archivo demasiado grande (máx 5 MB)")

    rows = xls.parse_xlsx(content)
    if not rows:
        raise HTTPException(status_code=400, detail="Sin filas de datos")

    result = xls.import_pedidos_rows(
        rows,
        user=user,
        comentario=comentario.strip(),
        crear_bodega_si_falta=crear_bodega_si_falta,
    )
    log_action(
        user=user,
        action="import_pedidos_excel",
        entity_type="import",
        entity_id=file.filename,
        comment=comentario.strip(),
        after={"creados": result["creados"], "errores": len(result["errores"])},
    )
    return result
