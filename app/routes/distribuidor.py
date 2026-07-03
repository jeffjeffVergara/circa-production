"""
Distribuidor Portal API — Circa
"""
from fastapi import APIRouter, HTTPException, Header, Depends, UploadFile, File
from pydantic import BaseModel, Field
from typing import Optional, List
import os, httpx
from datetime import datetime, timezone

router = APIRouter(prefix="/api/distribuidor", tags=["distribuidor"])

SUPABASE_URL = os.getenv("SUPABASE_URL", "https://rhxqcoijzgqlecpdfhde.supabase.co")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_KEY", os.getenv("SUPABASE_KEY", ""))

def _sb_headers():
    return {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}",
            "Content-Type": "application/json", "Prefer": "return=representation"}

def _sb_get(path, params=None):
    r = httpx.get(f"{SUPABASE_URL}/rest/v1/{path}", headers=_sb_headers(), params=params or {}, timeout=15)
    if r.status_code >= 400:
        import logging
        logging.getLogger("circa").error(f"Supabase error {r.status_code}: {r.text}")
        r.raise_for_status()
    return r.json()

def _sb_patch(path, data, params=None):
    r = httpx.patch(f"{SUPABASE_URL}/rest/v1/{path}", headers=_sb_headers(), json=data, params=params or {}, timeout=15)
    r.raise_for_status()
    return r.json()


def _sb_map_by_ids(table: str, select: str, ids: list[str], id_col: str = "id") -> dict:
    """Batch fetch rows by id (evita N+1)."""
    uniq = list({i for i in ids if i})
    if not uniq:
        return {}
    rows = _sb_get(table, {"select": select, id_col: f"in.({','.join(uniq)})"})
    return {row[id_col]: row for row in rows}


async def verify_distribuidor(x_api_token: str = Header(..., alias="X-API-Token")):
    rows = _sb_get("distribuidores", {"select": "*", "api_token": f"eq.{x_api_token}"})
    if not rows:
        raise HTTPException(status_code=401, detail="Token invalido")
    return rows[0]

from app.services.order_status import STATUS_FLOW, STATUS_LABELS as _STATUS_LABELS

STATUS_LABELS = {**_STATUS_LABELS, "pagado": "Pagado"}

WA_MESSAGES = {
    "recibido": "✅ *Pedido {numero} recibido*\n{distribuidor} recibió tu pedido y lo está preparando.",
    "en_preparacion": "📦 *Pedido {numero} en preparacion*\n{distribuidor} esta armando tu pedido.",
    "despachado": "🚚 *Pedido {numero} despachado*\n{distribuidor} despacho tu pedido. Salio del almacen.",
    "en_camino": "🚚 *Pedido {numero} en camino*\nTu pedido salió del almacén y va camino a tu bodega.",
    "entregado": "🎉 *Pedido {numero} entregado*\nTu pedido fue entregado en tu bodega. Gracias por comprar con Circa!",
}

META_TOKEN = os.getenv("META_ACCESS_TOKEN", "")
PHONE_NUMBER_ID = os.getenv("META_PHONE_NUMBER_ID", "1076586305533033")

def _send_wa_text(to, text):
    if not META_TOKEN: return
    try:
        httpx.post(f"https://graph.facebook.com/v23.0/{PHONE_NUMBER_ID}/messages",
            headers={"Authorization": f"Bearer {META_TOKEN}", "Content-Type": "application/json"},
            json={"messaging_product":"whatsapp","to":to,"type":"text","text":{"body":text}}, timeout=15)
    except Exception as e:
        print(f"[WA notify error] {e}")


# ── Plantillas de cobranza (WhatsApp message templates aprobadas en Meta) ──
# El recordatorio se elige segun los dias transcurridos desde el despacho.
# "vars" es el orden EXACTO de las variables {{1}}, {{2}}, ... de cada plantilla.
COBRANZA_TEMPLATES = {
    "dia2": {"name": "recordatorio_dia2_v1", "vars": ["nombre", "cuota", "vence"]},
    "dia4": {"name": "cobranza_dia_4",       "vars": ["nombre", "cuota", "vence", "linea"]},
    "dia6": {"name": "cobranza_dia_6",       "vars": ["nombre", "cuota", "linea"]},
}

# WABA (cuenta de WhatsApp Business) a la que pertenece el numero que envia.
WABA_ID = os.getenv("WABA_ID", "965950269106934")
# Codigos de espanol validos en la API de envio de Meta (no existe "es_PE").
COBRANZA_LANG_CANDIDATES = ["es", "es_MX", "es_ES", "es_AR"]
# Catalogo de plantillas consultado a Meta: {nombre: idioma_real}. Se carga una vez.
_META_TEMPLATES = {"cargado": False, "mapa": {}, "error": ""}


def _fmt_monto(x):
    """Formatea un monto: sin decimales si es entero, con 2 decimales si no."""
    try:
        x = float(x or 0)
    except Exception:
        x = 0.0
    return str(int(x)) if x == int(x) else f"{x:.2f}"


def _cargar_plantillas_meta():
    """Consulta a Meta (una sola vez) el catalogo de plantillas de la WABA y
    arma el mapa {nombre: idioma_real}. Si la consulta falla, guarda el error."""
    if _META_TEMPLATES["cargado"]:
        return _META_TEMPLATES
    try:
        r = httpx.get(
            f"https://graph.facebook.com/v23.0/{WABA_ID}/message_templates",
            params={"fields": "name,language,status", "limit": 250, "access_token": META_TOKEN},
            timeout=20)
        if r.status_code < 400:
            for t in r.json().get("data", []):
                nm, lg = t.get("name"), t.get("language")
                if nm and lg and nm not in _META_TEMPLATES["mapa"]:
                    _META_TEMPLATES["mapa"][nm] = lg
            _META_TEMPLATES["cargado"] = True
        else:
            _META_TEMPLATES["error"] = f"HTTP {r.status_code}: {r.text}"
    except Exception as e:
        _META_TEMPLATES["error"] = str(e)
    return _META_TEMPLATES


def _send_wa_template(to, template_name, variables):
    """Envia una plantilla de WhatsApp aprobada en Meta.

    Resuelve el codigo de idioma consultando el catalogo real de Meta; si no lo
    encuentra, prueba los codigos de espanol estandar. Si nada funciona, devuelve
    un diagnostico con las plantillas que la cuenta SI tiene.
    """
    if not META_TOKEN:
        return {"ok": False, "error": "META_TOKEN no configurado"}

    components = []
    if variables:
        components = [{
            "type": "body",
            "parameters": [{"type": "text", "text": str(v)} for v in variables],
        }]

    # Idioma real segun el catalogo de Meta; si no aparece, candidatos estandar.
    catalogo = _cargar_plantillas_meta()
    lang_real = catalogo["mapa"].get(template_name)
    intentos = []
    if lang_real:
        intentos.append(lang_real)
    for c in COBRANZA_LANG_CANDIDATES:
        if c not in intentos:
            intentos.append(c)

    ultimo_error = ""
    for lang in intentos:
        payload = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "template",
            "template": {
                "name": template_name,
                "language": {"code": lang},
                "components": components,
            },
        }
        try:
            r = httpx.post(
                f"https://graph.facebook.com/v23.0/{PHONE_NUMBER_ID}/messages",
                headers={"Authorization": f"Bearer {META_TOKEN}", "Content-Type": "application/json"},
                json=payload, timeout=15)
        except Exception as e:
            ultimo_error = str(e)
            continue
        if r.status_code < 400:
            return {"ok": True, "lang": lang, "response": r.json()}
        ultimo_error = r.text
        # 132001 = la plantilla no existe en ese idioma -> probar el siguiente.
        # Cualquier otro error no se arregla cambiando idioma -> cortar aqui.
        if "132001" not in ultimo_error:
            import logging
            logging.getLogger("circa").error(
                f"[WA template error] {template_name}/{lang}: {r.status_code} {ultimo_error}")
            return {"ok": False, "error": ultimo_error}

    # Nada funciono: devolver diagnostico con lo que la cuenta SI tiene.
    import json as _json, logging
    diag = {
        "plantilla_buscada": template_name,
        "idioma_segun_meta": lang_real,
        "plantillas_en_la_cuenta": catalogo["mapa"],
        "error_al_leer_catalogo": catalogo["error"],
        "ultimo_error_envio": ultimo_error,
    }
    logging.getLogger("circa").error(f"[WA template DIAG] {_json.dumps(diag, ensure_ascii=False)}")
    return {"ok": False, "error": _json.dumps(diag, ensure_ascii=False)}


