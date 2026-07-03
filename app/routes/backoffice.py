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
from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import Response
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel, Field

from app.routes import distribuidor as dist
from app.services import db
from app.services.backoffice_audit import log_action
from app.config import backoffice_viewer_accounts
from app.services.backoffice_auth import (
    _bearer,
    authenticate,
    create_token,
    get_backoffice_user,
    get_backoffice_writer,
    verify_reauth_password,
)
from app.services.distribuidor_routing import DIMAX_DISTRIBUIDOR_ID, ZOOM_DISTRIBUIDOR_ID
from app.services.bodega_onboarding_snapshot import onboarding_alta_fields
from app.services import dimax_bodega_excel as dimax_bod
from app.services import excel_import as xls
from app.services.preventa_excel import match_bodega_por_nombre, parse_preventa_excel
from app.services.pedido_flow import build_pedido_flow_progress, flujo_resumen

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


def _enrich_pedidos_flujo(pedidos: list[dict]) -> None:
    for p in pedidos:
        p["flujo"] = flujo_resumen(build_pedido_flow_progress(p))


class LoginRequest(BaseModel):
    email: str
    password: str


class ReauthMixin(BaseModel):
    comentario: str = Field(..., min_length=8, max_length=500)
    password: str = Field(..., min_length=1)


@router.post("/auth/login")
async def login(body: LoginRequest):
    user = authenticate(body.email, body.password)
    if not user:
        raise HTTPException(status_code=401, detail="Credenciales inválidas")
    token = create_token(user["id"], user["email"], user["role"])
    return {
        "ok": True,
        "token": token,
        "user": user,
        "expires_in": int(os.getenv("BACKOFFICE_TOKEN_TTL_SEC", str(8 * 3600))),
    }


@router.get("/auth/me")
async def me(user: dict = Depends(get_backoffice_user)):
    return {"user": user}


@router.get("/auth/setup-status")
async def auth_setup_status():
    """Diagnóstico: ¿el servidor tiene cuentas viewer en variables de entorno?"""
    accounts = backoffice_viewer_accounts()
    return {
        "viewer_configured": bool(accounts),
        "viewer_count": len(accounts),
        "viewer_emails": [email for email, _ in accounts],
        "hint": (
            "OK: cuentas viewer cargadas desde Railway/env."
            if accounts
            else "Falta configurar en Railway (no en la pantalla de login): "
            "BACKOFFICE_VIEWER_CREDENTIALS=lectura@circa.pe:tu-clave "
            "o BACKOFFICE_VIEWER_EMAIL + BACKOFFICE_VIEWER_PASSWORD. Luego redeploy."
        ),
    }


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
    _enrich_pedidos_flujo(detalle.get("pedidos") or [])
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
    data = await dist.admin_list_pedidos(
        bodega=bodega, distribuidor=distribuidor, estado=estado, tipo=tipo, test=test, admin=True,
    )
    _enrich_pedidos_flujo(data.get("pedidos") or [])
    return data


@router.get("/pedido/{pedido_id}/flujo")
async def pedido_flujo(pedido_id: str, user: dict = Depends(get_backoffice_user)):
    """Pipeline BPMN del pedido (paso actual, restantes, fases)."""
    rows = _sb_get("pedidos", {"select": "*", "id": f"eq.{pedido_id}"})
    if not rows:
        raise HTTPException(status_code=404, detail="Pedido no encontrado")
    return build_pedido_flow_progress(rows[0])


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


class PreventaRevalidate(BaseModel):
    bodega_nombre: str = Field(..., min_length=2, max_length=200)
    fecha: Optional[str] = None
    items: list[dict[str, Any]] = Field(..., min_length=1)
    descuento_prorrateado: float = 0
    es_test: bool = False
    bodega_id: Optional[str] = None
    filename: Optional[str] = None


