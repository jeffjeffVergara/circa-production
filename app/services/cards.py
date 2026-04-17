"""
Circa branded cards — HTML rendered via htmlcsstoimage.com API.
Brand: Blue #5B8AF5, Black #0D0D10, White #FFFFFF, Font Poppins
"""
import os, logging, httpx

logger = logging.getLogger("circa.cards")

HCTI_USER = os.getenv("HCTI_USER_ID", "")
HCTI_KEY = os.getenv("HCTI_API_KEY", "")
HCTI_URL = "https://hcti.io/v1/image"

CSS = """
@import url('https://fonts.googleapis.com/css2?family=Poppins:wght@400;600;700;800&display=swap');
:root{--blue:#5B8AF5;--black:#0D0D10;--green:#16a34a;--red:#DC2626;--muted:#6E6E80;--line:#e5e7eb;}
*{box-sizing:border-box;margin:0;padding:0;}
body{font-family:'Poppins',sans-serif;background:{bg};padding:28px;display:flex;justify-content:center;}
.frame{width:760px;background:{bg};border-radius:28px;padding:28px;}
.ticket{background:#fff;border-radius:28px;position:relative;overflow:hidden;box-shadow:0 18px 40px rgba(0,0,0,0.12);}
.ticket::before,.ticket::after{content:"";position:absolute;width:34px;height:34px;border-radius:50%;background:{bg};top:{hole}%;transform:translateY(-50%);z-index:2;}
.ticket::before{left:-17px;}
.ticket::after{right:-17px;}
.top{padding:36px 36px 24px;text-align:center;}
.logo{margin-bottom:18px;}
.logo svg{height:56px;}
.icon{width:96px;height:96px;margin:10px auto 18px;border-radius:50%;background:{icon_bg};display:flex;align-items:center;justify-content:center;color:#fff;font-size:54px;font-weight:700;}
.status{color:{status_c};font-weight:800;font-size:28px;margin:0 0 14px;}
.title{color:var(--black);font-weight:800;font-size:34px;line-height:1.1;margin:0 0 26px;}
.divider{height:1px;background:var(--line);}
.amt-section{padding:28px 36px 24px;text-align:center;}
.amt-label{color:{amt_label_c};font-size:20px;font-weight:800;letter-spacing:0.5px;margin-bottom:16px;text-transform:uppercase;}
.amt{color:{amt_c};font-weight:900;font-size:84px;line-height:1;}
.amt small{font-size:44px;font-weight:700;vertical-align:middle;margin-right:8px;}
.details{padding:14px 36px 24px;}
.row{display:flex;align-items:center;gap:14px;padding:18px 0;border-top:1px dashed #d1d5db;font-size:19px;color:var(--black);}
.row:first-child{border-top:1px solid var(--line);}
.lbl{font-weight:700;min-width:160px;color:var(--muted);}
.val{font-weight:500;flex:1;}
.bottom{border-top:2px dashed {dash_c};padding:22px 36px 28px;}
.bottom strong{display:block;color:{strong_c};font-size:18px;margin-bottom:4px;}
.bottom span{color:var(--muted);font-size:16px;line-height:1.4;}
.ts{text-align:center;color:var(--muted);font-size:14px;padding:0 36px 24px;}
"""

LOGO_SVG = '<svg viewBox="0 0 240 80" fill="none" xmlns="http://www.w3.org/2000/svg"><ellipse cx="32" cy="40" rx="28" ry="28" stroke="#5B8AF5" stroke-width="5" fill="none"/><ellipse cx="56" cy="40" rx="28" ry="28" stroke="#5B8AF5" stroke-width="5" fill="none"/><text x="96" y="52" font-family="Poppins,sans-serif" font-weight="800" font-size="36" fill="#0D0D10" letter-spacing="2">CIRCA</text></svg>'

def _render(html, css):
    if not HCTI_USER or not HCTI_KEY:
        logger.error("HCTI credentials not set")
        return None
    try:
        r = httpx.post(HCTI_URL, data={"html": html, "css": css, "google_fonts": "Poppins"}, auth=(HCTI_USER, HCTI_KEY), timeout=30)
        r.raise_for_status()
        url = r.json().get("url")
        if url:
            img = httpx.get(url, timeout=30)
            return img.content
    except Exception as e:
        logger.error(f"HCTI render error: {e}")
    return None

def _css(**kw):
    return CSS.format(**kw)

def _rows(items):
    return "".join(f'<div class="row"><div class="lbl">{l}</div><div class="val">{v}</div></div>' for l, v in items)