class StatusUpdate(BaseModel):
    nuevo_estado: str

@router.get("/pedidos")
async def list_pedidos(estado: Optional[str] = None, incluir_test: bool = False, dist: dict = Depends(verify_distribuidor)):
    params = {"select":"*","distribuidor_id":f"eq.{dist['id']}","order":"created_at.desc"}
    if estado: params["estado"] = f"eq.{estado}"
    pedidos = _sb_get("pedidos", params)
    bodega_ids = list(set(p.get("bodega_id", "") for p in pedidos if p.get("bodega_id")))
    bodegas_map = _sb_map_by_ids(
        "bodegas",
        "id,nombre_comercial,razon_social,representante_nombre_corto,representante_legal,telefono_whatsapp,ruc,direccion_fiscal,es_test,codigo_afiliado",
        bodega_ids,
    )
    # El distribuidor ve solo pedidos reales por defecto; ?incluir_test=true muestra los de prueba.
    if not incluir_test:
        pedidos = [p for p in pedidos if not bodegas_map.get(p.get("bodega_id"), {}).get("es_test", False)]
    for p in pedidos:
        p["bodegas"] = bodegas_map.get(p.get("bodega_id"), {})
        if "items_json" in p and "items" not in p:
            p["items"] = p["items_json"]
    return {"pedidos": pedidos, "distribuidor": dist["nombre_comercial"]}

@router.get("/pedidos/{pedido_id}")
async def get_pedido(pedido_id: str, dist: dict = Depends(verify_distribuidor)):
    rows = _sb_get("pedidos", {"select":"*","id":f"eq.{pedido_id}","distribuidor_id":f"eq.{dist['id']}"})
    if not rows: raise HTTPException(status_code=404, detail="Pedido no encontrado")
    return rows[0]

@router.post("/pedidos/{pedido_id}/status")
async def update_status(pedido_id: str, body: StatusUpdate, dist: dict = Depends(verify_distribuidor)):
    rows = _sb_get("pedidos", {"select":"*","id":f"eq.{pedido_id}","distribuidor_id":f"eq.{dist['id']}"})
    if not rows: raise HTTPException(status_code=404, detail="Pedido no encontrado")
    pedido = rows[0]
    # Fetch bodega for notification
    try:
        b_rows = _sb_get("bodegas", {"select":"nombre_comercial,telefono_whatsapp","id":f"eq.{pedido.get('bodega_id','')}"})
        pedido["bodegas"] = b_rows[0] if b_rows else {}
    except: pedido["bodegas"] = {}
    current = pedido["estado"]
    nuevo = body.nuevo_estado
    if nuevo != STATUS_FLOW.get(current):
        raise HTTPException(status_code=400, detail=f"No se puede pasar de '{current}' a '{nuevo}'. Siguiente: '{STATUS_FLOW.get(current)}'")
    _sb_patch("pedidos", {"estado": nuevo, f"fecha_{nuevo}": datetime.now(timezone.utc).isoformat()}, {"id": f"eq.{pedido_id}"})
    bodega = pedido.get("bodegas") or {}
    tel = bodega.get("telefono_whatsapp","")
    if tel and nuevo in WA_MESSAGES:
        _send_wa_text(tel, WA_MESSAGES[nuevo].format(numero=pedido.get("numero",pedido_id[:8]), distribuidor=dist["nombre_comercial"]))
    # If entregado, send payment reminder
    if nuevo == "entregado":
        # Calcular fecha_vencimiento desde entrega
        try:
            ped_fv = _sb_get("pedidos", {"select":"plazo_dias","id":f"eq.{pedido_id}"})[0]
            plazo_d = ped_fv.get("plazo_dias") or 7
            from datetime import timedelta as td
            fv = (datetime.now(timezone.utc) + td(days=plazo_d)).strftime("%Y-%m-%d")
            _sb_patch("pedidos", {"fecha_vencimiento": fv}, {"id": f"eq.{pedido_id}"})
            _sb_patch("pagos", {"fecha_vencimiento": fv}, {"pedido_id": f"eq.{pedido_id}"})
        except Exception as efv:
            import logging
            logging.getLogger("circa").error(f"fecha_vencimiento calc error: {efv}")
        try:
            ped = _sb_get("pedidos", {"select":"*","id":f"eq.{pedido_id}"})[0]
            monto_fin = ped.get("monto_financiado") or 0
            fee = ped.get("fee_monto") or 0
            total_credito = round(monto_fin + fee, 2)
            plazo = ped.get("plazo_dias") or 7
            venc = ped.get("fecha_vencimiento") or ""
            if not venc and ped.get("created_at"):
                from datetime import timedelta
                created = datetime.fromisoformat(ped["created_at"].replace("Z","+00:00"))
                venc = (created + timedelta(days=plazo)).strftime("%d/%m/%Y")
            num = ped.get("numero", "")
            if tel and monto_fin > 0:
                reminder = (
                    f"\U0001f4b3 *Recordatorio de pago*\n"
                    f"━━━━━━━━━━━━━━━━━━\n\n"
                    f"Pedido: *{num}*\n"
                    f"Monto financiado: S/{monto_fin:.2f}\n"
                    f"Fee: S/{fee:.2f}\n"
                    f"*Total a pagar: S/{total_credito:.2f}*\n\n"
                    f"Vence: *{venc}*\n"
                    f"Plazo: {plazo} dias\n\n"
                    f"━━━━━━━━━━━━━━━━━━\n"
                    f"Paga por Yape o Plin al:\n"
                    f"\U0001f4f1 *986311567*\n"
                    f"\U0001f464 PALI SAC\n\n"
                    f"Despues de pagar, escribe *YA PAGUE* en este chat."
                )
                _send_wa_text(tel, reminder)
                # Send payment reminder card
                try:
                    from app.services.cards import generate_payment_reminder_card
                    import tempfile
                    venc_str = venc if isinstance(venc, str) else str(venc)
                    card_bytes = generate_payment_reminder_card(num, monto_fin, fee, total_credito, plazo, venc_str)
                    tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
                    tmp.write(card_bytes)
                    tmp.close()
                    upload_r = httpx.post(
                        f"https://graph.facebook.com/v23.0/{PHONE_NUMBER_ID}/media",
                        headers={"Authorization": f"Bearer {META_TOKEN}"},
                        files={"file": ("reminder.png", open(tmp.name, "rb"), "image/png")},
                        data={"messaging_product": "whatsapp", "type": "image/png"},
                        timeout=30)
                    media_id = upload_r.json().get("id")
                    if media_id:
                        httpx.post(f"https://graph.facebook.com/v23.0/{PHONE_NUMBER_ID}/messages",
                            headers={"Authorization": f"Bearer {META_TOKEN}", "Content-Type": "application/json"},
                            json={"messaging_product": "whatsapp", "to": tel, "type": "image",
                                  "image": {"id": media_id}}, timeout=15)
                    import os; os.unlink(tmp.name)
                except Exception as card_e:
                    import logging
                    logging.getLogger("circa").error(f"Reminder card error: {card_e}")
        except Exception as e:
            import logging
            logging.getLogger("circa").error(f"Payment reminder error: {e}")
    return {"ok":True,"pedido_id":pedido_id,"estado_anterior":current,"estado_nuevo":nuevo,"notificado":bool(tel)}