class PreventaImportConfirm(BaseModel):
    comentario: str = Field(..., min_length=8, max_length=500)
    bodega_id: str
    items: list[dict[str, Any]] = Field(..., min_length=1)
    descuento_prorrateado: float = 0
    fecha: Optional[str] = None
    vendedor_id: Optional[str] = None
    filename: Optional[str] = None
    bodega_nombre: Optional[str] = None


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
    provincia: str | None,  # solo preview/UI; no existe columna en bodegas
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
        "linea_aprobada": DEFAULT_LINEA_APROBADA,
        "linea_disponible": 0,
        "estado": estado,
        "distribuidor_id": dist_id,
        "es_test": es_test,
        "solo_dni_sin_ruc": solo_dni_sin_ruc,
        "en_piloto": True,
        **onboarding_alta_fields(DEFAULT_LINEA_APROBADA),
    }
    db.sb.table("bodegas").insert(payload).execute()
    return bodega_id, payload


@router.post("/bodegas")
async def create_bodega(body: BodegaCreate, user: dict = Depends(get_backoffice_writer)):
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
async def update_bodega(bodega_id: str, body: BodegaUpdate, user: dict = Depends(get_backoffice_writer)):
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
async def reset_sesion(bodega_id: str, body: SessionReset, user: dict = Depends(get_backoffice_writer)):
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
async def pin_set(bodega_id: str, body: BackofficePinSet, user: dict = Depends(get_backoffice_writer)):
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
async def pin_reset(bodega_id: str, body: ReauthMixin, user: dict = Depends(get_backoffice_writer)):
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
    pedido_id: str, body: PedidoEstadoUpdate, user: dict = Depends(get_backoffice_writer),
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
async def cancelar_pedido(pedido_id: str, body: ReauthMixin, user: dict = Depends(get_backoffice_writer)):
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
async def aceptar_preventa(pedido_id: str, user: dict = Depends(get_backoffice_writer)):
    return await dist.admin_aceptar_preventa(pedido_id, admin=True)


@router.post("/cobranza/{pedido_id}/verificar-pago")
async def verificar_pago(pedido_id: str, payload: dict, user: dict = Depends(get_backoffice_writer)):
    result = await dist.admin_verificar_pago(pedido_id, payload, admin=True)
    log_action(user=user, action="verificar_pago", entity_type="pedido", entity_id=pedido_id, pedido_id=pedido_id)
    return result


@router.post("/cobranza/{pedido_id}/recordatorio")
async def enviar_recordatorio(pedido_id: str, user: dict = Depends(get_backoffice_writer)):
    return await dist.admin_send_cobranza(pedido_id, admin=True)


class VendedorCreate(ReauthMixin):
    codigo: str
    nombre: str
    telefono_whatsapp: Optional[str] = None
    distribuidor_id: Optional[str] = None
    es_admin: bool = False


class VendedorUpdate(ReauthMixin):
    nombre: Optional[str] = None
    telefono_whatsapp: Optional[str] = None
    activo: Optional[bool] = None
    es_admin: Optional[bool] = None


class CarteraAssign(ReauthMixin):
    bodega_id: str
    activo: bool = True


@router.get("/vendedores")
async def list_vendedores(user: dict = Depends(get_backoffice_user)):
    rows = _sb_get("vendedores", {
        "select": "id,codigo,nombre,telefono_whatsapp,distribuidor_id,activo,es_admin,ultimo_acceso,access_token",
        "order": "nombre.asc",
        "limit": "500",
    })
    for v in rows:
        tok = v.get("access_token") or ""
        v["url_app"] = f"/v/{tok}" if tok else None
        v.pop("access_token", None)
    return {"vendedores": rows, "total": len(rows)}


@router.post("/vendedores")
async def create_vendedor(body: VendedorCreate, user: dict = Depends(get_backoffice_writer)):
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
    if body.telefono_whatsapp:
        payload["telefono_whatsapp"] = _normalizar_telefono(body.telefono_whatsapp)
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
    vendedor_id: str, body: VendedorUpdate, user: dict = Depends(get_backoffice_writer),
):
    verify_reauth_password(body.password)
    updates = {k: v for k, v in body.model_dump(exclude={"comentario", "password"}).items() if v is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="Sin campos para actualizar")
    if "telefono_whatsapp" in updates:
        updates["telefono_whatsapp"] = _normalizar_telefono(updates["telefono_whatsapp"])
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
    vendedor_id: str, body: CarteraAssign, user: dict = Depends(get_backoffice_writer),
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
    user: dict = Depends(get_backoffice_writer),
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
    user: dict = Depends(get_backoffice_writer),
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
    user: dict = Depends(get_backoffice_writer),
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
    user: dict = Depends(get_backoffice_writer),
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


