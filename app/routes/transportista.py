"""
Portal Transportista — Circa
Hoja web de reparto. El transportista ve los pedidos por entregar, sube el
voucher FIRMADO POR EL CLIENTE y revisa lo que subio (historia corta).

Reglas de diseno (decididas con Paola, 12-oct-2026):
  - NO mueve `pedidos.estado`. Solo deja el reporte en `entregas_transportista`.
    El paso a `entregado` (y con el fecha_vencimiento + recordatorio de pago)
    lo sigue dando Circa / el portal del distribuidor.
  - Copia el voucher a `pedidos.prueba_entrega_url` para que el portal del
    distribuidor y el cierre diario lo vean sin ningun cambio adicional.
  - Solo bodegas reales (es_test = false). No hay modo prueba en esta hoja.
"""
from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from fastapi.responses import FileResponse
from typing import Optional
import re
import httpx
from datetime import datetime, timezone, timedelta

from app.routes.distribuidor import (
    _sb_get, _sb_patch, _sb_map_by_ids, _SB_CLIENT, _sb_headers,
    SUPABASE_URL, SUPABASE_KEY,
)

# ── Ventanas de la hoja, en dias. Se cambian aqui y nada mas. ──────────────
# Pendientes: los estados en base van atrasados (los mueve el cierre), asi que
# un pedido sin entregar debe seguir visible varios dias o se pierde.
DIAS_POR_ENTREGAR = 4
# Historia: lo que el transportista ya reporto, solo lectura.
DIAS_HISTORIA = 2

ESTADOS_POR_ENTREGAR = (
    "preventa_aceptada", "confirmado", "recibido",
    "en_preparacion", "despachado", "en_camino",
)

MAX_UPLOAD_BYTES = 12 * 1024 * 1024
EXT_PERMITIDAS = {"jpg", "jpeg", "png", "webp", "heic", "heif", "pdf"}
TOKEN_RE = re.compile(r"^[A-Za-z0-9]{16,64}$")

router = APIRouter(prefix="/api/transportista", tags=["transportista"])
page_router = APIRouter(tags=["transportista"])


def _sb_post(path, data):
    r = _SB_CLIENT.post(f"{SUPABASE_URL}/rest/v1/{path}", headers=_sb_headers(), json=data)
    if r.status_code >= 400:
        import logging
        logging.getLogger("circa").error(f"Supabase insert error {r.status_code}: {r.text}")
        r.raise_for_status()
    return r.json()


def _verify_transportista(token: str) -> dict:
    """Resuelve el token del link. 404 generico: no filtra si existe o esta inactivo."""
    if not token or not TOKEN_RE.match(token):
        raise HTTPException(status_code=404, detail="Link invalido")
    rows = _sb_get("transportistas", {"select": "*", "token": f"eq.{token}", "activo": "is.true"})
    if not rows:
        raise HTTPException(status_code=404, detail="Link invalido o desactivado")
    return rows[0]


def _iso_hace(dias: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=dias)).isoformat()


def _resumen_pedido(p: dict, bodega: dict) -> dict:
    raw = p.get("items_json") or []
    items = raw if isinstance(raw, list) else []
    return {
        "id": p["id"],
        "numero": p.get("numero") or "",
        "estado": p.get("estado") or "",
        "created_at": p.get("created_at"),
        "bodega": (bodega.get("nombre_comercial") or bodega.get("razon_social")
                   or bodega.get("representante_nombre_corto") or bodega.get("representante_legal") or "Bodega"),
        "codigo_afiliado": bodega.get("codigo_afiliado") or "",
        "direccion": bodega.get("direccion_fiscal") or bodega.get("direccion") or "",
        "telefono": bodega.get("telefono_whatsapp") or "",
        "total": float(p.get("total_pedido") or p.get("monto_productos") or 0),
        "cobra_efectivo": float(p.get("monto_contado") or 0),
        "financiado": float(p.get("monto_financiado") or 0),
        "items": [{"nombre": i.get("nombre") or i.get("producto") or "-",
                   "cantidad": i.get("cantidad") or 1} for i in items],
    }


