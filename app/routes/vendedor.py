"""
Vendedor App — Preventa Presencial (Circa)
==========================================
Endpoints para que vendedores DIMAX armen pedidos en bodega
usando su URL personal con access_token.

URLs:
  GET  /v/{token}                     -> menu principal del vendedor
  GET  /v/{token}/preventa            -> pantalla buscar bodega por DNI/RUC
  GET  /v/{token}/api/buscar-bodega   -> API de busqueda (JSON)
  ... (mas endpoints proximamente: catalogo, pedido confirmado)
"""
from fastapi import APIRouter, HTTPException, Path, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi import UploadFile, File, Request, Form
from datetime import datetime, timezone
import os, re, httpx, logging

from app.services.vendedor_wa import _bodega_identificacion
from app.services.identity import consultar_dni, validate_dni_format
from app.services.db import sb

router = APIRouter(prefix="/v", tags=["vendedor"])
logger = logging.getLogger("circa")

SUPABASE_URL = os.getenv("SUPABASE_URL", "https://rhxqcoijzgqlecpdfhde.supabase.co")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_KEY", os.getenv("SUPABASE_KEY", ""))


# ==========================================================
# HELPERS DE SUPABASE
# ==========================================================

def _sb_headers():
    return {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }


def _sb_get(path, params=None):
    r = httpx.get(f"{SUPABASE_URL}/rest/v1/{path}", headers=_sb_headers(),
                  params=params or {}, timeout=15)
    if r.status_code >= 400:
        logger.error(f"Supabase error {r.status_code}: {r.text}")
        r.raise_for_status()
    return r.json()


def _sb_patch(path, data, params=None):
    r = httpx.patch(f"{SUPABASE_URL}/rest/v1/{path}", headers=_sb_headers(),
                    json=data, params=params or {}, timeout=15)
    r.raise_for_status()
    return r.json()


# ==========================================================
# AUTH / VENDEDOR
# ==========================================================

def _get_vendedor_by_token(token: str):
    """Levanta vendedor activo por access_token. Retorna dict o None."""
    if not token or len(token) < 16:
        return None
    rows = _sb_get("vendedores", {
        "select": "id,codigo,nombre,distribuidor_id,activo,es_admin",
        "access_token": f"eq.{token}",
        "activo": "eq.true",
        "limit": "1",
    })
    return rows[0] if rows else None


def _registrar_acceso(vendedor_id: str):
    """Best-effort: actualiza ultimo_acceso. No bloquea si falla."""
    try:
        _sb_patch("vendedores",
                  {"ultimo_acceso": datetime.now(timezone.utc).isoformat()},
                  {"id": f"eq.{vendedor_id}"})
    except Exception as e:
        logger.warning(f"No se pudo registrar ultimo_acceso para {vendedor_id}: {e}")


def _primer_nombre(nombre_completo: str) -> str:
    """Extrae primer nombre de formato peruano (APE PAT, APE MAT, NOM1 NOM2...)."""
    tokens = nombre_completo.strip().split()
    if len(tokens) >= 3:
        return tokens[2].capitalize()
    return tokens[-1].capitalize() if tokens else "Vendedor"


# ==========================================================
# CSS BASE (compartido entre pantallas)
# ==========================================================

CSS_BASE = """
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:'Poppins',-apple-system,sans-serif;background:#0A0E1A;color:#fff;min-height:100vh;padding:32px 22px;-webkit-tap-highlight-color:transparent}
.logo{font-size:26px;font-weight:700;letter-spacing:-0.5px}
.logo span{color:#2563EB}
.back{display:inline-flex;align-items:center;gap:6px;color:rgba(255,255,255,0.6);text-decoration:none;font-size:13px;margin-bottom:20px;margin-top:-8px}
.back:active{color:#fff}
.titulo{font-size:24px;font-weight:600;margin-top:8px;line-height:1.2}
.subtitulo{font-size:13px;color:rgba(255,255,255,0.5);margin-top:8px;letter-spacing:0.3px}
.input-group{margin-top:32px}
.label{font-size:11px;color:rgba(255,255,255,0.5);margin-bottom:10px;display:block;letter-spacing:0.6px;font-weight:500}
.input{width:100%;padding:18px 20px;background:rgba(255,255,255,0.05);border:1px solid rgba(255,255,255,0.1);border-radius:14px;color:#fff;font-family:inherit;font-size:18px;font-weight:500;letter-spacing:1px;outline:none;transition:border-color 0.15s ease}
.input:focus{border-color:#2563EB;background:rgba(37,99,235,0.06)}
.btn{display:block;width:100%;padding:18px 22px;background:#2563EB;border:none;border-radius:14px;color:#fff;font-family:inherit;font-size:16px;font-weight:600;text-align:center;text-decoration:none;margin-top:14px;cursor:pointer;transition:transform 0.1s ease}
.btn:active{transform:scale(0.98)}
.btn:disabled{background:rgba(37,99,235,0.3);cursor:wait}
.btn.secondary{background:rgba(255,255,255,0.05);border:1px solid rgba(255,255,255,0.1)}
.result{margin-top:28px}
.card{background:rgba(255,255,255,0.05);border:1px solid rgba(255,255,255,0.1);border-radius:14px;padding:20px 22px;margin-bottom:14px}
.card .nombre{font-size:17px;font-weight:600;line-height:1.3}
.card .meta{font-size:12px;color:rgba(255,255,255,0.5);margin-top:6px;line-height:1.5}
.card .linea{margin-top:14px;padding-top:14px;border-top:1px solid rgba(255,255,255,0.08);display:flex;justify-content:space-between;align-items:baseline}
.card .linea .lbl{font-size:11px;color:rgba(255,255,255,0.5);letter-spacing:0.5px;text-transform:uppercase}
.card .linea .val{font-size:18px;font-weight:600;color:#22D3EE}
.error{background:rgba(239,68,68,0.1);border:1px solid rgba(239,68,68,0.2);color:#fca5a5;padding:14px 18px;border-radius:12px;font-size:13px;line-height:1.5}
.warning{background:rgba(245,158,11,0.1);border:1px solid rgba(245,158,11,0.2);color:#fcd34d;padding:14px 18px;border-radius:12px;font-size:13px;line-height:1.5;margin-bottom:12px}
"""


# ==========================================================
# ENDPOINT 1: MENU PRINCIPAL  GET /v/{token}
# ==========================================================

