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
from datetime import datetime, timezone
import os, httpx, logging

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
    <a href="/v/{token}/preventa" class="menu-btn">
      Hacer preventa
      <span class="desc">Arma un pedido para tu cliente</span>
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
        const meta = [b.razon_social, b.distrito].filter(Boolean).join(' · ');
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
        return {"found": False, "error": f"No encontramos una bodega con ese {tipo}"}

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
  <div class="subtitulo">Pásale el link o el QR a tu cliente</div>

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
    El cliente abre el QR (o pega el link en WhatsApp)<br>y aprueba la preventa con su clave Circa.
  </div>

  <div class="btns-final">
    <a href="/v/{token}/preventa" class="btn secondary">Nueva preventa</a>
    <a href="https://wa.me/?text=Hola%20te%20paso%20el%20link%20para%20aprobar%20tu%20pedido%20Circa%3A%20{wa_link}" target="_blank" class="btn">Compartir</a>
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