@router.post("/pedidos/{pedido_id}/facturar")
async def preparar_factura(pedido_id: str, dist: dict = Depends(verify_distribuidor)):
    rows = _sb_get("pedidos", {"select":"*","id":f"eq.{pedido_id}","distribuidor_id":f"eq.{dist['id']}"})
    if not rows: raise HTTPException(status_code=404, detail="Pedido no encontrado")
    pedido = rows[0]
    try:
        b_rows = _sb_get("bodegas", {"select":"nombre_comercial,telefono_whatsapp,ruc,direccion,razon_social","id":f"eq.{pedido.get('bodega_id','')}"})
        pedido["bodegas"] = b_rows[0] if b_rows else {}
    except: pedido["bodegas"] = {}
    if pedido["estado"] not in ("despachado","en_camino","entregado"):
        raise HTTPException(status_code=400, detail="Solo se puede facturar pedidos despachados o entregados")
    bodega = pedido.get("bodegas") or {}
    items = pedido.get("items_json", pedido.get("items", []))
    lineas, subtotal = [], 0
    for i, item in enumerate(items, 1):
        pu = item.get("precio_unitario", item.get("precio", 0))
        cant = item.get("cantidad", 1)
        vv = pu * cant
        igv = round(vv * 0.18, 2)
        lineas.append({"numero":i,"codigo":item.get("codigo",f"PROD-{i:03d}"),"descripcion":item.get("nombre",item.get("producto","")),"cantidad":cant,"unidad_medida":item.get("unidad","NIU"),"precio_unitario":pu,"valor_venta":round(vv,2),"igv":igv,"precio_venta":round(vv+igv,2)})
        subtotal += vv
    igv_total = round(subtotal * 0.18, 2)
    factura = {"tipo_documento":"01","serie":dist.get("serie_factura","F001"),
        "emisor":{"ruc":dist.get("ruc",""),"razon_social":dist.get("razon_social",dist["nombre_comercial"]),"direccion":dist.get("direccion","")},
        "receptor":{"ruc":bodega.get("ruc",""),"razon_social":bodega.get("razon_social",bodega.get("nombre_comercial","")),"direccion":bodega.get("direccion","")},
        "fecha_emision":datetime.now(timezone.utc).strftime("%Y-%m-%d"),"moneda":"PEN","items":lineas,
        "subtotal":round(subtotal,2),"igv":igv_total,"total":round(subtotal+igv_total,2),
        "pedido_circa":pedido.get("numero",""),"observacion":f"Pedido Circa {pedido.get('numero','')}"}
    _sb_patch("pedidos", {"facturado":True,"fecha_facturado":datetime.now(timezone.utc).isoformat()}, {"id":f"eq.{pedido_id}"})
    return {"factura": factura}

@router.get("/conciliacion")
async def conciliacion(fecha: Optional[str] = None, dist: dict = Depends(verify_distribuidor)):
    """Daily reconciliation: how much Circa owes the distributor."""
    params = {"select":"*","distribuidor_id":f"eq.{dist['id']}","estado":"in.(confirmado,recibido,en_preparacion,despachado,en_camino,entregado)"}
    pedidos = _sb_get("pedidos", params)
    total_productos = 0
    total_financiado = 0
    total_contado = 0
    total_fee_circa = 0
    desglose = []
    for p in pedidos:
        mp = p.get("monto_productos") or 0
        mf = p.get("monto_financiado") or 0
        mc = p.get("monto_contado") or 0
        fee = p.get("fee_monto") or 0
        total_productos += mp
        total_financiado += mf
        total_contado += mc
        total_fee_circa += fee
        desglose.append({
            "numero": p.get("numero",""),
            "estado": p.get("estado",""),
            "monto_productos": round(mp,2),
            "bodega_paga_contado": round(mc,2),
            "circa_financia": round(mf,2),
            "fee_circa": round(fee,2),
            "circa_paga_distribuidor": round(mf,2),
        })
    return {
        "distribuidor": dist["nombre_comercial"],
        "resumen": {
            "total_productos": round(total_productos,2),
            "total_bodega_contado": round(total_contado,2),
            "total_circa_financia": round(total_financiado,2),
            "circa_debe_distribuidor": round(total_financiado,2),
            "total_fee_circa": round(total_fee_circa,2),
            "pedidos_count": len(pedidos),
        },
        "desglose": desglose,
    }


@router.post("/pedidos/{pedido_id}/sustento")
async def upload_sustento(pedido_id: str, file: UploadFile = File(...), dist: dict = Depends(verify_distribuidor)):
    """Upload delivery proof (signed guide, invoice, photo)."""
    rows = _sb_get("pedidos", {"select":"id,estado","id":f"eq.{pedido_id}","distribuidor_id":f"eq.{dist['id']}"})
    if not rows:
        raise HTTPException(status_code=404, detail="Pedido no encontrado")
    if rows[0]["estado"] not in ("despachado","en_camino","entregado"):
        raise HTTPException(status_code=400, detail="Solo se puede subir sustento para pedidos despachados o entregados")
    content = await file.read()
    import base64
    ext = file.filename.split(".")[-1] if "." in file.filename else "jpg"
    # Upload to Supabase Storage
    storage_path = f"sustentos/{pedido_id}.{ext}"
    try:
        upload_url = f"{SUPABASE_URL}/storage/v1/object/sustentos/{storage_path}"
        r = httpx.post(upload_url, headers={
            "apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}",
            "Content-Type": file.content_type or "application/octet-stream",
            "x-upsert": "true",
        }, content=content, timeout=30)
        if r.status_code < 300:
            public_url = f"{SUPABASE_URL}/storage/v1/object/public/sustentos/{storage_path}"
            _sb_patch("pedidos", {"prueba_entrega_url": public_url}, {"id": f"eq.{pedido_id}"})
            return {"ok": True, "url": public_url}
        else:
            # Fallback: store as base64 data URL
            b64 = base64.b64encode(content).decode()
            data_url = f"data:{file.content_type};base64,{b64[:100]}..."
            _sb_patch("pedidos", {"prueba_entrega_url": f"uploaded:{file.filename}"}, {"id": f"eq.{pedido_id}"})
            return {"ok": True, "url": f"uploaded:{file.filename}", "note": "Storage bucket may need setup"}
    except Exception as e:
        _sb_patch("pedidos", {"prueba_entrega_url": f"uploaded:{file.filename}"}, {"id": f"eq.{pedido_id}"})
        return {"ok": True, "url": f"uploaded:{file.filename}", "note": str(e)}

# ===================== CIRCA ADMIN =====================

from app.config import admin_token_or_raise


async def verify_admin(x_admin_token: str = Header(..., alias="X-Admin-Token")):
    import hmac

    expected = admin_token_or_raise()
    if not x_admin_token or not hmac.compare_digest(x_admin_token.strip(), expected):
        raise HTTPException(status_code=401, detail="Token admin invalido")
    return True


def _verify_admin_action(autorizacion: str) -> None:
    """Segunda confirmación: token escrito en el formulario de soporte."""
    if (autorizacion or "").strip() != admin_token_or_raise():
        raise HTTPException(status_code=403, detail="Autorización inválida")


def _pin_url(bodega_id: str, mode: str = "create") -> str:
    base = os.getenv("APP_BASE_URL", "http://localhost:8000").rstrip("/")
    phone_id = os.getenv("META_PHONE_NUMBER_ID", os.getenv("PHONE_NUMBER_ID", ""))
    to = phone_id.strip() if phone_id else ""
    return f"{base}/pin?b={bodega_id}&mode={mode}&to={to}"


class AdminPinAction(BaseModel):
    comentario: str = Field(..., min_length=8, max_length=500)
    autorizacion: str = Field(..., min_length=1)


class AdminPinSet(AdminPinAction):
    pin: str
    pin_confirm: str


# ──────────────────────────────────────────────────────────────────────
# Helper: filtrar por bodegas de prueba vs reales
# Acepta: test='real'|'false' (solo reales con es_test=false)
#         test='test'|'true'  (solo pruebas con es_test=true)
#         test=None|'all'     (sin filtro — comportamiento original)
# ──────────────────────────────────────────────────────────────────────
def _bodega_ids_por_test(test_param):
    """Devuelve set de bodega_ids matching el filtro test/real, o None si no hay filtro."""
    if not test_param or str(test_param).lower() in ("all", "todas", "todos"):
        return None
    is_test = str(test_param).lower() in ("test", "true", "prueba", "pruebas", "1")
    es_test_val = "true" if is_test else "false"
    try:
        rows = _sb_get("bodegas", {
            "select": "id",
            "es_test": f"eq.{es_test_val}",
            "limit": "2000"
        })
        return set(r.get("id") for r in rows if r.get("id"))
    except Exception:
        return None  # si la columna no existe todavía, no filtrar


def _days_ago_iso(days: int) -> str:
    from datetime import timedelta
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