def _preventa_preview_payload(parsed: dict[str, Any], *, es_test: bool, filename: str | None = None) -> dict[str, Any]:
    dist_id = ZOOM_DISTRIBUIDOR_ID if es_test else DIMAX_DISTRIBUIDOR_ID
    sugerida, candidatos = match_bodega_por_nombre(parsed.get("bodega_nombre") or "", dist_id)
    total = round(sum(float(i.get("subtotal") or 0) for i in parsed.get("items") or []), 2)
    can_create = total > 0 and bool(candidatos or sugerida)
    issues: list[str] = []
    if total <= 0:
        issues.append("El total cobrado es 0")
    if not candidatos:
        issues.append("No se encontró bodega coincidente en el distribuidor")
    return {
        **parsed,
        "total_pedido": total,
        "bodega_sugerida": sugerida,
        "candidatos": candidatos,
        "can_create": can_create,
        "issues": issues,
        "es_test": es_test,
        "filename": filename,
    }


@router.post("/import/preventa/preview")
async def preview_preventa_excel(
    file: UploadFile = File(...),
    es_test: bool = Form(False),
    user: dict = Depends(get_backoffice_user),
):
    content = await _read_xlsx_upload(file, max_mb=10)
    try:
        parsed = parse_preventa_excel(content, filename=file.filename)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    preview = _preventa_preview_payload(parsed, es_test=es_test, filename=file.filename)
    return {"ok": True, "preview": preview}


@router.post("/import/preventa/revalidate")
async def revalidate_preventa_import(
    body: PreventaRevalidate,
    user: dict = Depends(get_backoffice_user),
):
    total = round(sum(float(i.get("subtotal") or 0) for i in body.items), 2)
    parsed = {
        "bodega_nombre": body.bodega_nombre.strip(),
        "fecha": body.fecha,
        "items": body.items,
        "total_pedido": total,
        "descuento_prorrateado": body.descuento_prorrateado,
        "monto_productos": round(total + body.descuento_prorrateado, 2),
        "n_items": len([i for i in body.items if not i.get("es_regalo")]),
        "n_regalos": len([i for i in body.items if i.get("es_regalo")]),
        "warnings": [],
    }
    preview = _preventa_preview_payload(parsed, es_test=body.es_test, filename=body.filename)
    if body.bodega_id:
        preview["bodega_seleccionada"] = body.bodega_id
        if not any(c["id"] == body.bodega_id for c in preview.get("candidatos") or []):
            preview["can_create"] = False
            preview["issues"] = list(preview.get("issues") or []) + ["Bodega seleccionada no válida"]
    return {"ok": True, "preview": preview}


@router.post("/import/preventa/confirm")
async def confirm_preventa_import(
    body: PreventaImportConfirm,
    user: dict = Depends(get_backoffice_writer),
):
    if not body.bodega_id:
        raise HTTPException(status_code=400, detail="Selecciona una bodega")

    bodega_rows = db.sb.table("bodegas").select("id, distribuidor_id, estado, es_test").eq(
        "id", body.bodega_id
    ).limit(1).execute().data
    if not bodega_rows:
        raise HTTPException(status_code=404, detail="Bodega no encontrada")
    bodega = bodega_rows[0]
    if bodega.get("estado") not in ("activo", "preaprobada"):
        raise HTTPException(status_code=400, detail=f"Bodega en estado '{bodega.get('estado')}'")

    items_dimax = []
    for it in body.items:
        items_dimax.append({
            "sku_distribuidor": str(it.get("sku_distribuidor") or "").lstrip("0") or "0",
            "descripcion": it.get("descripcion"),
            "cantidad": int(it.get("cantidad") or 0),
            "unidad": it.get("unidad") or "UND x 1",
            "precio_unitario": float(it.get("precio_unitario") or 0),
            "subtotal": float(it.get("subtotal") or 0),
        })

    total_pedido = round(sum(float(i.get("subtotal") or 0) for i in items_dimax), 2)
    if total_pedido <= 0:
        raise HTTPException(status_code=400, detail="El total cobrado es 0")

    resultado = db.crear_pedido_preventa(
        bodega_id=body.bodega_id,
        distribuidor_id=bodega["distribuidor_id"],
        items_dimax=items_dimax,
        total_pedido=total_pedido,
        descuento_prorrateado=body.descuento_prorrateado,
        vendedor_id=body.vendedor_id,
        fecha_visita=body.fecha,
    )
    pedido_id = resultado.get("pedido_id")
    if pedido_id:
        db.sb.table("pedidos").update({
            "origen": "backoffice_preventa_excel",
        }).eq("id", pedido_id).execute()

    log_action(
        user=user,
        action="import_preventa_excel",
        entity_type="pedido",
        entity_id=pedido_id,
        comment=body.comentario.strip(),
        after={
            "bodega_id": body.bodega_id,
            "total_pedido": total_pedido,
            "items_creados": resultado.get("items_creados"),
            "filename": body.filename,
        },
        bodega_id=body.bodega_id,
        pedido_id=pedido_id,
    )
    return {
        "ok": True,
        "pedido_id": pedido_id,
        "total_pedido": total_pedido,
        "items_creados": resultado.get("items_creados"),
        "items_no_match": resultado.get("items_no_match") or [],
        "link_token": resultado.get("link_token"),
    }

