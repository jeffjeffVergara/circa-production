"""
Vendedor App — Preventa Presencial (Circa)
==========================================
Endpoint para vendedores DIMAX que arman pedidos en bodega
usando su URL personal con access_token.

URL pattern: /v/{access_token}
"""
from fastapi import APIRouter, HTTPException, Path
from fastapi.responses import HTMLResponse
from datetime import datetime, timezone
import os, httpx, logging

router = APIRouter(prefix="/v", tags=["vendedor"])
logger = logging.getLogger("circa")

SUPABASE_URL = os.getenv("SUPABASE_URL", "https://rhxqcoijzgqlecpdfhde.supabase.co")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_KEY", os.getenv("SUPABASE_KEY", ""))


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


def _get_vendedor_by_token(token: str):
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
    try:
        _sb_patch("vendedores",
                  {"ultimo_acceso": datetime.now(timezone.utc).isoformat()},
                  {"id": f"eq.{vendedor_id}"})
    except Exception as e:
        logger.warning(f"No se pudo registrar ultimo_acceso para {vendedor_id}: {e}")


def _primer_nombre(nombre_completo: str) -> str:
    tokens = nombre_completo.strip().split()
    if len(tokens) >= 3:
        return tokens[2].capitalize()
    return tokens[-1].capitalize() if tokens else "Vendedor"


@router.get("/{token}", response_class=HTMLResponse)
def vendedor_home(token: str = Path(..., min_length=16, max_length=64)):
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
    *{{box-sizing:border-box;margin:0;padding:0}}
    body{{font-family:'Poppins',-apple-system,sans-serif;background:#0A0E1A;color:#fff;min-height:100vh;padding:32px 22px;-webkit-tap-highlight-color:transparent}}
    .logo{{font-size:26px;font-weight:700;letter-spacing:-0.5px}}
    .logo span{{color:#2563EB}}
    .saludo{{margin-top:36px;font-size:13px;color:rgba(255,255,255,0.5);letter-spacing:0.3px}}
    .nombre{{margin-top:4px;font-size:24px;font-weight:600}}
    .codigo{{margin-top:6px;font-size:12px;color:rgba(255,255,255,0.4);letter-spacing:0.5px}}
    .menu{{margin-top:48px}}
    .btn{{display:block;width:100%;padding:20px 22px;background:#2563EB;border:none;border-radius:14px;color:#fff;font-family:inherit;font-size:16px;font-weight:600;text-align:left;text-decoration:none;margin-bottom:14px;cursor:pointer;transition:transform 0.1s ease}}
    .btn:active{{transform:scale(0.98)}}
    .btn.secondary{{background:rgba(255,255,255,0.05);border:1px solid rgba(255,255,255,0.1)}}
    .btn .desc{{display:block;font-size:12px;font-weight:400;color:rgba(255,255,255,0.7);margin-top:4px}}
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
    <a href="/v/{token}/preventa" class="btn">
      Hacer preventa
      <span class="desc">Arma un pedido para tu cliente</span>
    </a>
    <a href="/v/{token}/mis-pedidos" class="btn secondary">
      Mis preventas
      <span class="desc">Ve el estado de tus pedidos</span>
    </a>
  </div>

  <div class="footer">Circa · Pali SAC</div>
</body>
</html>"""

    return HTMLResponse(content=html)
