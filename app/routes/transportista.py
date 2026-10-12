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
# Los NO ENTREGADOS duran mas: un feriado o un domingo en medio no debe
# borrarlos de la pantalla antes de que se resuelvan.
DIAS_HISTORIA_NO_ENTREGADO = 3
# Ventana para que el propio transportista deshaga un reporte equivocado.
HORAS_DESHACER = 24

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


def _resumen_pedido(p: dict, bodega: dict, comercial: dict) -> dict:
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
        "vendedor": comercial.get("vendedor") or "",
        "vendedor_codigo": comercial.get("vendedor_codigo") or "",
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
    _ventana = max(DIAS_HISTORIA, DIAS_HISTORIA_NO_ENTREGADO)
    mios = _sb_get("entregas_transportista", {
        "select": "*", "transportista_id": f"eq.{t['id']}", "anulado_at": "is.null",
        "reportado_at": f"gte.{_iso_hace(_ventana)}",
        "order": "reportado_at.desc", "limit": "300",
    })
    _corte_corto = _iso_hace(DIAS_HISTORIA)
    mios = [r for r in mios
            if r.get("resultado") == "no_entregado" or (r.get("reportado_at") or "") >= _corte_corto]
    ids_cand = [p["id"] for p in candidatos]
    ajenos = []
    if ids_cand:
        ajenos = _sb_get("entregas_transportista", {
            "select": "pedido_id,resultado,reportado_at",
            "pedido_id": f"in.({','.join(ids_cand)})",
            "anulado_at": "is.null",
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

    # Vendedor RESPONSABLE de la bodega (no quien armo la preventa: ese campo,
    # pedidos.vendedor_id, dice ADMIN CIRCA en las preventas importadas).
    # Se lee bodega_vendedores directo y no vw_bodega_comercial, porque la vista
    # hace DISTINCT ON ... ORDER BY created_at y devolveria la asignacion MAS
    # ANTIGUA si una bodega llegara a tener dos activas. Aqui gana la mas reciente.
    comercial = {}
    _bids = list({p.get("bodega_id") for p in todos.values() if p.get("bodega_id")})
    if _bids:
        _asig = _sb_get("bodega_vendedores", {
            "select": "bodega_id,created_at,vendedores(codigo,nombre)",
            "bodega_id": f"in.({','.join(_bids)})",
            "activo": "is.true",
            "order": "created_at.desc",
        })
        for _a in _asig:
            if _a["bodega_id"] in comercial:
                continue
            _v = _a.get("vendedores") or {}
            comercial[_a["bodega_id"]] = {"vendedor": _v.get("nombre") or "",
                                          "vendedor_codigo": _v.get("codigo") or ""}

    _limite_deshacer = (datetime.now(timezone.utc) - timedelta(hours=HORAS_DESHACER)).isoformat()
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
        fila = _resumen_pedido(p, b, comercial.get(p.get("bodega_id")) or {})
        rep = ultimo_reporte.get(pid)
        if rep:
            fila["estado_reporte"] = rep.get("resultado")
            fila["reporte"] = {
                "id": rep.get("id"),
                "resultado": rep.get("resultado"),
                "sustento_url": rep.get("sustento_url"),
                "observacion": rep.get("observacion"),
                "reportado_at": rep.get("reportado_at"),
                "puede_deshacer": (rep.get("reportado_at") or "") >= _limite_deshacer,
            }
            historia.append(fila)
        elif pid in ya_reportados:
            continue                              # lo reporto otro transportista
        elif p.get("estado") in ESTADOS_POR_ENTREGAR:
            fila["estado_reporte"] = "pendiente"
            por_entregar.append(fila)

    historia.sort(key=lambda x: x["reporte"]["reportado_at"] or "", reverse=True)
    return {
        "transportista": t.get("nombre") or "Transportista",
        "por_entregar": por_entregar,
        "historia": historia,
        "dias_historia": DIAS_HISTORIA,
        "dias_historia_no_entregado": DIAS_HISTORIA_NO_ENTREGADO,
    }


def _pedido_del_distribuidor(pedido_id: str, distribuidor_id: str) -> dict:
    rows = _sb_get("pedidos", {"select": "id,numero,estado",
                               "id": f"eq.{pedido_id}",
                               "distribuidor_id": f"eq.{distribuidor_id}"})
    if not rows:
        raise HTTPException(status_code=404, detail="Pedido no encontrado")
    return rows[0]


RESULTADOS = {
    # resultado -> (necesita foto, necesita motivo)
    "entregado":      (True,  False),   # voucher firmado por el cliente
    "no_entregado":   (False, True),    # no se pudo entregar
    "entregado_cash": (False, False),   # entregado y el cliente pago todo en efectivo
}


def _subir_a_storage(pedido_id: str, file: UploadFile) -> str:
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
    return f"{SUPABASE_URL}/storage/v1/object/public/sustentos/{storage_path}"


@router.post("/{token}/pedidos/{pedido_id}/reporte")
def reportar(token: str, pedido_id: str,
             resultado: str = Form("entregado"),
             motivo: Optional[str] = Form(None),
             file: Optional[UploadFile] = File(None)):
    """Reporte de reparto. NO cambia `pedidos.estado` en ningun caso.

    entregado      -> voucher firmado, obligatorio.
    no_entregado   -> motivo obligatorio.
    entregado_cash -> el cliente pago todo en efectivo. Foto opcional; Circa
                      decide despues si el pedido pasa a `pagado_cash`.
    """
    t = _verify_transportista(token)
    pedido = _pedido_del_distribuidor(pedido_id, t["distribuidor_id"])

    if resultado not in RESULTADOS:
        raise HTTPException(status_code=400, detail="Reporte invalido.")
    necesita_foto, necesita_motivo = RESULTADOS[resultado]

    motivo = (motivo or "").strip()[:300]
    if necesita_motivo and not motivo:
        raise HTTPException(status_code=400, detail="Escribe el motivo.")
    if necesita_foto and file is None:
        raise HTTPException(status_code=400, detail="Falta la foto del voucher firmado.")

    url = _subir_a_storage(pedido_id, file) if file is not None else None

    _sb_post("entregas_transportista", {
        "pedido_id": pedido_id, "transportista_id": t["id"],
        "resultado": resultado, "sustento_url": url, "observacion": motivo or None,
    })
    # AISLAMIENTO (Paola, 12-oct-2026): nada de lo que haga el transportista
    # escribe en `pedidos`. Ni estado, ni prueba_entrega_url. El reporte vive
    # solo en `entregas_transportista`; el portal del distribuidor lo LEE y lo
    # muestra aparte. El sustento oficial del pedido lo sigue poniendo Circa.
    return {"ok": True, "resultado": resultado, "url": url, "numero": pedido.get("numero", "")}


@router.delete("/{token}/reportes/{reporte_id}")
def deshacer_reporte(token: str, reporte_id: str):
    """ANULA un reporte propio y reciente. No borra nada.

    La fila se queda con `anulado_at` sellado: desaparece de la hoja del
    transportista y el pedido vuelve a 'por entregar', pero Circa sigue viendo
    en el portal que hubo un reporte y que se anulo. Un tercero no borra
    evidencia. Tampoco se toca `pedidos` ni el archivo del storage.
    """
    t = _verify_transportista(token)
    rows = _sb_get("entregas_transportista", {
        "select": "id,reportado_at,anulado_at",
        "id": f"eq.{reporte_id}",
        "transportista_id": f"eq.{t['id']}",
    })
    if not rows:
        raise HTTPException(status_code=404, detail="Ese reporte no es tuyo o ya no existe.")
    if rows[0].get("anulado_at"):
        return {"ok": True, "nota": "ya estaba anulado"}
    limite = (datetime.now(timezone.utc) - timedelta(hours=HORAS_DESHACER)).isoformat()
    if (rows[0].get("reportado_at") or "") < limite:
        raise HTTPException(
            status_code=400,
            detail=f"Solo se puede deshacer dentro de las {HORAS_DESHACER} horas. Avisa a Circa.")
    _sb_patch("entregas_transportista",
              {"anulado_at": datetime.now(timezone.utc).isoformat(),
               "anulado_por": f"transportista:{t.get('nombre') or t['id']}"},
              {"id": f"eq.{reporte_id}", "transportista_id": f"eq.{t['id']}"})
    return {"ok": True}


@page_router.get("/t/{token}")
def hoja_transportista(token: str):
    _verify_transportista(token)
    return FileResponse("static/transportista.html")