@router.get("/scoring")
async def scoring_preview(
    test: Optional[str] = None,
    user: dict = Depends(get_backoffice_user),
):
    """Vista previa del modelo de score (sin persistir en bodegas.scoring)."""
    from app.services.bodega_scoring_batch import run_bodega_scoring_batch

    return run_bodega_scoring_batch(test=test, persist=False)


@router.post("/scoring/ejecutar")
async def scoring_ejecutar(
    test: Optional[str] = None,
    user: dict = Depends(get_backoffice_writer),
):
    """Ejecuta el modelo y guarda score en bodegas.scoring."""
    from app.services.bodega_scoring_batch import run_bodega_scoring_batch

    result = run_bodega_scoring_batch(test=test, persist=True)
    log_action(
        user=user,
        action="scoring_ejecutar",
        entity_type="scoring",
        entity_id="batch",
        comment=f"test={test or 'all'} total={result.get('total', 0)}",
        after={"actualizadas": result.get("actualizadas"), "resumen": result.get("resumen_grados")},
    )
    return result


class CreditModelLoadItem(BaseModel):
    telefono: str = Field(..., min_length=8)
    razon_social: str = ""
    sql_inserts: str = Field(..., min_length=1)
    sql_verificacion: str = Field(..., min_length=1)
    necesita_revision: bool = False
    confirmar_revision: bool = False
    linea_aprobada: Optional[int] = Field(default=None, ge=1, le=50000)
    linea_7d: Optional[float] = None
    cliente: dict[str, Any] = Field(default_factory=dict)
    vendedores: list[dict[str, Any]] = Field(default_factory=list)


class CreditModelPatchLineaBody(BaseModel):
    sql_inserts: str = Field(..., min_length=1)
    sql_verificacion: str = Field(..., min_length=1)
    razon_social: str = ""
    linea_aprobada: int = Field(..., ge=1, le=50000)
    linea_7d: Optional[float] = None


class CreditModelLoadRequest(ReauthMixin):
    bodegas: list[CreditModelLoadItem] = Field(..., min_length=1)


@router.post("/credit-model/process")
async def credit_model_process(
    files: list[UploadFile] = File(...),
    user: dict = Depends(get_backoffice_user),
):
    """Analiza Excel DIMAX (cliente + historial) y devuelve tiers, SQL y mensajes."""
    if not files:
        raise HTTPException(status_code=400, detail="Sube al menos un archivo .xlsx")
    from app.services.credit_model.credit_model_service import process_files

    items: list[tuple[bytes, str]] = []
    for f in files:
        content = await _read_xlsx_upload(f, max_mb=10)
        items.append((content, f.filename or "upload.xlsx"))
    return process_files(items)


@router.post("/credit-model/patch-linea")
async def credit_model_patch_linea(
    body: CreditModelPatchLineaBody,
    user: dict = Depends(get_backoffice_user),
):
    """Actualiza el SQL de alta con una línea de crédito distinta a la sugerida."""
    from app.services.credit_model.credit_model_service import apply_linea_to_load_item

    try:
        patched = apply_linea_to_load_item(body.model_dump())
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {
        "linea_aprobada": patched["tier"],
        "sql_inserts": patched["sql_inserts"],
        "sql_block": patched.get("sql_block") or "",
    }