@router.get("/admin/pedidos")
async def admin_list_pedidos(
    bodega: Optional[str] = None,
    distribuidor: Optional[str] = None,
    estado: Optional[str] = None,
    tipo: Optional[str] = None,
    test: Optional[str] = None,
    admin: bool = Depends(verify_admin),
):
    """List all orders with full details — admin view. Filtra por test/real."""
    params = {"select":"*","order":"created_at.desc","limit":"1000"}
    if estado: params["estado"] = f"eq.{estado}"
    if tipo in ("venta", "preventa"):
        params["tipo_operacion"] = f"eq.{tipo}"
    pedidos = _sb_get("pedidos", params)
    # NUEVO: filtrar por test/real
    ids_filter = _bodega_ids_por_test(test)
    if ids_filter is not None:
        pedidos = [p for p in pedidos if p.get("bodega_id") in ids_filter]
    # Fetch all bodegas and distribuidores
    bodega_ids = list(set(p.get("bodega_id","") for p in pedidos if p.get("bodega_id")))
    dist_ids = list(set(p.get("distribuidor_id","") for p in pedidos if p.get("distribuidor_id")))
    bodegas_map = {}
    for bid in bodega_ids:
        try:
            rows = _sb_get("bodegas", {
                "select": (
                    "id,nombre_comercial,razon_social,representante_legal,"
                    "representante_nombre_corto,telefono_whatsapp,ruc,"
                    "direccion_fiscal,linea_aprobada,linea_disponible"
                ),
                "id": f"eq.{bid}",
            })
            if rows: bodegas_map[bid] = rows[0]
        except: pass
    dist_map = {}
    for did in dist_ids:
        try:
            rows = _sb_get("distribuidores", {"select":"id,nombre_comercial,ruc","id":f"eq.{did}"})
            if rows: dist_map[did] = rows[0]
        except: pass
    for p in pedidos:
        p["bodega"] = bodegas_map.get(p.get("bodega_id"), {})
        p["distribuidor"] = dist_map.get(p.get("distribuidor_id"), {})
        if "items_json" in p and "items" not in p:
            p["items"] = p["items_json"]
    # Filter by name if provided
    if bodega:
        bl = bodega.lower()
        def _match_bodega(p: dict) -> bool:
            b = p.get("bodega", {}) or {}
            haystack = " ".join([
                b.get("nombre_comercial", "") or "",
                b.get("razon_social", "") or "",
                b.get("representante_legal", "") or "",
                b.get("representante_nombre_corto", "") or "",
                b.get("telefono_whatsapp", "") or "",
                b.get("ruc", "") or "",
            ]).lower()
            return bl in haystack
        pedidos = [p for p in pedidos if _match_bodega(p)]
    if distribuidor:
        dl = distribuidor.lower()
        pedidos = [p for p in pedidos if dl in (p.get("distribuidor",{}).get("nombre_comercial","") or "").lower()]
    return {"pedidos": pedidos, "total": len(pedidos)}


@router.post("/admin/preventa/{pedido_id}/aceptar")
async def admin_aceptar_preventa(pedido_id: str, admin: bool = Depends(verify_admin)):
    rows = _sb_get("pedidos", {"select":"id,numero,estado,tipo_operacion","id":f"eq.{pedido_id}"})
    if not rows:
        raise HTTPException(status_code=404, detail="Pedido no encontrado")
    p = rows[0]
    if p.get("tipo_operacion") != "preventa":
        raise HTTPException(status_code=400, detail="El pedido no es pre-venta")
    if p.get("estado") != "preventa_confirmada":
        raise HTTPException(status_code=400, detail="La pre-venta no está en estado confirmada")
    _sb_patch(
        "pedidos",
        {
            "estado": "preventa_aceptada",
            "preventa_aceptada_at": datetime.now(timezone.utc).isoformat(),
            "preventa_aceptada_por": "admin",
        },
        {"id": f"eq.{pedido_id}"},
    )
    return {"ok": True, "pedido_id": pedido_id, "estado": "preventa_aceptada", "numero": p.get("numero")}

@router.get("/admin/resumen")
async def admin_resumen(
    test: Optional[str] = None,
    admin: bool = Depends(verify_admin),
):
    """Dashboard summary for Circa admin. Filtra por bodegas reales/test si test=real|test."""
    # NUEVO: agregamos bodega_id al SELECT para poder filtrar por es_test
    pedidos = _sb_get("pedidos", {
        "select": "estado,monto_productos,monto_financiado,monto_contado,fee_monto,total,bodega_id",
        "limit": "500"
    })
    # NUEVO: filtrar por test/real si corresponde
    ids_filter = _bodega_ids_por_test(test)
    if ids_filter is not None:
        pedidos = [p for p in pedidos if p.get("bodega_id") in ids_filter]

    estados = {}
    total_financiado = 0
    total_fee = 0
    total_contado = 0
    for p in pedidos:
        e = p.get("estado","?")
        estados[e] = estados.get(e, 0) + 1
        total_financiado += p.get("monto_financiado") or 0
        total_fee += p.get("fee_monto") or 0
        total_contado += p.get("monto_contado") or 0
    return {
        "pedidos_por_estado": estados,
        "total_pedidos": len(pedidos),
        "total_financiado": round(total_financiado, 2),
        "total_fee_circa": round(total_fee, 2),
        "total_contado": round(total_contado, 2),
        "circa_cobra_bodegas": round(total_financiado + total_fee, 2),
        "filtro_aplicado": test or "todas",
    }


@router.get("/admin/analytics-resumen")
async def admin_analytics_resumen(
    test: Optional[str] = None,
    admin: bool = Depends(verify_admin),
):
    """Light analytics dashboard for pilot event/message tracking. Filtra por test/real."""
    since_7d = _days_ago_iso(7)
    since_30d = _days_ago_iso(30)

    events_7d = _sb_get("events", {"select": "event_type,created_at,bodega_id", "created_at": f"gte.{since_7d}", "limit": "5000"})
    events_30d = _sb_get("events", {"select": "event_type,created_at,bodega_id", "created_at": f"gte.{since_30d}", "limit": "20000"})
    msgs_7d = _sb_get("messages", {"select": "direction,bodega_id,created_at", "created_at": f"gte.{since_7d}", "limit": "10000"})
    
    # NUEVO: filtrar por test/real
    ids_filter = _bodega_ids_por_test(test)
    if ids_filter is not None:
        events_7d = [e for e in events_7d if e.get("bodega_id") in ids_filter]
        events_30d = [e for e in events_30d if e.get("bodega_id") in ids_filter]
        msgs_7d = [m for m in msgs_7d if m.get("bodega_id") in ids_filter]

    def _cnt(rows, ev):
        return sum(1 for r in rows if r.get("event_type") == ev)

    funnel = {
        "catalog_opened": _cnt(events_7d, "catalog_opened"),
        "product_added": _cnt(events_7d, "product_added"),
        "order_created": _cnt(events_7d, "order_created") + _cnt(events_7d, "preventa_created"),
        "order_confirmed": _cnt(events_7d, "order_confirmed") + _cnt(events_7d, "preventa_confirmada"),
        "payment_made": _cnt(events_7d, "payment_made"),
    }

    inbound = sum(1 for m in msgs_7d if m.get("direction") == "inbound")
    outbound = sum(1 for m in msgs_7d if m.get("direction") == "outbound")
    response_rate = round((inbound / outbound) * 100, 1) if outbound else 0.0

    by_type = {}
    for ev in events_7d:
        t = ev.get("event_type", "unknown")
        by_type[t] = by_type.get(t, 0) + 1
    top_events = sorted(
        [{"event_type": k, "count": v} for k, v in by_type.items()],
        key=lambda x: x["count"],
        reverse=True,
    )[:8]

    active_bodegas_30d = len(set(e.get("bodega_id") for e in events_30d if e.get("bodega_id")))

    return {
        "period_days": 7,
        "funnel": funnel,
        "messages": {
            "inbound_7d": inbound,
            "outbound_7d": outbound,
            "response_rate_pct": response_rate,
        },
        "active_bodegas_30d": active_bodegas_30d,
        "top_events_7d": top_events,
    }