@router.get("/{token}", response_class=HTMLResponse)
def vendedor_home(token: str = Path(..., min_length=16, max_length=64)):
    """Entry point del vendedor. Valida token y muestra menu."""
    vendedor = _get_vendedor_by_token(token)
    if not vendedor:
        raise HTTPException(status_code=404, detail="Acceso no encontrado")

    _registrar_acceso(vendedor["id"])

    primer_nombre = _primer_nombre(vendedor["nombre"])
    codigo = vendedor["codigo"]
    es_admin = bool(vendedor.get("es_admin"))

    badge_admin = (
        '<div style="background:#2563EB;color:white;font-size:11px;'
        'padding:4px 10px;border-radius:12px;display:inline-block;'
        'margin-top:10px;font-weight:500;letter-spacing:0.5px;">ADMIN CIRCA</div>'
        if es_admin else ''
    )

    html = f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1.0,maximum-scale=1.0,user-scalable=no">
  <title>Circa · {primer_nombre}</title>
  <link href="https://fonts.googleapis.com/css2?family=Poppins:wght@400;500;600;700&display=swap" rel="stylesheet">
  <style>
    {CSS_BASE}
    .saludo{{margin-top:36px;font-size:13px;color:rgba(255,255,255,0.5);letter-spacing:0.3px}}
    .nombre{{margin-top:4px;font-size:24px;font-weight:600}}
    .codigo{{margin-top:6px;font-size:12px;color:rgba(255,255,255,0.4);letter-spacing:0.5px}}
    .menu{{margin-top:48px}}
    .menu-btn{{display:block;width:100%;padding:20px 22px;background:#2563EB;border:none;border-radius:14px;color:#fff;font-family:inherit;font-size:16px;font-weight:600;text-align:left;text-decoration:none;margin-bottom:14px;cursor:pointer}}
    .menu-btn.secondary{{background:rgba(255,255,255,0.05);border:1px solid rgba(255,255,255,0.1)}}
    .menu-btn .desc{{display:block;font-size:12px;font-weight:400;color:rgba(255,255,255,0.7);margin-top:4px}}
    .footer{{position:fixed;bottom:24px;left:0;right:0;text-align:center;font-size:11px;color:rgba(255,255,255,0.3)}}
  </style>
</head>
<body>
  <div class="logo">circa<span>.</span></div>
  <div class="saludo">Hola,</div>
  <div class="nombre">{primer_nombre}</div>
  <div class="codigo">Código {codigo}</div>
  {badge_admin}

  <div class="menu">
    <a href="/v/{token}/preventa/subir" class="menu-btn">
      Subir preventa
      <span class="desc">Sube el Excel de ZOOM y confirma la bodega</span>
    </a>
    <a href="/v/{token}/preventa" class="menu-btn">
      Hacer preventa
      <span class="desc">Arma un pedido para tu cliente</span>
    </a>
    <a href="/v/{token}/afiliar" class="menu-btn">
      Afiliar bodega
      <span class="desc">[COPY: precarga los datos de una bodega nueva]</span>
    </a>
    <a href="/v/{token}/mis-pedidos" class="menu-btn secondary">
      Mis preventas
      <span class="desc">Ve el estado de tus pedidos</span>
    </a>
  </div>

  <div class="footer">Circa · Pali SAC</div>
</body>
</html>"""

    return HTMLResponse(content=html)


# ==========================================================
# ENDPOINT 2: PANTALLA BUSCAR BODEGA  GET /v/{token}/preventa
# ==========================================================

@router.get("/{token}/preventa", response_class=HTMLResponse)
def preventa_buscar(token: str = Path(..., min_length=16, max_length=64)):
    """Pantalla donde el vendedor escribe DNI o RUC de la bodega."""
    vendedor = _get_vendedor_by_token(token)
    if not vendedor:
        raise HTTPException(status_code=404, detail="Acceso no encontrado")

    html = f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1.0,maximum-scale=1.0,user-scalable=no">
  <title>Hacer preventa · Circa</title>
  <link href="https://fonts.googleapis.com/css2?family=Poppins:wght@400;500;600;700&display=swap" rel="stylesheet">
  <style>{CSS_BASE}</style>
</head>
<body>
  <a href="/v/{token}" class="back">← Volver</a>
  <div class="titulo">Hacer preventa</div>
  <div class="subtitulo">Identificá la bodega del cliente</div>

  <div class="input-group">
    <label class="label">DNI O RUC DEL CLIENTE</label>
    <input id="q" class="input" type="tel" inputmode="numeric"
           placeholder="Ej: 12345678" maxlength="11" autocomplete="off">
    <button id="buscar" class="btn">Buscar bodega</button>
  </div>

  <div id="result" class="result"></div>

  <script>
    const TOKEN = "{token}";
    const inp = document.getElementById('q');
    const btn = document.getElementById('buscar');
    const out = document.getElementById('result');

    inp.focus();

    inp.addEventListener('input', (e) => {{
      e.target.value = e.target.value.replace(/\\D/g, '').slice(0, 11);
    }});

    inp.addEventListener('keypress', (e) => {{
      if (e.key === 'Enter') buscar();
    }});

    btn.addEventListener('click', buscar);

    async function buscar() {{
      const q = inp.value.trim();
      if (q.length !== 8 && q.length !== 11) {{
        out.innerHTML = '<div class="error">Ingresá un DNI (8 dígitos) o un RUC (11 dígitos)</div>';
        return;
      }}

      btn.disabled = true;
      btn.textContent = 'Buscando...';
      out.innerHTML = '';

      try {{
        const r = await fetch(`/v/${{TOKEN}}/api/buscar-bodega?q=${{q}}`);
        const data = await r.json();

        if (!data.found) {{
          out.innerHTML = `<div class="error">${{data.error || 'No encontramos esa bodega'}}</div>`;
          return;
        }}

        const b = data.bodega;
        const nombre = b.nombre_comercial || b.razon_social;
        const meta = [b.identificacion, b.distrito].filter(Boolean).join(' · ');
        const lineaFmt = `S/ ${{b.linea_disponible.toFixed(2)}}`;
        const continuarHref = `/v/${{TOKEN}}/catalogo/${{b.id}}`;

        let warningHtml = '';
        if (data.warning) {{
          warningHtml = `<div class="warning">${{data.warning}}</div>`;
        }}

        out.innerHTML = `
          ${{warningHtml}}
          <div class="card">
            <div class="nombre">${{nombre}}</div>
            <div class="meta">${{meta}}</div>
            <div class="linea">
              <span class="lbl">Línea disponible</span>
              <span class="val">${{lineaFmt}}</span>
            </div>
          </div>
          <a href="${{continuarHref}}" class="btn">Es esta, continuar</a>
          <button class="btn secondary" onclick="reiniciar()">No, buscar otra</button>
        `;
      }} catch (err) {{
        out.innerHTML = '<div class="error">Hubo un error. Reintentá.</div>';
        console.error(err);
      }} finally {{
        btn.disabled = false;
        btn.textContent = 'Buscar bodega';
      }}
    }}

    function reiniciar() {{
      inp.value = '';
      out.innerHTML = '';
      inp.focus();
    }}
  </script>
</body>
</html>"""

    return HTMLResponse(content=html)


# ==========================================================
# ENDPOINT 3: API JSON BUSQUEDA BODEGA  GET /v/{token}/api/buscar-bodega
# ==========================================================

@router.get("/{token}/api/buscar-bodega")
def api_buscar_bodega(
    token: str = Path(..., min_length=16, max_length=64),
    q: str = Query(..., min_length=8, max_length=11),
):
    """Busca bodega por DNI del representante o RUC del comercio.
    Aplica filtro de cartera (bodega_vendedores) excepto si es_admin."""
    vendedor = _get_vendedor_by_token(token)
    if not vendedor:
        raise HTTPException(status_code=404, detail="Acceso no encontrado")

    # Solo digitos
    q_clean = ''.join(c for c in q if c.isdigit())
    if len(q_clean) not in (8, 11):
        return {"found": False, "error": "Ingresá un DNI (8 dígitos) o RUC (11 dígitos)"}

    select_fields = (
        "id,razon_social,nombre_comercial,distrito,ruc,dni_representante,"
        "linea_aprobada,linea_disponible,distribuidor_id,solo_dni_sin_ruc,estado"
    )

    if len(q_clean) == 8:
        rows = _sb_get("bodegas", {
            "select": select_fields,
            "dni_representante": f"eq.{q_clean}",
            "limit": "1",
        })
    else:  # 11 digitos = RUC
        rows = _sb_get("bodegas", {
            "select": select_fields,
            "ruc": f"eq.{q_clean}",
            "limit": "1",
        })

    if not rows:
        tipo = "DNI" if len(q_clean) == 8 else "RUC"
        hint = ""
        if len(q_clean) == 11:
            hint = " Si la bodega se registró solo con DNI, prueba con el DNI del representante."
        return {"found": False, "error": f"No encontramos una bodega con ese {tipo}{hint}"}

    bodega = rows[0]

    # Validar cartera (solo para vendedores no-admin)
    if not vendedor.get("es_admin"):
        cartera = _sb_get("bodega_vendedores", {
            "select": "id",
            "vendedor_id": f"eq.{vendedor['id']}",
            "bodega_id": f"eq.{bodega['id']}",
            "activo": "eq.true",
            "limit": "1",
        })
        if not cartera:
            return {"found": False, "error": "Esta bodega no está en tu cartera"}

    # Validar estado de la bodega
    estado = (bodega.get("estado") or "").lower()
    if estado in ("rechazada", "suspendida", "bloqueada"):
        return {"found": False, "error": f"Esta bodega está {estado}, no puede recibir preventas"}

    # Validar linea
    linea = float(bodega.get("linea_disponible") or 0)

    response = {
        "found": True,
        "bodega": {
            "id": bodega["id"],
            "razon_social": bodega["razon_social"],
            "nombre_comercial": bodega.get("nombre_comercial"),
            "distrito": bodega.get("distrito"),
            "linea_disponible": linea,
            "ruc": bodega.get("ruc"),
            "dni_representante": bodega.get("dni_representante"),
            "identificacion": _bodega_identificacion(bodega),
            "solo_dni_sin_ruc": bool(bodega.get("solo_dni_sin_ruc")),
        },
    }

    if linea <= 0:
        response["warning"] = "Esta bodega no tiene línea disponible ahora mismo"

    return response


# ==========================================================
# ENDPOINT 4: REDIRECT AL CATALOGO  GET /v/{token}/catalogo/{bodega_id}
# ==========================================================

@router.get("/{token}/catalogo/{bodega_id}")
def vendedor_catalogo_redirect(
    token: str = Path(..., min_length=16, max_length=64),
    bodega_id: str = Path(...),
):
    """Valida token + bodega-en-cartera, redirige al catalogo web con params modo vendedor."""
    vendedor = _get_vendedor_by_token(token)
    if not vendedor:
        raise HTTPException(status_code=404, detail="Acceso no encontrado")

    # Validar que la bodega exista
    bodega_rows = _sb_get("bodegas", {
        "select": "id,estado",
        "id": f"eq.{bodega_id}",
        "limit": "1",
    })
    if not bodega_rows:
        raise HTTPException(status_code=404, detail="Bodega no encontrada")

    # Validar cartera (excepto admin)
    if not vendedor.get("es_admin"):
        cartera = _sb_get("bodega_vendedores", {
            "select": "id",
            "vendedor_id": f"eq.{vendedor['id']}",
            "bodega_id": f"eq.{bodega_id}",
            "activo": "eq.true",
            "limit": "1",
        })
        if not cartera:
            raise HTTPException(status_code=403, detail="Esta bodega no esta en tu cartera")

    # Redirect al catalogo web con params: bodega_id, modo preventa, token vendedor
    redirect_url = f"/static/catalogo_v2.html?b={bodega_id}&t=preventa&vt={token}"
    return RedirectResponse(url=redirect_url, status_code=302)


# ==========================================================
# ENDPOINT 5: QR + LINK PARA COMPARTIR  GET /v/{token}/preventa/{link_token}/share
# ==========================================================

# Numero de WhatsApp de Circa (donde el bodeguero abre el chat con su pedido)
CIRCA_WA_NUMBER = os.getenv("CIRCA_WA_NUMBER", "51986311567")


@router.get("/{token}/preventa/{link_token}/share", response_class=HTMLResponse)
def vendedor_share_link(
    token: str = Path(..., min_length=16, max_length=64),
    link_token: str = Path(..., min_length=8, max_length=16),
):
    """Pantalla final del vendedor: QR + link wa.me para pasar al bodeguero."""
    vendedor = _get_vendedor_by_token(token)
    if not vendedor:
        raise HTTPException(status_code=404, detail="Acceso no encontrado")

    # Validar que el pedido existe, esta en preventa_confirmada, y pertenece a este vendedor
    pedidos = _sb_get("pedidos", {
        "select": "id,vendedor_id,estado,bodega_id,total_pedido,link_token",
        "link_token": f"eq.{link_token}",
        "limit": "1",
    })
    if not pedidos:
        raise HTTPException(status_code=404, detail="Preventa no encontrada")
    pedido = pedidos[0]

    # Solo el vendedor que creo el pedido (o un admin) puede ver el link
    if pedido.get("vendedor_id") != vendedor["id"] and not vendedor.get("es_admin"):
        raise HTTPException(status_code=403, detail="Esta preventa no es tuya")

    # Levantar datos de la bodega para mostrar nombre
    bodega_rows = _sb_get("bodegas", {
        "select": "razon_social,nombre_comercial",
        "id": f"eq.{pedido['bodega_id']}",
        "limit": "1",
    })
    bodega_nombre = ""
    if bodega_rows:
        b = bodega_rows[0]
        bodega_nombre = b.get("nombre_comercial") or b.get("razon_social") or ""

    total = float(pedido.get("total_pedido") or 0)
    wa_link = f"https://wa.me/{CIRCA_WA_NUMBER}?text=Pedido%20{link_token}"
    from urllib.parse import quote as _q
    _share_msg = f"Hola te paso el link para aprobar tu pedido Circa: {wa_link}"
    share_link = f"https://wa.me/?text={_q(_share_msg, safe='')}"

    html = f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1.0,maximum-scale=1.0,user-scalable=no">
  <title>Compartir preventa · Circa</title>
  <link href="https://fonts.googleapis.com/css2?family=Poppins:wght@400;500;600;700&display=swap" rel="stylesheet">
  <script src="https://cdn.jsdelivr.net/npm/qrcodejs@1.0.0/qrcode.min.js"></script>
  <style>
    {CSS_BASE}
    .preventa-meta{{background:rgba(34,211,238,0.08);border:1px solid rgba(34,211,238,0.2);border-radius:14px;padding:16px 18px;margin-top:24px}}
    .preventa-meta .bodega{{font-size:15px;font-weight:600;color:#fff}}
    .preventa-meta .total{{font-size:22px;font-weight:700;color:#22D3EE;margin-top:6px}}
    .preventa-meta .codigo{{font-size:11px;color:rgba(255,255,255,0.4);margin-top:6px;letter-spacing:0.5px;font-family:monospace}}
    .btn-copy-big{{width:100%;margin-top:20px;padding:18px 22px;background:#22D3EE;color:#0A0E1A;border:none;border-radius:14px;font-family:inherit;font-size:16px;font-weight:700;cursor:pointer;display:flex;align-items:center;justify-content:center;gap:10px;transition:transform 0.1s ease;letter-spacing:0.2px}}
    .btn-copy-big:active{{transform:scale(0.98)}}
    .btn-copy-big.ok{{background:#10b981;color:#fff}}
    .btn-copy-big .ico{{font-size:20px}}
    .qr-wrap{{display:flex;justify-content:center;margin-top:20px;background:#fff;padding:18px;border-radius:14px}}
    .qr-wrap img,.qr-wrap canvas{{display:block;max-width:200px;height:auto}}
    .link-text-small{{margin-top:12px;font-family:monospace;font-size:10px;color:rgba(255,255,255,0.35);word-break:break-all;text-align:center;line-height:1.5;padding:0 10px}}
    .help{{margin-top:24px;font-size:12px;color:rgba(255,255,255,0.5);line-height:1.6;text-align:center}}
    .btns-final{{margin-top:24px;display:flex;gap:10px;padding-bottom:24px}}
    .btns-final .btn{{margin-top:0}}
  </style>
</head>
<body>
  <a href="/v/{token}" class="back">← Menú</a>
  <div class="titulo">Preventa lista</div>
  <div class="subtitulo">✅ Se envió por WhatsApp al bodeguero</div>

  <div class="preventa-meta">
    <div class="bodega">{bodega_nombre}</div>
    <div class="total">S/ {total:.2f}</div>
    <div class="codigo">Código {link_token}</div>
  </div>

  <button class="btn-copy-big" id="btnCopy" onclick="copiarLink()">
    <span class="ico">📋</span>
    <span id="btnCopyText">Copiar link para enviar</span>
  </button>

  <div class="qr-wrap"><div id="qr"></div></div>
  <div class="link-text-small" id="link-text">{wa_link}</div>

  <div class="help">
    El bodeguero ya recibió las opciones de pago por WhatsApp.<br>Si no le llegó, comparte el link de abajo.
  </div>

  <div class="btns-final">
    <a href="/v/{token}/preventa" class="btn secondary">Nueva preventa</a>
    <a href="{share_link}" target="_blank" class="btn">Compartir</a>
  </div>

  <script>
    // Genera el QR del wa.me link
    new QRCode(document.getElementById("qr"), {{
      text: "{wa_link}",
      width: 200,
      height: 200,
      colorDark: "#0A0E1A",
      colorLight: "#ffffff",
      correctLevel: QRCode.CorrectLevel.M
    }});

    var LINK = "{wa_link}";
    var btn = document.getElementById('btnCopy');
    var btnText = document.getElementById('btnCopyText');

    function copiarLink() {{
      // Metodo moderno
      if(navigator.clipboard && window.isSecureContext){{
        navigator.clipboard.writeText(LINK).then(showOK).catch(fallback);
      }} else {{
        fallback();
      }}
    }}

    function fallback(){{
      // Fallback con textarea temporal
      var ta = document.createElement('textarea');
      ta.value = LINK;
      ta.style.position = 'fixed';
      ta.style.opacity = '0';
      document.body.appendChild(ta);
      ta.focus(); ta.select();
      try {{
        document.execCommand('copy');
        showOK();
      }} catch(e) {{
        alert('No se pudo copiar. Selecciona el link manualmente.');
      }}
      document.body.removeChild(ta);
    }}

    function showOK(){{
      btn.classList.add('ok');
      btnText.textContent = '✓ Copiado, pégalo en WhatsApp';
      setTimeout(function(){{
        btn.classList.remove('ok');
        btnText.textContent = 'Copiar link para enviar';
      }}, 2500);
    }}
  </script>
</body>
</html>"""

    return HTMLResponse(content=html)


@router.post("/{token}/preventa/upload")
async def preventa_upload(
    token: str = Path(..., min_length=16, max_length=64),
    file: UploadFile = File(...),
):
    """Lee el Excel DIMAX y devuelve un PREVIEW (no crea nada todavia)."""
    vendedor = _get_vendedor_by_token(token)
    if not vendedor or not vendedor.get("activo"):
        raise HTTPException(status_code=403, detail="Vendedor no valido")
    contents = await file.read()
    if not contents:
        raise HTTPException(status_code=400, detail="El archivo llego vacio.")
    try:
        from app.services.preventa_excel import parse_preventa_excel, match_bodega_por_nombre
        parsed = parse_preventa_excel(contents, filename=file.filename)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"No pude leer el Excel: {e}")
    sugerida, candidatos = match_bodega_por_nombre(
        parsed.get("bodega_nombre"), vendedor["distribuidor_id"]
    )
    return {
        "ok": True,
        "bodega_nombre": parsed.get("bodega_nombre"),
        "fecha": parsed.get("fecha"),
        "total_pedido": parsed.get("total_pedido"),
        "descuento_prorrateado": parsed.get("descuento_prorrateado"),
        "n_items": parsed.get("n_items"),
        "n_regalos": parsed.get("n_regalos"),
        "warnings": parsed.get("warnings") or [],
        "items": parsed.get("items") or [],
        "bodega_sugerida": sugerida,
        "candidatos": candidatos,
    }


@router.post("/{token}/preventa/crear")
async def preventa_crear(
    token: str = Path(..., min_length=16, max_length=64),
    request: Request = None,
):
    """Crea la preventa (estado preventa_confirmada) y devuelve el link/QR para compartir."""
    vendedor = _get_vendedor_by_token(token)
    if not vendedor or not vendedor.get("activo"):
        raise HTTPException(status_code=403, detail="Vendedor no valido")
    payload = await request.json()
    bodega_id = (payload or {}).get("bodega_id")
    items = (payload or {}).get("items") or []
    fecha = (payload or {}).get("fecha")
    descuento = float((payload or {}).get("descuento_prorrateado") or 0)
    if not bodega_id or not items:
        raise HTTPException(status_code=400, detail="Faltan datos: bodega o items.")

    from app.services import db as circa_db
    # Guard de credito: la bodega debe ser del mismo distribuidor del vendedor.
    bod = circa_db.sb.table("bodegas").select(
        "id, distribuidor_id, estado"
    ).eq("id", bodega_id).limit(1).execute().data
    if not bod or bod[0].get("distribuidor_id") != vendedor["distribuidor_id"]:
        raise HTTPException(status_code=403, detail="Esa bodega no es de tu distribuidor.")

    # Normalizar items OCR: mapear 'sku' a 'sku_distribuidor' si falta
    for it in items:
        if "sku_distribuidor" not in it and "sku" in it:
            it["sku_distribuidor"] = it["sku"]
        if "precio_unitario" not in it and "precio" in it:
            it["precio_unitario"] = it["precio"]
        if "descripcion" not in it and "nombre" in it:
            it["descripcion"] = it["nombre"]
        if "unidad" not in it and "pack_size" in it:
            it["unidad"] = it["pack_size"]
        if "sku_distribuidor" not in it:
            it["sku_distribuidor"] = ""

    # Total cobrado = suma de subtotales (los regalos vienen en 0). No confiamos en el total del cliente.
    total_pedido = round(sum(float(i.get("subtotal") or 0) for i in items), 2)
    if total_pedido <= 0:
        raise HTTPException(status_code=400, detail="El total cobrado salio en 0; revisa el Excel.")

    res = circa_db.crear_pedido_preventa(
        bodega_id=bodega_id,
        distribuidor_id=vendedor["distribuidor_id"],
        items_dimax=items,
        total_pedido=total_pedido,
        descuento_prorrateado=descuento,
        vendedor_id=vendedor.get("id"),
        fecha_visita=fecha,
    )
    link_token = res.get("link_token")

    # Notificar al bodeguero por WhatsApp (mismo disparo que distribuidor.py:1544)
    pedido_id_nuevo = res.get("pedido_id")
    if pedido_id_nuevo:
        try:
            import asyncio
            from app.flows.catalogo import notificar_preventa_bodeguero
            asyncio.ensure_future(notificar_preventa_bodeguero(str(pedido_id_nuevo)))
        except Exception as e:
            print(f"[preventa_crear] fallo al agendar notificacion: {e}")

    return {
        "ok": True,
        "pedido_id": res.get("pedido_id"),
        "items_creados": res.get("items_creados"),
        "items_no_match": res.get("items_no_match") or [],
        "total_pedido": total_pedido,
        "link_token": link_token,
        "share_url": f"/v/{token}/preventa/{link_token}/share",
    }


@router.get("/{token}/preventa/subir", response_class=HTMLResponse)
def vendedor_preventa_subir(token: str = Path(..., min_length=16, max_length=64)):
    vendedor = _get_vendedor_by_token(token)
    if not vendedor or not vendedor.get("activo"):
        raise HTTPException(status_code=403, detail="Vendedor no valido")
    return HTMLResponse(content=_HTML_SUBIR_PREVENTA.replace("__TOKEN__", token))


_HTML_SUBIR_PREVENTA = r"""<!doctype html>
<html lang="es"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1">
<title>Subir preventa &middot; Circa</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:#0D0D10;color:#fff;min-height:100vh;padding:20px 16px 60px}
.wrap{max-width:480px;margin:0 auto}
.top{display:flex;align-items:center;gap:10px;margin-bottom:6px}
.top a{color:rgba(255,255,255,.55);text-decoration:none;font-size:22px;line-height:1}
.titulo{font-size:22px;font-weight:700}
.sub{color:rgba(255,255,255,.5);font-size:13px;margin:2px 0 22px}
.card{background:rgba(255,255,255,.04);border:1px solid rgba(255,255,255,.08);border-radius:16px;padding:18px;margin-bottom:16px}
.card h3{font-size:12px;letter-spacing:.6px;text-transform:uppercase;color:#22D3EE;margin-bottom:12px;font-weight:700}
.drop{border:1.5px dashed rgba(34,211,238,.4);border-radius:14px;padding:26px 14px;text-align:center;cursor:pointer;transition:.15s}
.drop:hover{background:rgba(34,211,238,.06)}
.drop .big{font-size:15px;font-weight:600}
.drop .small{font-size:12px;color:rgba(255,255,255,.45);margin-top:5px}
.drop.filed{border-style:solid;border-color:rgba(34,211,238,.6);background:rgba(34,211,238,.07)}
input[type=file]{display:none}
.btn{display:block;width:100%;border:none;border-radius:13px;padding:15px;font-size:15px;font-weight:700;cursor:pointer;margin-top:14px;font-family:inherit}
.btn.primary{background:#22D3EE;color:#04222a}
.btn.primary:disabled{background:rgba(34,211,238,.25);color:rgba(255,255,255,.4);cursor:not-allowed}
.btn.ghost{background:transparent;border:1px solid rgba(255,255,255,.18);color:#fff;margin-top:10px}
.row{display:flex;justify-content:space-between;padding:7px 0;font-size:14px;border-bottom:1px solid rgba(255,255,255,.06)}
.row:last-child{border-bottom:none}
.row .k{color:rgba(255,255,255,.55)}
.row .v{font-weight:600}
.tot{font-size:24px;font-weight:800;color:#22D3EE}
.warn{background:rgba(245,176,66,.1);border:1px solid rgba(245,176,66,.3);color:#f5b042;border-radius:11px;padding:10px 12px;font-size:12.5px;margin-top:12px}
.bod{border:1px solid rgba(255,255,255,.1);border-radius:12px;padding:13px;margin-top:9px;cursor:pointer;transition:.12s}
.bod:hover{border-color:rgba(34,211,238,.5)}
.bod.sel{border-color:#22D3EE;background:rgba(34,211,238,.08)}
.bod .nm{font-weight:600;font-size:14px}
.bod .mt{font-size:12px;color:rgba(255,255,255,.5);margin-top:3px}
.bod .ln{font-size:12px;color:#22D3EE;margin-top:3px}
.detect{background:rgba(34,211,238,.08);border:1px solid rgba(34,211,238,.25);border-radius:11px;padding:11px 13px;font-size:13px;margin-bottom:12px}
.detect b{color:#22D3EE}
.find{display:flex;gap:8px;margin-top:12px}
.find input{flex:1;background:rgba(255,255,255,.05);border:1px solid rgba(255,255,255,.14);border-radius:11px;padding:12px;color:#fff;font-size:15px;font-family:inherit}
.find button{background:rgba(255,255,255,.1);border:none;border-radius:11px;color:#fff;padding:0 16px;font-weight:600;cursor:pointer}
.hidden{display:none}
.err{color:#ff6b6b;font-size:13px;margin-top:10px}
.spin{text-align:center;color:rgba(255,255,255,.5);font-size:13px;padding:10px}
</style></head>
<body><div class="wrap">
  <div class="top"><a href="/v/__TOKEN__">&larr;</a><div class="titulo">Subir preventa</div></div>
  <div class="sub">Sube el Excel que sale de ZOOM. Confirmas la bodega y listo.</div>

  <div class="card">
    <h3>1 &middot; Archivo de ZOOM</h3>
    <div style="display:flex;gap:6px;margin-bottom:12px">
      <button type="button" id="btnModoExcel" onclick="setModo('excel')" style="flex:1;padding:10px;border-radius:10px;border:2px solid #22D3EE;background:#22D3EE;color:#04222a;font-weight:700;cursor:pointer;font-size:13px;font-family:inherit">&#128196; Excel</button>
      <button type="button" id="btnModoFoto" onclick="setModo('foto')" style="flex:1;padding:10px;border-radius:10px;border:2px solid #22D3EE;background:transparent;color:#22D3EE;font-weight:700;cursor:pointer;font-size:13px;font-family:inherit">&#128247; Fotos ticket</button>
    </div>
    <div id="zonaExcel">
      <label class="drop" id="drop">
        <div class="big" id="dropTxt">Toca para elegir el Excel</div>
        <div class="small">archivo .xlsx tal cual sale del sistema</div>
        <input type="file" id="file" accept=".xlsx,.xls">
      </label>
      <button class="btn primary" id="btnRevisar" disabled>Revisar archivo</button>
    </div>
    <div id="zonaFotos" class="hidden">
      <div class="drop" id="dropFoto" onclick="document.getElementById('fileFotos').click()">
        <div class="big" id="dropFotoTxt">Toca para elegir fotos del ticket</div>
        <div class="small">puedes seleccionar varias im&aacute;genes</div>
        <input type="file" id="fileFotos" multiple accept="image/*" style="display:none">
      </div>
      <div id="thumbs" style="display:flex;flex-wrap:wrap;gap:6px;margin-top:10px"></div>
      <button class="btn primary hidden" id="btnProcesar" disabled>&#128270; Procesar fotos</button>
      <div id="ocrStatus" style="text-align:center;color:rgba(255,255,255,.5);font-size:12px;margin-top:6px"></div>
    </div>
    <div class="err hidden" id="errUp"></div>
  </div>

  <div class="card hidden" id="cardPrev">
    <h3>2 &middot; Revisa la preventa</h3>
    <div class="row"><span class="k">Fecha</span><span class="v" id="pvFecha">-</span></div>
    <div class="row"><span class="k">Productos</span><span class="v" id="pvItems">-</span></div>
    <div class="row"><span class="k">Regalos</span><span class="v" id="pvReg">-</span></div>
    <div class="row"><span class="k">Descuento ZOOM</span><span class="v" id="pvDesc">-</span></div>
    <div class="row"><span class="k">Total a cobrar</span><span class="tot" id="pvTot">-</span></div>
    <div id="pvWarn"></div>
    <div id="pvItems2" style="margin-top:10px"></div>
  </div>

  <div class="card hidden" id="cardBod">
    <h3>3 &middot; &iquest;Para qu&eacute; bodega?</h3>
    <div class="detect" id="detect"></div>
    <div id="sugBox"></div>
    <div id="candBox"></div>
    <div class="find">
      <input id="docInput" inputmode="numeric" placeholder="Buscar por DNI o RUC">
      <button id="btnFind">Buscar</button>
    </div>
    <div class="err hidden" id="errFind"></div>
    <div id="manualBox"></div>
  </div>

  <button class="btn primary hidden" id="btnCrear" disabled>Crear preventa</button>
  <div class="err hidden" id="errCrear"></div>
</div>
<script>
var TOKEN="__TOKEN__";
var modo="excel";

function setModo(m){
  modo=m;
  var zE=$("zonaExcel"),zF=$("zonaFotos"),bE=$("btnModoExcel"),bF=$("btnModoFoto");
  if(m==="foto"){
    zE.classList.add("hidden");zF.classList.remove("hidden");
    bF.style.background="#22D3EE";bF.style.color="#04222a";
    bE.style.background="transparent";bE.style.color="#22D3EE";
  } else {
    zE.classList.remove("hidden");zF.classList.add("hidden");
    bE.style.background="#22D3EE";bE.style.color="#04222a";
    bF.style.background="transparent";bF.style.color="#22D3EE";
  }
}

document.getElementById("fileFotos").addEventListener("change",function(){
  var files=this.files, box=$("thumbs");
  box.innerHTML="";
  for(var i=0;i<files.length;i++){
    (function(idx){
      var d=document.createElement("div");
      d.style.cssText="position:relative;width:64px;height:64px;border-radius:10px;overflow:hidden;border:1px solid rgba(255,255,255,.15)";
      var img=document.createElement("img");
      img.src=URL.createObjectURL(files[idx]);
      img.style.cssText="width:100%;height:100%;object-fit:cover";
      d.appendChild(img);
      box.appendChild(d);
    })(i);
  }
  if(files.length>0){
    $("dropFoto").classList.add("filed");
    $("dropFotoTxt").textContent=files.length+" foto"+(files.length>1?"s":"")+" seleccionada"+(files.length>1?"s":"");
    $("btnProcesar").classList.remove("hidden");
    $("btnProcesar").disabled=false;
  }
});

document.getElementById("btnProcesar").addEventListener("click",function(){
  var input=$("fileFotos");
  if(!input.files||input.files.length===0) return;
  var fd=new FormData();
  for(var i=0;i<input.files.length;i++) fd.append("files",input.files[i]);
  this.disabled=true; this.textContent="Procesando OCR...";
  $("ocrStatus").textContent="Leyendo "+input.files.length+" imagen"+(input.files.length>1?"es":"")+"...";
  $("errUp").classList.add("hidden");
  fetch("/v/"+TOKEN+"/preventa/upload-imagenes",{method:"POST",body:fd})
    .then(function(r){return r.json()})
    .then(function(data){
      $("btnProcesar").disabled=false;$("btnProcesar").textContent="Procesar fotos";
      if(!data.ok){
        $("ocrStatus").textContent="";
        throw new Error(data.error||(data.parse_errors||[]).join(", ")||"Error al procesar");
      }
      var matched=data.items||[];
      var noMatch=data.items_no_match||[];
      $("ocrStatus").textContent=matched.length+" items reconocidos"+(noMatch.length>0?", "+noMatch.length+" sin match en cat\u00e1logo":"");
      var nBonif=(matched.filter(function(x){return x.es_bonificacion}).length)+(data.bonificaciones||[]).length;
      preview={
        fecha:(data.headers&&data.headers[0]&&data.headers[0].fecha)||"(foto de ticket)",
        n_items:matched.length,
        n_regalos:nBonif,
        descuento_prorrateado:0,
        total_pedido:data.total_pedido,
        warnings:noMatch.map(function(x){return "Sin match: "+x.sku+" - "+x.descripcion}),
        bodega_nombre:data.bodega_nombre||"(identificar manualmente)",
        bodega_sugerida:data.bodega_sugerida||null,
        candidatos:data.candidatos||[],
        items_json:matched,
        origen_ocr:true,
        bonificaciones:data.bonificaciones||[]
      };
      renderPreview();
    })
    .catch(function(e){
      $("btnProcesar").disabled=false;$("btnProcesar").textContent="Procesar fotos";
      $("errUp").textContent=e.message;$("errUp").classList.remove("hidden");
    });
});
var preview=null, chosenId=null, chosenName=null;
var $=function(id){return document.getElementById(id)};

function money(n){return "S/"+(Number(n)||0).toFixed(2)}

$("file").addEventListener("change",function(){
  var f=this.files[0];
  if(f){$("dropTxt").textContent=f.name;$("drop").classList.add("filed");$("btnRevisar").disabled=false}
});

$("btnRevisar").addEventListener("click",function(){
  var f=$("file").files[0]; if(!f) return;
  $("errUp").classList.add("hidden");
  this.disabled=true; this.textContent="Leyendo...";
  var fd=new FormData(); fd.append("file",f);
  fetch("/v/"+TOKEN+"/preventa/upload",{method:"POST",body:fd})
   .then(function(r){return r.json().then(function(j){return {ok:r.ok,j:j}})})
   .then(function(res){
     $("btnRevisar").disabled=false; $("btnRevisar").textContent="Revisar archivo";
     if(!res.ok){throw new Error((res.j&&res.j.detail)||"No se pudo leer")}
     preview=res.j; renderPreview(); 
   })
   .catch(function(e){$("errUp").textContent=e.message;$("errUp").classList.remove("hidden")});
});

function renderPreview(){
  $("cardPrev").classList.remove("hidden");
  $("pvFecha").textContent=preview.fecha||"(no detectada)";
  $("pvItems").textContent=preview.n_items;
  $("pvReg").textContent=preview.n_regalos;
  $("pvDesc").textContent=money(preview.descuento_prorrateado);
  $("pvTot").textContent=money(preview.total_pedido);
  var w=$("pvWarn"); w.innerHTML="";
  (preview.warnings||[]).forEach(function(t){var d=document.createElement("div");d.className="warn";d.textContent=t;w.appendChild(d)});
  var il=$("pvItems2"); if(il) il.innerHTML="";
  if(preview.items_json && il){
    preview.items_json.forEach(function(it){
      var r=document.createElement("div");
      r.className="row";
      r.innerHTML='<span class="k">'+it.cantidad+'x '+(it.nombre||it.sku)+'</span><span class="v">S/'+(it.subtotal||0).toFixed(2)+'</span>';
      il.appendChild(r);
    });
    if(preview.bonificaciones){
      preview.bonificaciones.forEach(function(it){
        var r=document.createElement("div");
        r.className="row";
        r.innerHTML='<span class="k" style="color:#22D3EE">\ud83c\udf81 '+(it.cantidad||1)+'x '+(it.descripcion||it.sku)+'</span><span class="v" style="color:#22D3EE">REGALO</span>';
        il.appendChild(r);
      });
    }
  }
  $("cardBod").classList.remove("hidden");
  $("btnCrear").classList.remove("hidden");
  $("detect").innerHTML="El archivo dice: <b>"+(preview.bodega_nombre||"(sin nombre)")+"</b>";
  renderBodegas();
}

function pickBodega(id,name,el){
  chosenId=id; chosenName=name;
  document.querySelectorAll(".bod").forEach(function(x){x.classList.remove("sel")});
  if(el) el.classList.add("sel");
  $("btnCrear").disabled=false;
}

function bodCard(b){
  var d=document.createElement("div"); d.className="bod";
  var ln = (b.linea_disponible!=null)? '<div class="ln">L&iacute;nea disp. '+money(b.linea_disponible)+'</div>':'';
  var iden = b.identificacion || b.dni_representante || b.ruc || "";
  var idenHtml = iden ? '<div class="mt">'+iden+'</div>' : '';
  d.innerHTML='<div class="nm">'+(b.razon_social||b.nombre_comercial||"(sin nombre)")+'</div>'+idenHtml+'<div class="mt">'+(b.distrito||"")+'</div>'+ln;
  d.addEventListener("click",function(){pickBodega(b.id,b.razon_social||b.nombre_comercial,d)});
  return d;
}

function renderBodegas(){
  var sug=$("sugBox"); sug.innerHTML="";
  var cand=$("candBox"); cand.innerHTML="";
  if(preview.bodega_sugerida){
    var c=bodCard(preview.bodega_sugerida); sug.appendChild(c);
    pickBodega(preview.bodega_sugerida.id, preview.bodega_sugerida.razon_social, c);
  }
  var otras=(preview.candidatos||[]).filter(function(b){
    return !preview.bodega_sugerida || b.id!==preview.bodega_sugerida.id;
  });
  otras.forEach(function(b){cand.appendChild(bodCard(b))});
}

$("btnFind").addEventListener("click",function(){
  var q=($("docInput").value||"").trim();
  if(!q) return;
  $("errFind").classList.add("hidden");
  this.textContent="...";
  var self=this;
  fetch("/v/"+TOKEN+"/api/buscar-bodega?q="+encodeURIComponent(q))
   .then(function(r){return r.json()})
   .then(function(j){
     self.textContent="Buscar";
     if(j.found===false||j.error){throw new Error(j.error||"No encontrada")}
     var b = j.bodega || j;
     b.razon_social = b.razon_social || b.nombre_comercial || "(sin nombre)";
     var box=$("manualBox"); box.innerHTML="";
     var c=bodCard(b); box.appendChild(c);
     pickBodega(b.id,b.razon_social,c);
   })
   .catch(function(e){self.textContent="Buscar";$("errFind").textContent=e.message;$("errFind").classList.remove("hidden")});
});

$("btnCrear").addEventListener("click",function(){
  if(!chosenId||!preview) return;
  $("errCrear").classList.add("hidden");
  this.disabled=true; this.textContent="Creando...";
  var self=this;
  fetch("/v/"+TOKEN+"/preventa/crear",{
    method:"POST",headers:{"Content-Type":"application/json"},
    body:JSON.stringify({
      bodega_id:chosenId, items:(preview.items||preview.items_json||[]).map(function(x){return {sku_distribuidor:x.sku_distribuidor||x.sku||"",catalogo_id:x.catalogo_id,cantidad:x.cantidad,unidad:x.pack_size||x.unidad||"",precio_unitario:x.precio||x.precio_unitario||0,subtotal:x.subtotal||0,descripcion:x.nombre||x.descripcion||""};}),
      total_pedido:preview.total_pedido,
      descuento_prorrateado:preview.descuento_prorrateado,
      fecha:preview.fecha
    })
  })
   .then(function(r){return r.json().then(function(j){return {ok:r.ok,j:j}})})
   .then(function(res){
     if(!res.ok){throw new Error((res.j&&res.j.detail)||"No se pudo crear")}
     window.location.href=res.j.share_url;
   })
   .catch(function(e){self.disabled=false;self.textContent="Crear preventa";$("errCrear").textContent=e.message;$("errCrear").classList.remove("hidden")});
});
</script></body></html>"""


# ═══════════════════════════════════════════════════════════
# OCR: Upload múltiples fotos de tickets BsSoft
# ═══════════════════════════════════════════════════════════

@router.post("/{token}/preventa/upload-imagenes")
async def upload_imagenes_preventa(
    token: str,
    request: Request,
    files: list[UploadFile] = File(...),
):
    """
    Recibe múltiples fotos de tickets BsSoft, ejecuta OCR,
    matchea SKUs contra catálogo. Shape compatible con /preventa/upload.
    """
    import asyncio
    from fastapi.responses import JSONResponse

    # Import lazy — no crashea el app si falta dependencia
    try:
        from app.services.preventa_ocr import parse_ticket_bsoft, merge_items_multiples
    except Exception as e:
        return JSONResponse(
            {"error": f"OCR no disponible: {e}"},
            status_code=503,
        )

    # Validar vendedor
    vendedor = _get_vendedor_by_token(token)
    if not vendedor:
        return JSONResponse({"error": "Token inválido"}, status_code=401)

    if len(files) > 10:
        return JSONResponse(
            {"error": "Máximo 10 archivos permitidos"},
            status_code=400,
        )

    ALLOWED_TYPES = {
        "image/jpeg", "image/png", "image/webp",
        "image/heic", "image/heif",
        "application/pdf",
    }
    MAX_SIZE = 10 * 1024 * 1024

    images_bytes = []
    for f in files:
        ct = f.content_type or ""
        if ct not in ALLOWED_TYPES:
            return JSONResponse(
                {"error": f"Tipo no soportado: {f.filename} ({ct}). Usa JPG, PNG o PDF."},
                status_code=400,
            )
        data = await f.read()
        if len(data) > MAX_SIZE:
            return JSONResponse(
                {"error": f"Archivo muy grande: {f.filename}. Máximo 10MB."},
                status_code=400,
            )
        images_bytes.append(data)

    if not images_bytes:
        return JSONResponse({"error": "No se recibieron archivos"}, status_code=400)

    # OCR en paralelo
    loop = asyncio.get_event_loop()
    parseos = await asyncio.gather(*[
        loop.run_in_executor(None, parse_ticket_bsoft, img_bytes)
        for img_bytes in images_bytes
    ])

    merged = merge_items_multiples(list(parseos))
    ocr_items = merged["items"]

    if not ocr_items:
        return JSONResponse({
            "ok": False,
            "error": "No se pudieron leer items de las imágenes.",
            "parse_errors": merged["all_errors"],
            "raw_texts": merged["raw_texts"],
        })

    # Match contra catálogo del distribuidor
    dist_id = vendedor.get("distribuidor_id")
    if not dist_id:
        return JSONResponse({"error": "Vendedor sin distribuidor asignado"}, status_code=400)

    from app.services.db import sb
    
    cat_resp = sb.table("catalogo_distribuidor").select(
        "id, sku_distribuidor, producto_circa_id, unidades, activo, codigo"
    ).eq("distribuidor_id", str(dist_id)).eq("activo", True).execute()

    catalogo_rows = cat_resp.data or []

    pc_ids = [r["producto_circa_id"] for r in catalogo_rows if r.get("producto_circa_id")]
    pc_map = {}
    if pc_ids:
        for chunk_start in range(0, len(pc_ids), 50):
            chunk = pc_ids[chunk_start:chunk_start + 50]
            pc_resp = sb.table("productos_circa").select(
                "id, nombre, marca, categoria"
            ).in_("id", chunk).execute()
            for p in (pc_resp.data or []):
                pc_map[p["id"]] = p

    cat_by_sku = {}
    for row in catalogo_rows:
        sku = (row.get("sku_distribuidor") or "").strip()
        if sku:
            cat_by_sku[sku] = row
        codigo = row.get("codigo")
        if codigo:
            cat_by_sku[f"P{str(codigo).zfill(4)}"] = row

    items_matched = []
    items_no_match = []

    for ocr_item in ocr_items:
        sku = ocr_item["sku"]
        cat_row = cat_by_sku.get(sku)

        if not cat_row and sku.startswith("P"):
            numeric = sku[1:].lstrip("0")
            for k, v in cat_by_sku.items():
                if k.lstrip("P").lstrip("0") == numeric:
                    cat_row = v
                    break

        if cat_row:
            pc = pc_map.get(cat_row["producto_circa_id"], {})
            unidades = cat_row.get("unidades") or {}
            pack_size = ocr_item["pack_size"]

            # Precio del ticket como fuente de verdad. Catalogo solo referencia.
            # Fallback al catalogo solo si el OCR no leyo precio (bonif o error).
            precio_ocr = float(ocr_item.get("precio") or 0)
            precio_catalogo_raw = unidades.get(pack_size)
            precio_catalogo = float(precio_catalogo_raw) if precio_catalogo_raw is not None else None

            if precio_ocr > 0:
                precio = precio_ocr
            elif precio_catalogo is not None:
                precio = precio_catalogo
            else:
                precio = 0.0

            # Flag para preview: precio OCR difiere del catalogo > 2%
            precio_difiere = False
            if precio_ocr > 0 and precio_catalogo and precio_catalogo > 0:
                diff = abs(precio_ocr - precio_catalogo) / precio_catalogo
                precio_difiere = diff > 0.02

            items_matched.append({
                "catalogo_id": cat_row["id"],
                "nombre": pc.get("nombre", ocr_item["descripcion"]),
                "marca": pc.get("marca", ""),
                "pack_size": pack_size,
                "cantidad": ocr_item["cantidad"],
                "precio": round(precio, 2),
                "precio_catalogo": precio_catalogo,
                "precio_difiere": precio_difiere,
                "subtotal": round(precio * ocr_item["cantidad"], 2),
                "es_bonificacion": ocr_item["es_bonificacion"],
                "sku": sku,
            })
        else:
            items_no_match.append({
                "sku": sku,
                "descripcion": ocr_item["descripcion"],
                "pack_size": ocr_item["pack_size"],
                "cantidad": ocr_item["cantidad"],
                "precio": ocr_item["precio"],
                "total": ocr_item["total"],
                "es_bonificacion": ocr_item["es_bonificacion"],
            })

    total = sum(it["subtotal"] for it in items_matched)

    # Separar bonificaciones de items realmente no matcheados
    bonificaciones = [it for it in items_no_match if it.get("es_bonificacion")]
    items_sin_match_real = [it for it in items_no_match if not it.get("es_bonificacion")]

    # Extraer nombre de bodega del header OCR
    bodega_nombre = ""
    for h in merged.get("headers", []):
        if h.get("bodega_nombre"):
            bodega_nombre = h["bodega_nombre"]
            break

    # Auto-buscar bodega por nombre
    bodega_sugerida = None
    candidatos = []
    if bodega_nombre:
        try:
            palabras = bodega_nombre.strip().split()
            if len(palabras) >= 2:
                q = sb.table("bodegas").select(
                    "id, razon_social, nombre_comercial, distrito, "
                    "dni_representante, ruc, linea_disponible, linea_aprobada"
                ).eq("es_test", False)
                for p in palabras[:3]:
                    if len(p) > 2:
                        q = q.ilike("razon_social", f"%{p}%")
                result = q.limit(5).execute()
                if result.data:
                    bodega_sugerida = result.data[0]
                    candidatos = result.data[1:] if len(result.data) > 1 else []
        except Exception as e:
            import logging
            logging.getLogger("circa.ocr").warning(f"Bodega search failed: {e}")

    return JSONResponse({
        "ok": True,
        "items": items_matched,
        "items_no_match": items_sin_match_real,
        "bonificaciones": bonificaciones,
        "total_pedido": round(total, 2),
        "num_imagenes": len(images_bytes),
        "parse_errors": merged["all_errors"],
        "bodega_nombre": bodega_nombre,
        "headers": merged.get("headers", []),
        "bodega_sugerida": bodega_sugerida,
        "candidatos": candidatos,
    })


# ==========================================================
# FAST TRACK AFILIACIÓN  —  formulario de precarga de bodega
# ==========================================================
DIST_DIMAX_ID = "d1a2b3c4-0001-4000-8000-000000000002"
BUCKET_DNI = "dni_fotos"
BUCKET_LOCAL = "sustentos"  # foto de fachada va aquí bajo prefijo prospecto/


@router.get("/{token}/afiliar", response_class=HTMLResponse)
def afiliar_form(token: str = Path(..., min_length=16, max_length=64)):
    """Formulario de precarga de bodega nueva (Fast Track)."""
    vendedor = _get_vendedor_by_token(token)
    if not vendedor:
        raise HTTPException(status_code=404, detail="Acceso no encontrado")

    html = f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1.0,maximum-scale=1.0,user-scalable=no">
  <title>Circa · Afiliar bodega</title>
  <link href="https://fonts.googleapis.com/css2?family=Poppins:wght@400;500;600;700&display=swap" rel="stylesheet">
  <style>
    {CSS_BASE}
    .field{{margin-top:22px}}
    .hint{{font-size:11px;color:rgba(255,255,255,0.4);margin-top:6px;line-height:1.4}}
    .filebtn{{display:flex;align-items:center;justify-content:center;gap:8px;width:100%;padding:16px;background:rgba(255,255,255,0.05);border:1px dashed rgba(255,255,255,0.2);border-radius:14px;color:rgba(255,255,255,0.7);font-size:14px;cursor:pointer}}
    .filebtn.done{{border-style:solid;border-color:#22D3EE;color:#22D3EE}}
    input[type=file]{{display:none}}
    .row{{display:flex;gap:10px}}
    .row .field{{flex:1}}
    #msg{{margin-top:18px}}
  </style>
</head>
<body>
  <div class="logo">circa<span>.</span></div>
  <a href="/v/{token}" class="back" style="margin-top:16px;">&larr; Menú</a>
  <div class="titulo">[COPY: Afiliar bodega]</div>
  <div class="subtitulo">[COPY: instrucción corta — precarga los datos, el dueño termina por WhatsApp]</div>

  <div class="field">
    <label class="label">WHATSAPP DEL DUEÑO</label>
    <input class="input" id="tel" type="tel" inputmode="numeric" placeholder="9XX XXX XXX" maxlength="9">
    <div class="hint">[COPY: número personal del dueño — es su identidad en Circa]</div>
  </div>

  <div class="field">
    <label class="label">DNI DEL REPRESENTANTE</label>
    <input class="input" id="dni" type="tel" inputmode="numeric" placeholder="8 dígitos" maxlength="8">
  </div>

  <div class="field">
    <label class="label">RUC (OPCIONAL)</label>
    <input class="input" id="ruc" type="tel" inputmode="numeric" placeholder="11 dígitos — deja vacío si no tiene" maxlength="11">
  </div>

  <div class="field">
    <label class="label">FOTO DEL DNI</label>
    <label class="filebtn" id="lbl_dni" for="foto_dni">📷 [COPY: Subir foto del DNI]</label>
    <input type="file" id="foto_dni" accept="image/*" capture="environment">
  </div>

  <div class="field">
    <label class="label">FOTO DEL LOCAL (OPCIONAL)</label>
    <label class="filebtn" id="lbl_local" for="foto_local">📷 [COPY: Subir foto de la bodega]</label>
    <input type="file" id="foto_local" accept="image/*" capture="environment">
  </div>

  <button class="btn" id="submit" onclick="enviar()">[COPY: Afiliar bodega]</button>
  <div id="msg"></div>

  <script>
    const TOKEN = "{token}";
    document.getElementById('foto_dni').addEventListener('change', e => {{
      if (e.target.files.length) {{ const l=document.getElementById('lbl_dni'); l.textContent='✓ [COPY: DNI listo]'; l.classList.add('done'); }}
    }});
    document.getElementById('foto_local').addEventListener('change', e => {{
      if (e.target.files.length) {{ const l=document.getElementById('lbl_local'); l.textContent='✓ [COPY: Foto lista]'; l.classList.add('done'); }}
    }});

    async function enviar() {{
      const tel = document.getElementById('tel').value.replace(/\\D/g,'');
      const dni = document.getElementById('dni').value.replace(/\\D/g,'');
      const ruc = document.getElementById('ruc').value.replace(/\\D/g,'');
      const fotoDni = document.getElementById('foto_dni').files[0];
      const fotoLocal = document.getElementById('foto_local').files[0];
      const msg = document.getElementById('msg');
      const btn = document.getElementById('submit');

      if (tel.length !== 9) {{ msg.innerHTML='<div class="error">[COPY: Ingresa un WhatsApp válido de 9 dígitos]</div>'; return; }}
      if (dni.length !== 8) {{ msg.innerHTML='<div class="error">[COPY: El DNI debe tener 8 dígitos]</div>'; return; }}
      if (!fotoDni) {{ msg.innerHTML='<div class="error">[COPY: Falta la foto del DNI]</div>'; return; }}

      btn.disabled = true; btn.textContent = '[COPY: Afiliando...]';
      msg.innerHTML = '';

      const fd = new FormData();
      fd.append('telefono', tel);
      fd.append('dni', dni);
      fd.append('ruc', ruc);
      fd.append('foto_dni', fotoDni);
      if (fotoLocal) fd.append('foto_local', fotoLocal);

      try {{
        const r = await fetch('/v/'+TOKEN+'/api/afiliar', {{method:'POST', body:fd}});
        const data = await r.json();
        if (!r.ok || data.error) {{
          msg.innerHTML = '<div class="error">'+(data.error||'[COPY: No se pudo afiliar]')+'</div>';
          btn.disabled=false; btn.textContent='[COPY: Afiliar bodega]';
          return;
        }}
        msg.innerHTML = '<div class="card"><div class="nombre">✓ '+data.razon_social+'</div>'+
          '<div class="meta">DNI '+data.dni+(data.ruc?' · RUC '+data.ruc:'')+'</div>'+
          '<div class="meta" style="margin-top:10px;">[COPY: Bodega precargada. Cuando tenga línea asignada, el dueño escribe Hola al 986 311 567 y termina su afiliación.]</div></div>'+
          '<a href="/v/'+TOKEN+'/afiliar" class="btn secondary">[COPY: Afiliar otra]</a>';
        btn.style.display='none';
      }} catch (err) {{
        msg.innerHTML = '<div class="error">[COPY: Error de conexión. Reintenta.]</div>';
        btn.disabled=false; btn.textContent='[COPY: Afiliar bodega]';
      }}
    }}
  </script>
</body>
</html>"""
    return HTMLResponse(content=html)


def _subir_foto(bucket: str, path: str, data: bytes, content_type: str) -> bool:
    """Sube bytes a un bucket de Supabase Storage. Best-effort, no rompe el alta."""
    try:
        sb.storage.from_(bucket).upload(
            path=path, file=data,
            file_options={"content-type": content_type, "upsert": "true"},
        )
        return True
    except Exception as e:
        logger.warning(f"No se pudo subir foto a {bucket}/{path}: {e}")
        return False


@router.post("/{token}/api/afiliar")
async def api_afiliar(
    token: str,
    telefono: str = Form(...),
    dni: str = Form(...),
    ruc: str = Form(""),
    foto_dni: UploadFile = File(...),
    foto_local: UploadFile = File(None),
):
    """
    Precarga una bodega nueva (Fast Track). NO libera línea (linea_disponible=0,
    linea_aprobada=NULL). El dueño termina el onboarding por WhatsApp después.
    """
    from fastapi.responses import JSONResponse

    vendedor = _get_vendedor_by_token(token)
    if not vendedor or not vendedor.get("activo"):
        return JSONResponse({"error": "Vendedor no válido"}, status_code=403)

    tel_digits = re.sub(r"\D", "", telefono or "")
    dni_digits = re.sub(r"\D", "", dni or "")
    ruc_digits = re.sub(r"\D", "", ruc or "")

    if len(tel_digits) != 9:
        return JSONResponse({"error": "[COPY: WhatsApp inválido]"}, status_code=400)
    tel_e164 = "+51" + tel_digits

    ok_fmt, msg_fmt = validate_dni_format(dni_digits)
    if not ok_fmt:
        return JSONResponse({"error": msg_fmt}, status_code=400)

    # Validar DNI contra RENIEC (mismo proveedor que el onboarding)
    persona = await consultar_dni(dni_digits)
    if not persona or not persona.get("nombre_completo"):
        return JSONResponse(
            {"error": "[COPY: No se pudo validar el DNI en RENIEC. Verifica el número.]"},
            status_code=400,
        )
    razon_social = persona["nombre_completo"]

    # ── Dedup: no duplicar bodega existente ─────────────────────────────────
    filtro = f"or=(dni_representante.eq.{dni_digits},telefono_whatsapp.eq.{tel_e164}"
    if ruc_digits:
        filtro += f",ruc.eq.{ruc_digits}"
    filtro += ")"
    existentes = sb.table("bodegas").select("id, razon_social, telefono_whatsapp") \
        .or_(f"dni_representante.eq.{dni_digits},telefono_whatsapp.eq.{tel_e164}") \
        .limit(1).execute().data

    solo_dni = len(ruc_digits) != 11

    # ── Subir foto de DNI (bucket privado) ──────────────────────────────────
    dni_bytes = await foto_dni.read()
    ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    dni_ct = foto_dni.content_type or "image/jpeg"
    dni_ext = {"image/png": "png", "image/webp": "webp"}.get(dni_ct, "jpg")
    dni_path = f"prospecto/{tel_e164}/dni_{ts}.{dni_ext}"
    _subir_foto(BUCKET_DNI, dni_path, dni_bytes, dni_ct)

    if foto_local is not None:
        loc_bytes = await foto_local.read()
        loc_ct = foto_local.content_type or "image/jpeg"
        loc_ext = {"image/png": "png", "image/webp": "webp"}.get(loc_ct, "jpg")
        _subir_foto(BUCKET_LOCAL, f"prospecto/{tel_e164}/local_{ts}.{loc_ext}", loc_bytes, loc_ct)

    if existentes:
        # Ya existe: completar solo campos vacíos, NUNCA pisar. No re-crear.
        b = existentes[0]
        patch = {"dni_foto_url": dni_path, "kyc_nivel": "dni"}
        try:
            sb.table("bodegas").update(patch).eq("id", b["id"]).execute()
        except Exception as e:
            logger.warning(f"No se pudo actualizar bodega existente {b['id']}: {e}")
        return JSONResponse({
            "ok": True, "razon_social": b.get("razon_social") or razon_social,
            "dni": dni_digits, "ruc": ruc_digits, "duplicado": True,
        })

    # ── Crear bodega precargada ─────────────────────────────────────────────
    nueva = {
        "razon_social": razon_social,
        "representante_legal": razon_social,
        "representante_nombre_corto": _primer_nombre(razon_social),
        "dni_representante": dni_digits,
        "dni_foto_url": dni_path,
        "telefono_whatsapp": tel_e164,
        "ruc": ruc_digits if ruc_digits else None,
        "solo_dni_sin_ruc": solo_dni,
        "linea_disponible": 0,          # D-003: nunca liberar aquí
        # linea_aprobada se deja NULL: la asigna el modelo cuando llegue el histórico
        "distribuidor_id": vendedor["distribuidor_id"],
        "estado": "inactivo",
        "kyc_nivel": "dni",             # DNI validado, selfie pendiente
        "onboarding_fase": "precargada",
        "es_test": False,
        "en_piloto": True,
    }
    try:
        res = sb.table("bodegas").insert(nueva).execute()
        bodega_id = res.data[0]["id"]
    except Exception as e:
        logger.error(f"Fallo al crear bodega precargada: {e}")
        return JSONResponse({"error": f"[COPY: No se pudo crear la bodega] ({e})"}, status_code=500)

    # ── Mapeo bodega ↔ vendedor (atribución comercial) ──────────────────────
    try:
        sb.table("bodega_vendedores").insert({
            "bodega_id": bodega_id,
            "vendedor_id": vendedor["id"],
            "rol": "ABN",
            "activo": True,
        }).execute()
    except Exception as e:
        logger.warning(f"No se pudo mapear bodega_vendedores: {e}")

    return JSONResponse({
        "ok": True, "razon_social": razon_social,
        "dni": dni_digits, "ruc": ruc_digits, "bodega_id": bodega_id,
    })