@router.post("/credit-model/load")
async def credit_model_load(
    body: CreditModelLoadRequest,
    user: dict = Depends(get_backoffice_writer),
):
    """Ejecuta alta de bodega(s) vía Supabase API o Postgres (CIRCA_DB_URL opcional)."""
    verify_reauth_password(body.password)
    from app.services.credit_model.credit_model_service import load_bodegas_from_api

    try:
        result = load_bodegas_from_api([b.model_dump() for b in body.bodegas])
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e

    log_action(
        user=user,
        action="credit_model_load",
        entity_type="credit_model",
        entity_id="batch",
        comment=body.comentario.strip(),
        after={"ok": result.get("ok"), "fallo": result.get("fallo")},
    )
    return result


class BatchRunRequest(BaseModel):
    dry_run: bool = False
    test: Optional[str] = None
    comentario: str = Field(default="dry-run", min_length=1, max_length=500)
    password: str = Field(default="")
    selected_ids: Optional[list[str]] = Field(default=None, max_length=500)


class BatchScheduleBody(BaseModel):
    job_id: str
    label: Optional[str] = None
    activo: bool = True
    frecuencia: str = Field(default="daily")
    hour: int = Field(default=6, ge=0, le=23)
    minute: int = Field(default=0, ge=0, le=59)
    interval_hours: Optional[int] = Field(default=None, ge=1, le=24)
    weekdays: list[int] = Field(default_factory=list)
    test_filter: str = Field(default="real")


@router.get("/batch/schedules")
async def batch_schedules_list(user: dict = Depends(get_backoffice_user)):
    from app.services.batch_jobs.schedules import FREQ_LABELS, list_schedules

    return {"schedules": list_schedules(), "frecuencias": FREQ_LABELS}


@router.post("/batch/schedules")
async def batch_schedule_create(
    body: BatchScheduleBody,
    user: dict = Depends(get_backoffice_writer),
):
    from app.services.batch_jobs.schedules import create_schedule

    try:
        row = create_schedule(body.model_dump(), user_email=user.get("email", ""))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    log_action(
        user=user,
        action="batch_schedule_create",
        entity_type="batch_schedule",
        entity_id=row.get("id"),
        comment=body.label or body.job_id,
        after=row,
    )
    return row


@router.patch("/batch/schedules/{schedule_id}")
async def batch_schedule_update(
    schedule_id: str,
    body: BatchScheduleBody,
    user: dict = Depends(get_backoffice_writer),
):
    from app.services.batch_jobs.schedules import update_schedule

    try:
        row = update_schedule(schedule_id, body.model_dump())
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    return row