@router.post("/admin/cobranza/{pedido_id}")
async def admin_send_cobranza(pedido_id: str, admin: bool = Depends(verify_admin)):
    """Envia el recordatorio de pago al bodeguero usando la plantilla aprobada de
    Meta que corresponde al dia de cobranza (2 / 4 / 6 dias desde el despacho)."""
    from app.services.cobranza_recordatorios import send_recordatorio_pedido

    result = await send_recordatorio_pedido(pedido_id)
    if not result.get("ok"):
        err = str(result.get("error") or "")
        if "no encontrado" in err.lower():
            raise HTTPException(status_code=404, detail=err)
        if any(x in err.lower() for x in ("sin telefono", "no elegible", "no tiene saldo")):
            raise HTTPException(status_code=400, detail=err)
        raise HTTPException(status_code=502, detail=err)
    return result

# ===================== COBRANZAS =====================

@router.get("/admin/cobranzas")
async def admin_cobranzas(
    distribuidor: Optional[str] = None,
    bodega: Optional[str] = None,
    estado: Optional[str] = None,
    fecha_desde: Optional[str] = None,
    fecha_hasta: Optional[str] = None,
    test: Optional[str] = None,
    admin: bool = Depends(verify_admin),
):
    """List all orders with delivery status + payment tracking. Filtra por test/real."""
    from datetime import datetime, timedelta
    
    params = {
        "select": "*",
        "estado": "in.(entregado,pago_reportado,pagado)",
        "order": "created_at.desc",
        "limit": "500"
    }
    pedidos = _sb_get("pedidos", params)
    # NUEVO: filtrar por test/real
    ids_filter = _bodega_ids_por_test(test)
    if ids_filter is not None:
        pedidos = [p for p in pedidos if p.get("bodega_id") in ids_filter]
    
    # Bodegas
    bodega_ids = list(set(p.get("bodega_id", "") for p in pedidos if p.get("bodega_id")))
    bodegas_map = _sb_map_by_ids(
        "bodegas",
        "id,nombre_comercial,telefono_whatsapp,ruc,direccion_fiscal",
        bodega_ids,
    )

    dist_ids = list(set(p.get("distribuidor_id", "") for p in pedidos if p.get("distribuidor_id")))
    dist_map = _sb_map_by_ids("distribuidores", "id,nombre_comercial,ruc", dist_ids)
    
    from app.services.fees import total_pagar_desde_pedido, resolver_fecha_vencimiento_pedido

    hoy = datetime.utcnow().date()
    resultado = []

    # ── Ultimo recordatorio de cobranza enviado, por pedido (tabla messages) ──
    recordatorios_map = {}
    try:
        _msgs = _sb_get("messages", {
            "select": "template_name,metadata,created_at",
            "message_type": "eq.cobranza_recordatorio",
            "order": "created_at.desc",
            "limit": "2000",
        })
        for _m in _msgs:
            _meta = _m.get("metadata") or {}
            _pid = _meta.get("pedido_id")
            if _pid and _pid not in recordatorios_map:
                recordatorios_map[_pid] = {
                    "fecha": _m.get("created_at"),
                    "plantilla": _m.get("template_name"),
                    "dia": _meta.get("dia"),
                }
    except Exception:
        recordatorios_map = {}

    for p in pedidos:
        if float(p.get("monto_financiado") or 0) <= 0:
            continue

        plazo = p.get("plazo_dias") or 0
        fecha_entregado = p.get("fecha_entregado") or p.get("created_at")
        venc = resolver_fecha_vencimiento_pedido(p, hoy)
        if venc is not None:
            dias_restantes = (venc - hoy).days
        else:
            dias_restantes = None
        
        # Status
        if p.get("estado") == "pagado":
            status_cobranza = "pagado"
        elif p.get("estado") == "pago_reportado":
            status_cobranza = "pago_reportado"
        elif dias_restantes is None:
            status_cobranza = "pendiente"
        elif dias_restantes < 0:
            status_cobranza = "vencido"
        elif dias_restantes <= 3:
            status_cobranza = "por_vencer"
        else:
            status_cobranza = "al_dia"

        if status_cobranza == "pagado":
            dias_restantes = None
        
        tp = total_pagar_desde_pedido(p, hoy=hoy)
        item = {
            "pedido_id": p["id"],
            "numero": p.get("numero", ""),
            "bodega": bodegas_map.get(p.get("bodega_id"), {}),
            "distribuidor": dist_map.get(p.get("distribuidor_id"), {}),
            "monto_financiado": float(p.get("monto_financiado") or 0),
            "fee": float(p.get("fee_monto") or 0),
            "mora_monto": tp["mora_monto"],
            "credito_fijo": tp["credito_fijo"],
            "total_pagar": tp["total_pagar"],
            "plazo_dias": plazo,
            "fecha_entregado": fecha_entregado,
            "fecha_vencimiento": venc.isoformat() if venc else None,
            "dias_restantes": dias_restantes,
            "status_cobranza": status_cobranza,
            "estado": p.get("estado"),
            "fecha_pagado": p.get("fecha_pagado"),
            "fee_regimen": p.get("fee_regimen"),
            "ultimo_recordatorio": recordatorios_map.get(p["id"]),
        }
        
        # Filters
        if distribuidor:
            dl = distribuidor.lower()
            if dl not in (item["distribuidor"].get("nombre_comercial","") or "").lower():
                continue
        if bodega:
            bl = bodega.lower()
            if bl not in (item["bodega"].get("nombre_comercial","") or "").lower():
                continue
        if estado and estado != "todos":
            if estado != status_cobranza:
                continue
        if fecha_desde:
            try:
                if fecha_entregado and datetime.fromisoformat(fecha_entregado.replace("Z","+00:00")).date() < datetime.fromisoformat(fecha_desde).date():
                    continue
            except: pass
        if fecha_hasta:
            try:
                if fecha_entregado and datetime.fromisoformat(fecha_entregado.replace("Z","+00:00")).date() > datetime.fromisoformat(fecha_hasta).date():
                    continue
            except: pass
        
        resultado.append(item)
    
    # Stats por distribuidor
    stats_dist = {}
    for r in resultado:
        dname = r["distribuidor"].get("nombre_comercial", "?") or "?"
        if dname not in stats_dist:
            stats_dist[dname] = {"nombre": dname, "total": 0, "al_dia": 0, "por_vencer": 0, "vencido": 0, "pagado": 0, "pago_reportado": 0, "monto_vencido": 0}
        s = stats_dist[dname]
        s["total"] += 1
        s[r["status_cobranza"]] = s.get(r["status_cobranza"], 0) + 1
        if r["status_cobranza"] == "vencido":
            s["monto_vencido"] += r["total_pagar"]
    
    # Tasa de pago puntual
    for s in stats_dist.values():
        total_vencidos_o_pagados = s.get("pagado", 0) + s.get("vencido", 0)
        if total_vencidos_o_pagados > 0:
            s["tasa_puntual"] = round(100 * s.get("pagado", 0) / total_vencidos_o_pagados, 1)
        else:
            s["tasa_puntual"] = 100
    
    return {"cobranzas": resultado, "total": len(resultado), "stats_distribuidor": list(stats_dist.values())}


@router.get("/admin/cobranzas/reporte-diario")
async def admin_cobranza_reporte_diario(
    x_admin_token: str = Header(None, alias="X-Admin-Token"),
    authorization: str = Header(None, alias="Authorization"),
):
    import hmac
    token = x_admin_token
    if not token and authorization and authorization.startswith("Bearer "):
        token = authorization[7:]
    expected = admin_token_or_raise()
    if not token or not hmac.compare_digest(token.strip(), expected):
        raise HTTPException(status_code=401, detail="Token invalido")
    from starlette.responses import HTMLResponse
    from app.jobs.cobranza_diaria import get_pedidos_vencidos, render_html
    rows = await get_pedidos_vencidos()
    html = render_html(rows)
    return HTMLResponse(content=html)