def generate_account_activated_card(nombre, linea, distribuidor):
    from datetime import datetime
    css = _css(bg="#5B8AF5", hole=64, icon_bg="var(--green)", status_c="var(--green)", amt_label_c="var(--blue)", amt_c="var(--blue)", dash_c="var(--blue)", strong_c="var(--green)")
    now = datetime.now().strftime("%d %b %Y, %I:%M %p")
    html = f'''<div class="frame"><div class="ticket">
      <div class="top"><div class="logo">{LOGO_SVG}</div><div class="icon">✓</div>
      <p class="status">¡Cuenta activada!</p><h1 class="title">{nombre}</h1></div>
      <div class="divider"></div>
      <div class="amt-section"><div class="amt-label">Crédito disponible</div><p class="amt"><small>S/</small>{linea:,.2f}</p></div>
      <div class="details">{_rows([("Bodega", nombre), ("Distribuidor", distribuidor), ("Activada", now)])}</div>
      <div class="bottom"><div><strong>Compra hoy. Paga después.</strong><span>7, 15 o 30 días. Tu línea se renueva al pagar.</span></div></div>
    </div></div>'''
    return _render(html, css)


def generate_contract_signed_card(nombre, ruc, linea, contract_hash):
    from datetime import datetime
    css = _css(bg="#5B8AF5", hole=52, icon_bg="var(--green)", status_c="var(--green)", amt_label_c="var(--blue)", amt_c="var(--blue)", dash_c="var(--blue)", strong_c="var(--green)")
    now = datetime.now().strftime("%d/%m/%Y %H:%M")
    h = (contract_hash[:16] if contract_hash else "---")
    html = f'''<div class="frame"><div class="ticket">
      <div class="top"><div class="logo">{LOGO_SVG}</div><div class="icon">✓</div>
      <p class="status">Contrato firmado</p><h1 class="title">{nombre}</h1></div>
      <div class="divider"></div>
      <div class="details">{_rows([("RUC", ruc), ("Crédito", f"S/ {linea:,.2f}"), ("Contrato", "Facilidad Financ. v2.0"), ("Hash", h)])}</div>
      <div class="bottom"><div><strong>Firmado: {now}</strong><span>Recibirás el contrato completo en PDF</span></div></div>
    </div></div>'''
    return _render(html, css)


def generate_order_confirmed_card(numero, items_summary, monto, fee, total, dias, vencimiento, monto_productos=0):
    from datetime import datetime
    css = _css(bg="#5B8AF5", hole=60, icon_bg="var(--green)", status_c="var(--green)", amt_label_c="var(--green)", amt_c="var(--black)", dash_c="var(--green)", strong_c="var(--green)")
    lbl = "Total financiado" if dias > 0 else "Total contado"
    now = datetime.now().strftime("%d/%m/%Y %H:%M")
    det = []
    if monto_productos > 0:
        det.append(("Total compra", f"S/ {monto_productos:,.2f}"))
    if dias > 0:
        det += [("Financiado", f"S/ {monto:,.2f}"), (f"Fee ({dias}d)", f"S/ {fee:,.2f}"), ("Plazo", f"{dias} días"), ("Vence", vencimiento)]
    else:
        det.append(("Total", f"S/ {total:,.2f}"))
    pago = '<strong>Paga por Yape o Plin al 986311567</strong><span>PALI SAC</span><br>' if dias > 0 else ''
    html = f'''<div class="frame"><div class="ticket">
      <div class="top"><div class="logo">{LOGO_SVG}</div><div class="icon">✓</div>
      <p class="status">¡Pedido confirmado!</p><h1 class="title">{numero}</h1></div>
      <div class="divider"></div>
      <div class="amt-section"><div class="amt-label">{lbl}</div><p class="amt"><small>S/</small>{total:,.2f}</p></div>
      <div class="details">{_rows(det)}</div>
      <div class="bottom"><div>{pago}<span>Recibirás actualizaciones por WhatsApp</span></div></div>
      <div class="ts">{now} | Circa</div>
    </div></div>'''
    return _render(html, css)


def generate_payment_reminder_card(numero, monto_financiado, fee, total, dias, vencimiento):
    from datetime import datetime
    css = _css(bg="#5B8AF5", hole=58, icon_bg="var(--red)", status_c="var(--red)", amt_label_c="var(--red)", amt_c="var(--black)", dash_c="var(--red)", strong_c="var(--red)")
    now = datetime.now().strftime("%d/%m/%Y %H:%M")
    det = [("Pedido", numero), ("Financiado", f"S/ {monto_financiado:,.2f}"), ("Fee", f"S/ {fee:,.2f}"), ("Plazo", f"{dias} días"), ("Vence", vencimiento)]
    html = f'''<div class="frame"><div class="ticket">
      <div class="top"><div class="logo">{LOGO_SVG}</div><div class="icon" style="background:var(--red);">!</div>
      <p class="status">Recordatorio de pago</p><h1 class="title">Pedido {numero}</h1></div>
      <div class="divider"></div>
      <div class="amt-section"><div class="amt-label">Total a pagar</div><p class="amt"><small>S/</small>{total:,.2f}</p></div>
      <div class="details">{_rows(det)}</div>
      <div class="bottom"><div><strong>Paga por Yape o Plin al:</strong><span>986311567 — PALI SAC</span><br><span style="margin-top:8px;display:block;">Después de pagar, escribe <b>YA PAGUE</b> en el chat.</span></div></div>
      <div class="ts">{now} | Circa</div>
    </div></div>'''
    return _render(html, css)