@router.get("/{token}/pedidos")
def pedidos_del_transportista(token: str):
    t = _verify_transportista(token)

    candidatos = _sb_get("pedidos", {
        "select": ("id,numero,estado,bodega_id,created_at,total_pedido,monto_productos,"
                   "monto_contado,monto_financiado,items_json,prueba_entrega_url"),
        "distribuidor_id": f"eq.{t['distribuidor_id']}",
        "estado": f"in.({','.join(ESTADOS_POR_ENTREGAR)})",
        "created_at": f"gte.{_iso_hace(DIAS_POR_ENTREGAR)}",
        "order": "created_at.desc",
        "limit": "300",
    })

    # Reportes recientes: los de este transportista (su historia) y los de
    # cualquiera sobre los candidatos (para no pedir dos veces el mismo voucher).
    mios = _sb_get("entregas_transportista", {
        "select": "*", "transportista_id": f"eq.{t['id']}",
        "reportado_at": f"gte.{_iso_hace(DIAS_HISTORIA)}",
        "order": "reportado_at.desc", "limit": "300",
    })
    ids_cand = [p["id"] for p in candidatos]
    ajenos = []
    if ids_cand:
        ajenos = _sb_get("entregas_transportista", {
            "select": "pedido_id,resultado,reportado_at",
            "pedido_id": f"in.({','.join(ids_cand)})",
            "limit": "500",
        })
    ya_reportados = {r["pedido_id"] for r in ajenos} | {r["pedido_id"] for r in mios}

    # Los pedidos de la historia pueden haber salido ya de los estados candidatos.
    ids_hist = [r["pedido_id"] for r in mios]
    faltantes = [i for i in ids_hist if i not in set(ids_cand)]
    extra = []
    if faltantes:
        extra = _sb_get("pedidos", {
            "select": ("id,numero,estado,bodega_id,created_at,total_pedido,monto_productos,"
                       "monto_contado,monto_financiado,items_json,prueba_entrega_url"),
            "id": f"in.({','.join(faltantes)})",
        })

    todos = {p["id"]: p for p in (candidatos + extra)}
    bodegas = _sb_map_by_ids(
        "bodegas",
        ("id,nombre_comercial,razon_social,representante_nombre_corto,representante_legal,"
         "telefono_whatsapp,direccion_fiscal,es_test,codigo_afiliado"),
        [p.get("bodega_id") for p in todos.values()],
    )

    por_entregar, historia = [], []
    ultimo_reporte = {}
    for r in mios:
        ultimo_reporte.setdefault(r["pedido_id"], r)

    for pid, p in todos.items():
        b = bodegas.get(p.get("bodega_id")) or {}
        if b.get("es_test"):                      # solo bodegas reales
            continue
        if not b:                                 # sin bodega resuelta no se muestra
            continue
        fila = _resumen_pedido(p, b)
        rep = ultimo_reporte.get(pid)
        if rep:
            fila["reporte"] = {
                "resultado": rep.get("resultado"),
                "sustento_url": rep.get("sustento_url"),
                "observacion": rep.get("observacion"),
                "reportado_at": rep.get("reportado_at"),
            }
            historia.append(fila)
        elif pid in ya_reportados:
            continue                              # lo reporto otro transportista
        elif p.get("estado") in ESTADOS_POR_ENTREGAR:
            por_entregar.append(fila)

    historia.sort(key=lambda x: x["reporte"]["reportado_at"] or "", reverse=True)
    return {
        "transportista": t.get("nombre") or "Transportista",
        "por_entregar": por_entregar,
        "historia": historia,
        "dias_historia": DIAS_HISTORIA,
    }


def _pedido_del_distribuidor(pedido_id: str, distribuidor_id: str) -> dict:
    rows = _sb_get("pedidos", {"select": "id,numero,estado",
                               "id": f"eq.{pedido_id}",
                               "distribuidor_id": f"eq.{distribuidor_id}"})
    if not rows:
        raise HTTPException(status_code=404, detail="Pedido no encontrado")
    return rows[0]


@router.post("/{token}/pedidos/{pedido_id}/voucher")
def subir_voucher(token: str, pedido_id: str, file: UploadFile = File(...)):
    """Sube el voucher firmado por el cliente. No cambia el estado del pedido."""
    t = _verify_transportista(token)
    pedido = _pedido_del_distribuidor(pedido_id, t["distribuidor_id"])

    ext = (file.filename or "").rsplit(".", 1)[-1].lower() if "." in (file.filename or "") else "jpg"
    if ext not in EXT_PERMITIDAS:
        raise HTTPException(status_code=400, detail="Formato no permitido. Sube una foto o un PDF.")
    content = file.file.read()
    if not content:
        raise HTTPException(status_code=400, detail="El archivo llego vacio. Intenta de nuevo.")
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=400, detail="La foto pesa demasiado (max 12 MB).")

    ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    storage_path = f"transportista/{pedido_id}_{ts}.{ext}"
    r = httpx.post(
        f"{SUPABASE_URL}/storage/v1/object/sustentos/{storage_path}",
        headers={"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}",
                 "Content-Type": file.content_type or "application/octet-stream",
                 "x-upsert": "true"},
        content=content, timeout=60,
    )
    if r.status_code >= 300:
        import logging
        logging.getLogger("circa").error(f"[transportista] storage {r.status_code}: {r.text}")
        raise HTTPException(status_code=502, detail="No se pudo guardar la foto. Intenta de nuevo.")

    url = f"{SUPABASE_URL}/storage/v1/object/public/sustentos/{storage_path}"
    _sb_post("entregas_transportista", {
        "pedido_id": pedido_id, "transportista_id": t["id"],
        "resultado": "entregado", "sustento_url": url,
    })
    # Alimenta el portal del distribuidor y el cierre diario sin tocar el estado.
    _sb_patch("pedidos", {"prueba_entrega_url": url}, {"id": f"eq.{pedido_id}"})
    return {"ok": True, "url": url, "numero": pedido.get("numero", "")}


@router.post("/{token}/pedidos/{pedido_id}/no-entregado")
def reportar_no_entregado(token: str, pedido_id: str, motivo: str = Form(...)):
    """El pedido no se pudo entregar hoy. Queda registrado, el pedido no se toca."""
    t = _verify_transportista(token)
    pedido = _pedido_del_distribuidor(pedido_id, t["distribuidor_id"])
    motivo = (motivo or "").strip()[:300]
    if not motivo:
        raise HTTPException(status_code=400, detail="Escribe el motivo.")
    _sb_post("entregas_transportista", {
        "pedido_id": pedido_id, "transportista_id": t["id"],
        "resultado": "no_entregado", "observacion": motivo,
    })
    return {"ok": True, "numero": pedido.get("numero", "")}


@page_router.get("/t/{token}")
def hoja_transportista(token: str):
    _verify_transportista(token)
    return FileResponse("static/transportista.html")