@router.delete("/batch/schedules/{schedule_id}")
async def batch_schedule_delete(
    schedule_id: str,
    user: dict = Depends(get_backoffice_writer),
):
    from app.services.batch_jobs.schedules import delete_schedule

    try:
        delete_schedule(schedule_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    return {"ok": True}


@router.post("/batch/schedules/run-due")
async def batch_schedules_run_due(user: dict = Depends(get_backoffice_writer)):
    """Ejecuta programaciones vencidas (prueba manual o respaldo del cron)."""
    from app.services.batch_jobs.schedules import run_due_schedules

    return await run_due_schedules()


@router.post("/batch/schedules/tick")
async def batch_schedules_tick(
    x_cron_secret: Optional[str] = Header(None, alias="X-Cron-Secret"),
):
    """Endpoint para cron externo (cada 5–15 min). Requiere BATCH_CRON_SECRET."""
    secret = os.getenv("BATCH_CRON_SECRET", "").strip()
    if not secret or not x_cron_secret or not secrets.compare_digest(x_cron_secret, secret):
        raise HTTPException(status_code=401, detail="X-Cron-Secret inválido")
    from app.services.batch_jobs.schedules import run_due_schedules

    return await run_due_schedules()


@router.get("/batch/jobs")
async def batch_jobs_list(user: dict = Depends(get_backoffice_user)):
    from app.services.batch_jobs.runner import list_jobs_with_status

    return {"jobs": list_jobs_with_status()}


@router.get("/batch/runs")
async def batch_runs_list(
    job_id: Optional[str] = None,
    limit: int = 40,
    user: dict = Depends(get_backoffice_user),
):
    from app.services.batch_jobs.runner import fetch_runs

    return {"runs": fetch_runs(job_id=job_id, limit=min(limit, 100))}


@router.get("/batch/{job_id}/preview")
async def batch_job_preview(
    job_id: str,
    test: Optional[str] = None,
    user: dict = Depends(get_backoffice_user),
):
    from app.services.batch_jobs.runner import preview_batch_job

    mode = test or "real"
    try:
        return await preview_batch_job(job_id, test=mode)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/batch/{job_id}/run")
async def batch_job_run(
    job_id: str,
    body: BatchRunRequest,
    user: dict = Depends(get_backoffice_user),
):
    from app.services.batch_jobs.runner import run_batch_job

    if not body.dry_run:
        if user.get("role") == "viewer":
            raise HTTPException(status_code=403, detail="Solo lectura: usa dry-run o pide acceso de escritura")
        if len(body.comentario.strip()) < 8:
            raise HTTPException(status_code=400, detail="Comentario mínimo 8 caracteres")
        verify_reauth_password(body.password)
        if body.selected_ids is not None and len(body.selected_ids) == 0:
            raise HTTPException(status_code=400, detail="Selecciona al menos un destinatario")

    try:
        result = await run_batch_job(
            job_id,
            test=body.test,
            dry_run=body.dry_run,
            user_email=user.get("email", ""),
            comment=body.comentario.strip() if not body.dry_run else "dry-run",
            selected_ids=body.selected_ids,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e

    if not body.dry_run and user.get("role") != "viewer":
        log_action(
            user=user,
            action="batch_run",
            entity_type="batch",
            entity_id=job_id,
            comment=body.comentario.strip(),
            after=result,
        )
    return result


class ObservabilityAnalyzeBody(BaseModel):
    bodega_id: str = Field(..., min_length=8)
    question: Optional[str] = Field(default=None, max_length=2000)


@router.get("/observability/search")
async def observability_search(
    q: str,
    limit: int = 20,
    user: dict = Depends(get_backoffice_user),
):
    from app.services.client_observability import search_bodegas

    return {"query": q, "results": search_bodegas(q, limit=min(limit, 50))}


@router.get("/observability/timeline")
async def observability_timeline(
    bodega_id: str,
    user: dict = Depends(get_backoffice_user),
):
    from app.services.client_observability import build_timeline

    data = build_timeline(bodega_id.strip())
    if not data.get("bodega"):
        raise HTTPException(status_code=404, detail="Bodega no encontrada")
    return data


@router.post("/observability/analyze")
async def observability_analyze(
    body: ObservabilityAnalyzeBody,
    user: dict = Depends(get_backoffice_user),
):
    from app.services.client_observability import analyze_with_claude, build_timeline

    timeline = build_timeline(body.bodega_id.strip())
    if not timeline.get("bodega"):
        raise HTTPException(status_code=404, detail="Bodega no encontrada")
    try:
        result = analyze_with_claude(timeline, question=body.question)
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e

    log_action(
        user=user,
        action="observability_analyze",
        entity_type="bodega",
        entity_id=body.bodega_id,
        bodega_id=body.bodega_id,
        comment=(body.question or "Análisis automático")[:500],
        after={"model": result.get("model")},
    )
    return {"timeline_summary": timeline.get("summary"), **result}


from app.routes.backoffice_ops import bodegas_ops_handler
router.get("/bodegas-ops")(bodegas_ops_handler)
from app.routes.backoffice_ops import marcar_pago_distribuidor_handler
router.post("/pedido/{pedido_id}/pago-distribuidor")(marcar_pago_distribuidor_handler)
from app.routes.backoffice_ops import gmv_handler
router.get("/gmv")(gmv_handler)
from app.routes.backoffice_import_dimax import import_dimax_preview_handler, import_dimax_confirm_handler, DiMaxConfirmBody
router.post("/import/dimax-analisis/preview")(import_dimax_preview_handler)
router.post("/import/dimax-analisis/confirm")(import_dimax_confirm_handler)
