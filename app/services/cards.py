"""
Circa branded cards — HTML rendered to PNG via wkhtmltoimage.
Brand: Blue #5B8AF5, Black #0D0D10, White #FFFFFF
"""
import io, os, tempfile, logging
import imgkit

logger = logging.getLogger("circa.cards")

IMGKIT_CONFIG = imgkit.config(wkhtmltoimage="/usr/bin/wkhtmltoimage")
IMGKIT_OPTIONS = {"format": "png", "width": 760, "quality": 95, "enable-local-file-access": "", "xvfb": ""}

BASE_CSS = """
:root { --circa-blue:#5B8AF5; --circa-green:#16a34a; --circa-red:#DC2626; --text:#0D0D10; --muted:#6E6E80; --line:#e5e7eb; --card:#fff; }
* { box-sizing:border-box; margin:0; padding:0; }
body { font-family:'DejaVu Sans',Arial,sans-serif; background:{frame_color}; display:flex; align-items:center; justify-content:center; min-height:100vh; padding:28px; }
.frame { width:760px; background:{frame_color}; border-radius:28px; padding:28px; }
.ticket { background:var(--card); border-radius:28px; position:relative; overflow:hidden; box-shadow:0 18px 40px rgba(0,0,0,0.12); }
.ticket::before,.ticket::after { content:""; position:absolute; width:34px; height:34px; border-radius:50%; background:{frame_color}; top:{hole_pct}%; transform:translateY(-50%); z-index:2; }
.ticket::before {{ left:-17px; }}
.ticket::after {{ right:-17px; }}
.top { padding:36px 36px 24px; text-align:center; }
.logo { display:inline-flex; align-items:center; gap:14px; margin-bottom:18px; }
.logo svg { height:56px; }
.check-wrap { width:96px; height:96px; margin:10px auto 18px; border-radius:50%; background:{icon_color}; display:flex; align-items:center; justify-content:center; color:#fff; font-size:54px; font-weight:700; }
.status { color:{status_color}; font-weight:800; font-size:28px; margin:0 0 14px; }
.store-name { color:var(--text); font-weight:800; font-size:34px; line-height:1.1; margin:0 0 26px; }
.divider { height:1px; background:var(--line); }
.amount-section { padding:28px 36px 24px; text-align:center; }
.amount-label { color:{amount_label_color}; font-size:20px; font-weight:800; letter-spacing:0.5px; margin-bottom:16px; text-transform:uppercase; }
.amount { color:{amount_color}; font-weight:900; font-size:84px; line-height:1; }
.amount small { font-size:44px; font-weight:700; vertical-align:middle; margin-right:8px; }
.details { padding:14px 36px 24px; }
.detail-row { display:flex; align-items:center; gap:14px; padding:18px 0; border-top:1px dashed #d1d5db; font-size:19px; color:var(--text); }
.detail-row:first-child { border-top:1px solid var(--line); }
.label { font-weight:700; min-width:160px; color:var(--muted); }
.value { font-weight:500; flex:1; }
.bottom { border-top:2px dashed {bottom_dash_color}; padding:22px 36px 28px; }
.bottom strong { display:block; color:{bottom_strong_color}; font-size:18px; margin-bottom:4px; }
.bottom span { color:var(--muted); font-size:16px; line-height:1.4; }
.footer-ts { text-align:center; color:var(--muted); font-size:14px; padding:0 36px 24px; }
"""

def _render(html):
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
        tmp_path = tmp.name
    try:
        imgkit.from_string(html, tmp_path, options=IMGKIT_OPTIONS, config=IMGKIT_CONFIG)
        with open(tmp_path, "rb") as f:
            return f.read()
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)

LOGO = '<svg viewBox="0 0 240 80" fill="none" xmlns="http://www.w3.org/2000/svg"><ellipse cx="32" cy="40" rx="28" ry="28" stroke="#5B8AF5" stroke-width="5" fill="none"/><ellipse cx="56" cy="40" rx="28" ry="28" stroke="#5B8AF5" stroke-width="5" fill="none"/><text x="96" y="52" font-family="DejaVu Sans,Arial,sans-serif" font-weight="800" font-size="36" fill="#0D0D10" letter-spacing="2">CIRCA</text></svg>'

def _css(**kw):
    return BASE_CSS.format(**kw)

def _html(css, body):
    return f'<!DOCTYPE html><html><head><meta charset="UTF-8"><style>{css}</style></head><body><div class="frame"><div class="ticket">{body}</div></div></body></html>'

def generate_account_activated_card(nombre, linea, distribuidor):
    from datetime import datetime
    css = _css(frame_color="#5B8AF5", hole_pct=64, icon_color="var(--circa-green)", status_color="var(--circa-green)", amount_label_color="var(--circa-blue)", amount_color="var(--circa-blue)", bottom_dash_color="var(--circa-blue)", bottom_strong_color="var(--circa-green)")
    now = datetime.now().strftime("%d %b %Y, %I:%M %p")
    body = f'''<div class="top"><div class="logo">{LOGO}</div><div class="check-wrap">&#10003;</div><p class="status">¡Cuenta activada!</p><h1 class="store-name">{nombre}</h1></div><div class="divider"></div><div class="amount-section"><div class="amount-label">Crédito disponible</div><p class="amount"><small>S/</small>{linea:,.2f}</p></div><div class="details"><div class="detail-row"><div class="label">Bodega</div><div class="value">{nombre}</div></div><div class="detail-row"><div class="label">Distribuidor</div><div class="value">{distribuidor}</div></div><div class="detail-row"><div class="label">Activada</div><div class="value">{now}</div></div></div><div class="bottom"><div><strong>Compra hoy. Paga después.</strong><span>7, 15 o 30 días. Tu línea se renueva al pagar.</span></div></div>'''
    return _render(_html(css, body))