@router.post("/admin/verificar-pago/{pedido_id}")
async def admin_verificar_pago(pedido_id: str, payload: dict, admin: bool = Depends(verify_admin)):
    """Mark order as paid + restore bodega line."""
    from datetime import datetime
    from app.services.analytics import track_event
    
    rows = _sb_get("pedidos", {"select":"*","id":f"eq.{pedido_id}"})
    if not rows:
        raise HTTPException(status_code=404, detail="Pedido no encontrado")
    ped = rows[0]
    
    # Idempotencia: si el pedido ya esta pagado, no reprocesar.
    # Evita recargar la linea 2x y mandar el mensaje "Pago verificado" duplicado.
    if (ped.get("estado") or "").lower() == "pagado":
        return {"ok": True, "already_paid": True, "pedido": ped.get("numero"),
                "mensaje": "Este pedido ya estaba marcado como pagado."}
    
    monto_financiado = float(ped.get("monto_financiado") or 0)
    bodega_id = ped.get("bodega_id")
    
    # Update pedido
    patch = {
        "estado": "pagado",
        "fecha_pagado": datetime.utcnow().isoformat(),
        "metodo_pago": payload.get("metodo", "yape"),
        "nro_operacion": payload.get("nro_operacion", ""),
    }
    _sb_patch("pedidos", patch, {"id": f"eq.{pedido_id}"})

    # BUG #2 fix: marcar el financiamiento como pagado.
    # Antes este handler nunca tocaba 'financiamientos', asi que un prestamo
    # ya pagado quedaba en estado 'activo' y luego se marcaba como vencido.
    try:
        fins = _sb_get("financiamientos", {
            "select": "id,estado,monto_total",
            "pedido_id": f"eq.{pedido_id}",
        })
        for fin in (fins or []):
            if fin.get("estado") in ("activo", "verificando", "vencido"):
                _sb_patch("financiamientos", {
                    "estado": "pagado",
                    "fecha_pago": datetime.utcnow().isoformat(),
                    "monto_pagado": fin.get("monto_total"),
                    "metodo_pago": payload.get("metodo", "yape"),
                    "updated_at": datetime.utcnow().isoformat(),
                }, {"id": f"eq.{fin['id']}"})
    except Exception as e:
        import logging
        logging.getLogger("circa").error(
            f"No se pudo marcar financiamiento como pagado para pedido {pedido_id}: {e}"
        )

    # Facturacion Circa (simulada) - nunca bloquea la confirmacion de pago
    try:
        from app.services.cobranza import crear_comprobante_circa_simulado
        await crear_comprobante_circa_simulado(ped)
    except Exception as e:
        import logging
        logging.getLogger("circa").error(
            f"Facturacion Circa fallo para pedido {pedido_id}: {e}"
        )

    track_event(
        "payment_made",
        bodega_id=bodega_id,
        pedido_id=pedido_id,
        source="admin",
        metadata={
            "metodo": payload.get("metodo", "yape"),
            "nro_operacion": payload.get("nro_operacion", ""),
            "monto_financiado": monto_financiado,
        },
    )
    
    # Restore bodega line
    if bodega_id and monto_financiado > 0:
        bod = _sb_get("bodegas", {"select":"linea_disponible,linea_aprobada,telefono_whatsapp,nombre_comercial","id":f"eq.{bodega_id}"})
        if bod:
            nueva_linea = float(bod[0].get("linea_disponible") or 0) + monto_financiado
            nueva_linea = min(nueva_linea, bod[0].get('linea_aprobada', nueva_linea))  # Cap
            _sb_patch("bodegas", {"linea_disponible": nueva_linea}, {"id": f"eq.{bodega_id}"})
            
            # Notify bodega
            tel = bod[0].get("telefono_whatsapp", "")
            if tel:
                msg = (
                    f"\u2705 *Pago verificado*\n\n"
                    f"Pedido: *{ped.get('numero','')}*\n"
                    f"Monto: S/{ped.get('total',0)}\n\n"
                    f"\U0001f4b0 Tu linea disponible ahora es: *S/{nueva_linea:.2f}*\n\n"
                    f"Escribe *MENU* para hacer otro pedido."
                )
                _send_wa_text(tel, msg)
    
    return {"ok": True, "pedido": ped.get("numero"), "linea_restaurada": monto_financiado}


@router.get("/admin/export-pagos-distribuidor")
async def admin_export_pagos(
    fecha_desde: Optional[str] = None,
    fecha_hasta: Optional[str] = None,
    test: Optional[str] = None,
    admin: bool = Depends(verify_admin),
):
    """Resumen consolidado de pagos a distribuidores por rango de fechas. Filtra por test/real."""
    params = {"select":"*","estado":"in.(entregado,pagado,despachado,en_camino)","order":"created_at.desc","limit":"1000"}
    pedidos = _sb_get("pedidos", params)
    # NUEVO: filtrar por test/real
    ids_filter = _bodega_ids_por_test(test)
    if ids_filter is not None:
        pedidos = [p for p in pedidos if p.get("bodega_id") in ids_filter]
    
    # Filter by date
    from datetime import datetime
    filtered = []
    for p in pedidos:
        if not p.get("created_at"): continue
        try:
            fp = datetime.fromisoformat(p["created_at"].replace("Z","+00:00")).date()
            if fecha_desde and fp < datetime.fromisoformat(fecha_desde).date(): continue
            if fecha_hasta and fp > datetime.fromisoformat(fecha_hasta).date(): continue
            filtered.append(p)
        except: continue
    
    # Group by distribuidor
    grupos = {}
    for p in filtered:
        did = p.get("distribuidor_id", "")
        if did not in grupos:
            grupos[did] = {"pedidos": [], "total_financiado": 0}
        grupos[did]["pedidos"].append(p)
        grupos[did]["total_financiado"] += float(p.get("monto_financiado") or 0)
    
    # Enrich with distribuidor + bodega info
    for did, g in grupos.items():
        try:
            d = _sb_get("distribuidores", {"select":"*","id":f"eq.{did}"})
            g["distribuidor"] = d[0] if d else {}
        except: g["distribuidor"] = {}
        for p in g["pedidos"]:
            try:
                b = _sb_get("bodegas", {"select":"nombre_comercial,ruc,telefono_whatsapp","id":f"eq.{p.get('bodega_id','')}"})
                p["bodega"] = b[0] if b else {}
            except: p["bodega"] = {}
    
    return {"grupos": list(grupos.values()), "total_pedidos": len(filtered)}

# ============================================================
# NUEVOS ENDPOINTS — Fase 2 Panel Admin (12 mayo 2026)
# ============================================================

@router.get("/admin/alerts/sobregiro")
async def admin_alerts_sobregiro(
    test: Optional[str] = None,
    admin: bool = Depends(verify_admin),
):
    """🟥 Alerta de bodegas con linea_disponible > linea_aprobada (sobregiro / riesgo de compliance)."""
    bodegas = _sb_get("bodegas", {
        "select": "id,razon_social,nombre_comercial,telefono_whatsapp,representante_legal,"
                  "linea_aprobada,linea_disponible,es_test,distribuidor_id",
        "limit": "2000",
    })
    # Filtrar por sobregiro
    sobregiro = []
    for b in bodegas:
        aprobada = float(b.get("linea_aprobada") or 0)
        disponible = float(b.get("linea_disponible") or 0)
        if disponible > aprobada:
            b["sobregiro"] = round(disponible - aprobada, 2)
            b["pct_sobre"] = round((disponible - aprobada) / aprobada * 100, 1) if aprobada > 0 else 0
            sobregiro.append(b)
    # Filtrar por test/real si corresponde
    if test:
        is_test = str(test).lower() in ("test", "true", "prueba", "pruebas", "1")
        sobregiro = [b for b in sobregiro if bool(b.get("es_test")) == is_test]
    # Ordenar por monto de sobregiro descendente
    sobregiro.sort(key=lambda b: b.get("sobregiro", 0), reverse=True)
    return {
        "alertas": sobregiro,
        "total": len(sobregiro),
        "monto_total_sobregiro": round(sum(b.get("sobregiro", 0) for b in sobregiro), 2),
    }


@router.get("/admin/bodegas")
async def admin_list_bodegas(
    test: Optional[str] = None,
    estado: Optional[str] = None,
    search: Optional[str] = None,
    admin: bool = Depends(verify_admin),
):
    """Lista de bodegas con su sesion actual y conteo de pedidos. Optimizada: 3 queries totales."""
    params = {
        "select": "id,razon_social,nombre_comercial,representante_legal,telefono_whatsapp,"
                  "ruc,dni_representante,estado,linea_aprobada,linea_disponible,"
                  "distribuidor_id,created_at,es_test",
        "order": "created_at.desc",
        "limit": "2000",
    }
    if estado:
        params["estado"] = f"eq.{estado}"
    if test:
        is_test_str = "true" if str(test).lower() in ("test", "true", "prueba", "pruebas", "1") else "false"
        params["es_test"] = f"eq.{is_test_str}"
    bodegas = _sb_get("bodegas", params)

    # Filtrar por search (razón social, comercial, teléfono, RUC, DNI, representante)
    if search:
        s = search.lower()
        def _match(b):
            campos = [
                b.get("razon_social"), b.get("nombre_comercial"),
                b.get("telefono_whatsapp"), b.get("ruc"),
                b.get("dni_representante"), b.get("representante_legal"),
            ]
            return any(s in (str(c).lower() if c else "") for c in campos)
        bodegas = [b for b in bodegas if _match(b)]

    if not bodegas:
        return {"bodegas": [], "total": 0}

    # OPTIMIZACIÓN: batch fetch en vez de N+1
    bodega_ids = [b["id"] for b in bodegas if b.get("id")]
    ids_str = ",".join(bodega_ids)

    # Una sola query para TODAS las sesiones
    sesiones_map = {}
    try:
        sesiones = _sb_get("sesiones", {
            "select": "bodega_id,fase,last_activity,expires_at",
            "bodega_id": f"in.({ids_str})",
            "order": "last_activity.desc",
            "limit": "5000",
        })
        # Quedarse con la sesión más reciente por bodega (ya viene ordenado desc)
        for s in sesiones:
            bid = s.get("bodega_id")
            if bid and bid not in sesiones_map:
                sesiones_map[bid] = s
    except Exception:
        pass

    # Una sola query para TODOS los pedidos (solo lo mínimo: id + estado + bodega_id)
    pedidos_map = {}  # {bodega_id: {"count": N, "pagados": M}}
    try:
        pedidos = _sb_get("pedidos", {
            "select": "id,estado,bodega_id",
            "bodega_id": f"in.({ids_str})",
            "limit": "10000",
        })
        for p in pedidos:
            bid = p.get("bodega_id")
            if not bid:
                continue
            if bid not in pedidos_map:
                pedidos_map[bid] = {"count": 0, "pagados": 0}
            pedidos_map[bid]["count"] += 1
            if p.get("estado") == "pagado":
                pedidos_map[bid]["pagados"] += 1
    except Exception:
        pass

    # Merge en memoria (muy rápido)
    for b in bodegas:
        bid = b.get("id")
        b["sesion"] = sesiones_map.get(bid)
        b["pedidos_count"] = pedidos_map.get(bid, {}).get("count", 0)
        b["pedidos_pagados"] = pedidos_map.get(bid, {}).get("pagados", 0)

    return {"bodegas": bodegas, "total": len(bodegas)}


@router.get("/admin/bodega/{bodega_id}")
async def admin_bodega_detalle(
    bodega_id: str,
    admin: bool = Depends(verify_admin),
):
    """Drill-down de una bodega: datos + sesion + timeline de eventos + pedidos."""
    # 1. Datos de la bodega
    rows = _sb_get("bodegas", {"select": "*", "id": f"eq.{bodega_id}"})
    if not rows:
        raise HTTPException(status_code=404, detail="Bodega no encontrada")
    bodega = rows[0]

    # 2. Sesión actual
    try:
        ses = _sb_get("sesiones", {
            "select": "*",
            "bodega_id": f"eq.{bodega_id}",
            "order": "last_activity.desc",
            "limit": "1",
        })
        bodega["sesion"] = ses[0] if ses else None
    except Exception:
        bodega["sesion"] = None

    # 3. Timeline de eventos (últimos 50)
    try:
        eventos = _sb_get("events", {
            "select": "*",
            "bodega_id": f"eq.{bodega_id}",
            "order": "created_at.desc",
            "limit": "50",
        })
    except Exception:
        eventos = []

    # 4. Pedidos de la bodega
    try:
        pedidos = _sb_get("pedidos", {
            "select": "id,numero,estado,origen,monto_productos,monto_financiado,"
                      "monto_contado,total_pedido,fee_monto,created_at,pagado_at,"
                      "fecha_vencimiento,metodo_pago,dimax_pedido_id",
            "bodega_id": f"eq.{bodega_id}",
            "order": "created_at.desc",
            "limit": "100",
        })
    except Exception:
        pedidos = []

    # 5. Distribuidor de la bodega
    distribuidor = {}
    if bodega.get("distribuidor_id"):
        try:
            d = _sb_get("distribuidores", {"select": "*", "id": f"eq.{bodega['distribuidor_id']}"})
            if d: distribuidor = d[0]
        except Exception:
            pass

    # 6. Cartera comercial activa (vendedor de campo + supervisor DIMAX)
    cartera_comercial = {}
    try:
        bv_rows = _sb_get("bodega_vendedores", {
            "select": "supervisor,dia_visita,dia_entrega,grupo,vendedores(codigo,nombre)",
            "bodega_id": f"eq.{bodega_id}",
            "activo": "eq.true",
            "order": "created_at.desc",
            "limit": "1",
        })
        if bv_rows:
            row = bv_rows[0]
            vend = row.get("vendedores") or {}
            if isinstance(vend, list):
                vend = vend[0] if vend else {}
            cartera_comercial = {
                "vendedor_codigo": vend.get("codigo"),
                "vendedor_nombre": vend.get("nombre"),
                "supervisor": row.get("supervisor"),
                "dia_visita": row.get("dia_visita"),
                "dia_entrega": row.get("dia_entrega"),
                "grupo": row.get("grupo"),
            }
    except Exception:
        pass

    return {
        "bodega": bodega,
        "distribuidor": distribuidor,
        "cartera_comercial": cartera_comercial,
        "eventos": eventos,
        "pedidos": pedidos,
        "stats": {
            "total_pedidos": len(pedidos),
            "pedidos_pagados": sum(1 for p in pedidos if p.get("estado") == "pagado"),
            "pedidos_preventa_cancelada": sum(1 for p in pedidos if p.get("estado") == "preventa_cancelada"),
            "monto_financiado_pendiente": round(sum(
                float(p.get("monto_financiado") or 0)
                for p in pedidos
                if p.get("estado") not in ("pagado", "preventa_cancelada", "rechazado")
            ), 2),
        }
    }


@router.post("/admin/bodega/{bodega_id}/pin/reset")
async def admin_reset_pin(
    bodega_id: str,
    payload: AdminPinAction,
    admin: bool = Depends(verify_admin),
):
    """Resetea PIN: bodeguero crea clave nueva vía Flow/web. Requiere comentario y re-autorización."""
    from app.services import db
    from app.services.analytics import track_event
    from app.services.twilio_client import send_whatsapp

    _verify_admin_action(payload.autorizacion)
    comentario = payload.comentario.strip()

    rows = _sb_get("bodegas", {"select": "id,telefono_whatsapp,nombre_comercial", "id": f"eq.{bodega_id}"})
    if not rows:
        raise HTTPException(status_code=404, detail="Bodega no encontrada")
    bodega = rows[0]
    tel = bodega.get("telefono_whatsapp") or ""
    if not tel:
        raise HTTPException(status_code=400, detail="Bodega sin teléfono WhatsApp")

    db.update_bodega(bodega_id, {
        "pin_hash": None,
        "pin_intentos": 0,
        "pin_bloqueado_hasta": None,
    })
    db.upsert_session(
        tel,
        "reg_pin",
        {"bodega_id": bodega_id, "ruc": "reset", "is_reset": True},
        bodega_id,
    )

    track_event(
        "pin_reset_admin",
        bodega_id=bodega_id,
        telefono=tel,
        source="admin",
        channel="web",
        metadata={"comentario": comentario, "accion": "reset"},
    )

    wa_msg = (
        "🔐 *Soporte Circa* reseteó tu clave.\n\n"
        "Crea una clave nueva de 4 dígitos aquí:\n"
        f"👉 {_pin_url(bodega_id, 'create')}"
    )
    try:
        send_whatsapp(tel, wa_msg)
    except Exception:
        pass

    return {"ok": True, "mensaje": "Clave reseteada. Se envió link al bodeguero por WhatsApp."}