def generate_contract_signed_card(nombre, ruc, linea, contract_hash):
    from datetime import datetime
    css = _css(frame_color="#5B8AF5", hole_pct=52, icon_color="var(--circa-green)", status_color="var(--circa-green)", amount_label_color="var(--circa-blue)", amount_color="var(--circa-blue)", bottom_dash_color="var(--circa-blue)", bottom_strong_color="var(--circa-green)")
    now = datetime.now().strftime("%d/%m/%Y %H:%M")
    h = (contract_hash[:16] if contract_hash else "---")
    body = f'''<div class="top"><div class="logo">{LOGO}</div><div class="check-wrap">&#10003;</div><p class="status">Contrato firmado</p><h1 class="store-name">{nombre}</h1></div><div class="divider"></div><div class="details"><div class="detail-row"><div class="label">RUC</div><div class="value">{ruc}</div></div><div class="detail-row"><div class="label">Crédito</div><div class="value">S/ {linea:,.2f}</div></div><div class="detail-row"><div class="label">Contrato</div><div class="value">Facilidad Financ. v2.0</div></div><div class="detail-row"><div class="label">Hash</div><div class="value">{h}</div></div></div><div class="bottom"><div><strong>Firmado: {now}</strong><span>Recibirás el contrato completo en PDF</span></div></div>'''
    return _render(_html(css, body))

def generate_order_confirmed_card(numero, items_summary, monto, fee, total, dias, vencimiento, monto_productos=0):
    from datetime import datetime
    css = _css(frame_color="#5B8AF5", hole_pct=60, icon_color="var(--circa-green)", status_color="var(--circa-green)", amount_label_color="var(--circa-green)", amount_color="var(--text)", bottom_dash_color="var(--circa-green)", bottom_strong_color="var(--circa-green)")
    lbl = "Total financiado" if dias > 0 else "Total contado"
    now = datetime.now().strftime("%d/%m/%Y %H:%M")
    det = ""
    if monto_productos > 0:
        det += f'<div class="detail-row"><div class="label">Total compra</div><div class="value">S/ {monto_productos:,.2f}</div></div>'
    if dias > 0:
        det += f'<div class="detail-row"><div class="label">Financiado</div><div class="value">S/ {monto:,.2f}</div></div>'
        det += f'<div class="detail-row"><div class="label">Fee ({dias}d)</div><div class="value">S/ {fee:,.2f}</div></div>'
        det += f'<div class="detail-row"><div class="label">Plazo</div><div class="value">{dias} días</div></div>'
        det += f'<div class="detail-row"><div class="label">Vence</div><div class="value">{vencimiento}</div></div>'
    else:
        det += f'<div class="detail-row"><div class="label">Total</div><div class="value">S/ {total:,.2f}</div></div>'
    pago = f'<strong>Paga por Yape o Plin al 986311567</strong><span>PALI SAC</span><br>' if dias > 0 else ''
    body = f'''<div class="top"><div class="logo">{LOGO}</div><div class="check-wrap">&#10003;</div><p class="status">¡Pedido confirmado!</p><h1 class="store-name">{numero}</h1></div><div class="divider"></div><div class="amount-section"><div class="amount-label">{lbl}</div><p class="amount"><small>S/</small>{total:,.2f}</p></div><div class="details">{det}</div><div class="bottom"><div>{pago}<span>Recibirás actualizaciones por WhatsApp</span></div></div><div class="footer-ts">{now} | Circa</div>'''
    return _render(_html(css, body))

def generate_payment_reminder_card(numero, monto_financiado, fee, total, dias, vencimiento):
    from datetime import datetime
    css = _css(frame_color="#5B8AF5", hole_pct=58, icon_color="var(--circa-red)", status_color="var(--circa-red)", amount_label_color="var(--circa-red)", amount_color="var(--text)", bottom_dash_color="var(--circa-red)", bottom_strong_color="var(--circa-red)")
    now = datetime.now().strftime("%d/%m/%Y %H:%M")
    body = f'''<div class="top"><div class="logo">{LOGO}</div><div class="check-wrap" style="background:var(--circa-red);">!</div><p class="status">Recordatorio de pago</p><h1 class="store-name">Pedido {numero}</h1></div><div class="divider"></div><div class="amount-section"><div class="amount-label">Total a pagar</div><p class="amount"><small>S/</small>{total:,.2f}</p></div><div class="details"><div class="detail-row"><div class="label">Pedido</div><div class="value">{numero}</div></div><div class="detail-row"><div class="label">Financiado</div><div class="value">S/ {monto_financiado:,.2f}</div></div><div class="detail-row"><div class="label">Fee</div><div class="value">S/ {fee:,.2f}</div></div><div class="detail-row"><div class="label">Plazo</div><div class="value">{dias} días</div></div><div class="detail-row"><div class="label">Vence</div><div class="value">{vencimiento}</div></div></div><div class="bottom"><div><strong>Paga por Yape o Plin al:</strong><span>986311567 — PALI SAC</span><br><span style="margin-top:8px;display:block;">Después de pagar, escribe <b>YA PAGUE</b> en el chat.</span></div></div><div class="footer-ts">{now} | Circa</div>'''
    return _render(_html(css, body))