@router.post("/admin/bodega/{bodega_id}/pin/set")
async def admin_set_pin(
    bodega_id: str,
    payload: AdminPinSet,
    admin: bool = Depends(verify_admin),
):
    """Asigna PIN desde soporte (hash en BD). Requiere comentario y re-autorización."""
    from app.services import db
    from app.services.analytics import track_event
    from app.services.pin import hash_pin, validate_pin_format
    from app.services.twilio_client import send_whatsapp

    _verify_admin_action(payload.autorizacion)
    comentario = payload.comentario.strip()

    if payload.pin != payload.pin_confirm:
        raise HTTPException(status_code=400, detail="Las claves no coinciden")

    valid, error_msg = validate_pin_format(payload.pin)
    if not valid:
        raise HTTPException(status_code=400, detail=error_msg)

    rows = _sb_get("bodegas", {"select": "id,telefono_whatsapp", "id": f"eq.{bodega_id}"})
    if not rows:
        raise HTTPException(status_code=404, detail="Bodega no encontrada")
    bodega = rows[0]
    tel = bodega.get("telefono_whatsapp") or ""

    pin_hashed = hash_pin(payload.pin)
    db.update_bodega(bodega_id, {
        "estado": "activo",
        "pin_hash": pin_hashed,
        "pin_intentos": 0,
        "pin_bloqueado_hasta": None,
    })

    if tel:
        db.upsert_session(tel, "menu", {}, bodega_id)

    track_event(
        "pin_set_admin",
        bodega_id=bodega_id,
        telefono=tel or None,
        source="admin",
        channel="web",
        metadata={"comentario": comentario, "accion": "set"},
    )

    if tel:
        try:
            send_whatsapp(
                tel,
                "🔐 *Soporte Circa* actualizó tu clave Circa.\n\n"
                "Si no la recuerdas, escríbenos por este chat.\n\n"
                "Escribe *MENU* para continuar.",
            )
        except Exception:
            pass

    return {"ok": True, "mensaje": "Clave asignada. Comunícala al bodeguero por un canal seguro (teléfono)."}


# ============================================================
# Endpoint: Importar preventas desde DIMAX (Sprint 28-abr-2026)
# Modelo: origen='preventa_dimax', estado='preventa_confirmada'
# Ver memo Circa_Memo_Jeff_Modelo_Preventa_28abr.docx
# ============================================================

class PreventaItemIn(BaseModel):
    sku_distribuidor: str
    descripcion: Optional[str] = None
    cantidad: int
    unidad: Optional[str] = "UND x 1"
    precio_unitario: float
    subtotal: Optional[float] = None


class PreventaIn(BaseModel):
    ruc_bodega: str
    razon_social: Optional[str] = None
    nombre_comercial: Optional[str] = None
    telefono_whatsapp: Optional[str] = None
    direccion: Optional[str] = None
    distrito: Optional[str] = None
    provincia: Optional[str] = None
    dni_representante: Optional[str] = None
    representante_legal: Optional[str] = None
    vendedor_codigo: Optional[str] = None
    vendedor_nombre: Optional[str] = None
    dimax_pedido_id: Optional[str] = None
    fecha_visita: Optional[str] = None  # ISO date "YYYY-MM-DD"
    fecha_entrega: Optional[str] = None
    total_pedido: float
    descuento_prorrateado: Optional[float] = 0
    items: List[PreventaItemIn]


class PreventasImportRequest(BaseModel):
    preventas: List[PreventaIn]


def _normalizar_telefono(tel: Optional[str]) -> Optional[str]:
    """Normaliza un teléfono peruano al formato +51XXXXXXXXX."""
    if not tel:
        return None
    t = "".join(c for c in str(tel) if c.isdigit() or c == "+")
    if t.startswith("+51"):
        return t
    if t.startswith("51") and len(t) == 11:
        return "+" + t
    if len(t) == 9:
        return "+51" + t
    return t  # No reconocido, devolvemos tal cual


def _resolver_o_crear_vendedor(codigo: Optional[str], nombre: Optional[str], distribuidor_id: str) -> Optional[str]:
    """
    Busca vendedor por (distribuidor_id, codigo). Si no existe, lo crea.
    Devuelve vendedor_id o None si codigo viene vacío.
    """
    if not codigo:
        return None
    
    rows = _sb_get("vendedores", {
        "select": "id",
        "distribuidor_id": f"eq.{distribuidor_id}",
        "codigo": f"eq.{codigo}",
    })
    if rows:
        return rows[0]["id"]
    
    # No existe → crear
    payload = {
        "distribuidor_id": distribuidor_id,
        "codigo": codigo,
        "nombre": nombre or codigo,  # Si no hay nombre, usar el código como placeholder
        "activo": True,
    }
    r = httpx.post(
        f"{SUPABASE_URL}/rest/v1/vendedores",
        headers=_sb_headers(),
        json=payload,
        timeout=15
    )
    r.raise_for_status()
    nuevo = r.json()
    return nuevo[0]["id"] if isinstance(nuevo, list) else nuevo["id"]


@router.post("/preventas/import")
async def importar_preventas(
    request: PreventasImportRequest,
    dist: dict = Depends(verify_distribuidor)
):
    """
    Recibe un batch de preventas desde el ERP del distribuidor (DIMAX).
    
    Cada preventa es independiente: si una falla, las demás siguen procesándose.
    
    Crea pedidos en estado='preventa_confirmada', origen='preventa_dimax'.
    Si la bodega no existe, la crea en estado='inactivo' con linea_disponible=0.
    Si el vendedor no existe, lo crea con nombre stub (Ops puede actualizar después).
    
    Returns: dict con resumen de creadas, errores e items_no_match.
    """
    from app.services import db
    import logging
    logger = logging.getLogger("circa.preventa_import")
    
    distribuidor_id = dist["id"]
    creadas = 0
    errores = []
    preventas_creadas = []
    
    for pv in request.preventas:
        try:
            # 1. Resolver vendedor (lookup o crear)
            vendedor_id = _resolver_o_crear_vendedor(
                pv.vendedor_codigo,
                pv.vendedor_nombre,
                distribuidor_id
            )
            
            # 2. Sanity: validar que tenga items
            if not pv.items:
                errores.append({
                    "ruc": pv.ruc_bodega,
                    "error": "preventa sin items"
                })
                continue
            
            # 3. Upsert bodega
            tel_norm = _normalizar_telefono(pv.telefono_whatsapp)
            datos_bodega = {
                "razon_social": pv.razon_social,
                "nombre_comercial": pv.nombre_comercial,
                "telefono_whatsapp": tel_norm,
                "direccion_fiscal": pv.direccion,
                "direccion_despacho": pv.direccion,
                "distrito": pv.distrito,
                "provincia": pv.provincia,
                "dni_representante": pv.dni_representante,
                "representante_legal": pv.representante_legal,
            }
            bodega, bodega_creada = db.upsert_bodega_para_preventa(
                pv.ruc_bodega,
                distribuidor_id,
                **datos_bodega
            )
            
            # 4. Crear pedido preventa
            items_dimax = [
                {
                    "sku_distribuidor": str(it.sku_distribuidor),
                    "descripcion": it.descripcion,
                    "cantidad": it.cantidad,
                    "unidad": it.unidad,
                    "precio_unitario": it.precio_unitario,
                    "subtotal": it.subtotal if it.subtotal is not None else (it.cantidad * it.precio_unitario),
                }
                for it in pv.items
            ]
            
            resultado = db.crear_pedido_preventa(
                bodega_id=bodega["id"],
                distribuidor_id=distribuidor_id,
                items_dimax=items_dimax,
                total_pedido=pv.total_pedido,
                descuento_prorrateado=pv.descuento_prorrateado or 0,
                vendedor_id=vendedor_id,
                dimax_pedido_id=pv.dimax_pedido_id,
                fecha_visita=pv.fecha_visita,
                fecha_entrega=pv.fecha_entrega,
            )
            
            preventas_creadas.append({
                "ruc": pv.ruc_bodega,
                "pedido_id": resultado["pedido_id"],
                "bodega_creada": bodega_creada,
                "items_creados": resultado["items_creados"],
                "items_no_match": resultado["items_no_match"],
            })
            creadas += 1
            
        except Exception as e:
            logger.error(f"Error procesando preventa RUC {pv.ruc_bodega}: {e}", exc_info=True)
            errores.append({
                "ruc": pv.ruc_bodega,
                "error": str(e)
            })
    
    return {
        "ok": len(errores) == 0,
        "creadas": creadas,
        "errores": errores,
        "preventas": preventas_creadas,
    }

