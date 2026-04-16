"""
Circa branded cards — ticket style with proper sizing.
Brand: Blue #5B8AF5, Black #0D0D10, White #FFFFFF
Font: Poppins (fallback DejaVu on Railway)
"""
import os, io
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont

# Brand palette
BLUE   = (91, 138, 245)
BLACK  = (13, 13, 16)
WHITE  = (255, 255, 255)
GREEN  = (22, 163, 74)
RED    = (220, 38, 38)
MUTED  = (110, 110, 128)
LINE   = (229, 231, 234)

W = 1080
PAD = 40
IP = 80  # inner padding

def _font(size, bold=False):
    fdir = os.path.join(os.path.dirname(__file__), "..", "static", "fonts")
    if bold:
        paths = [os.path.join(fdir, "Poppins-Bold.ttf"), os.path.join(fdir, "Poppins-ExtraBold.ttf"), "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"]
    else:
        paths = [os.path.join(fdir, "Poppins-Regular.ttf"), os.path.join(fdir, "Poppins-Medium.ttf"), "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]
    for p in paths:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                continue
    return ImageFont.load_default()

def _ct(d, t, y, f, fill):
    tw = d.textlength(t, font=f)
    d.text(((W - tw) / 2, y), t, fill=fill, font=f)

def _dash(d, x1, y, x2, fill=(200, 205, 215), w=2):
    x = x1
    while x < x2:
        d.line([(x, y), (min(x + 16, x2), y)], fill=fill, width=w)
        x += 26

def _holes(d, H, y_pct, color):
    cy = PAD + int((H - PAD * 2) * y_pct)
    r = 28
    d.ellipse([PAD - r, cy - r, PAD + r, cy + r], fill=color)
    d.ellipse([W - PAD - r, cy - r, W - PAD + r, cy + r], fill=color)

def _check(d, cx, cy, r):
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=GREEN)
    lw = max(10, r // 3)
    d.line([(cx - r*0.30, cy + r*0.05), (cx - r*0.02, cy + r*0.35), (cx + r*0.40, cy - r*0.30)], fill=WHITE, width=lw, joint="curve")

def _warning(d, cx, cy, r):
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=RED)
    f = _font(int(r * 1.2), bold=True)
    tw = d.textlength("!", font=f)
    d.text((cx - tw / 2, cy - r * 0.55), "!", fill=WHITE, font=f)

def _logo(d, y):
    cr = 36
    gap = 20
    f = _font(56, bold=True)
    tw = d.textlength("CIRCA", font=f)
    logo_w = cr * 2 + gap
    total = logo_w + 18 + tw
    sx = (W - total) / 2
    cx1 = sx + cr
    cy = y + cr
    d.ellipse([cx1 - cr, cy - cr, cx1 + cr, cy + cr], outline=BLUE, width=5)
    d.ellipse([cx1 + gap - cr, cy - cr, cx1 + gap + cr, cy + cr], outline=BLUE, width=5)
    d.text((sx + logo_w + 18, y - 4), "CIRCA", fill=BLACK, font=f)
    return y + cr * 2 + 20

def _row(d, y, label, value):
    lx = IP + 10
    rx = W - IP - 10
    _dash(d, lx, y, rx)
    y += 24
    d.text((lx, y), label, fill=MUTED, font=_font(34, bold=True))
    d.text((lx + 300, y), value, fill=BLACK, font=_font(34))
    return y + 60


def generate_account_activated_card(nombre, linea, distribuidor):
    H = 1560
    img = Image.new("RGB", (W, H), BLUE)
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((PAD, PAD, W - PAD, H - PAD), radius=32, fill=WHITE)
    _holes(d, H, 0.56, BLUE)

    y = PAD + 60
    y = _logo(d, y)
    y += 20
    _check(d, W // 2, y + 70, 70)
    y += 170
    _ct(d, "Cuenta activada!", y, _font(48, True), GREEN)
    y += 70
    _ct(d, nombre, y, _font(56, True), BLACK)
    y += 90
    d.line([(IP, y), (W - IP, y)], fill=LINE, width=2)
    y += 45
    _ct(d, "CREDITO DISPONIBLE", y, _font(32, True), BLUE)
    y += 55
    _ct(d, "S/ {:,.2f}".format(linea), y, _font(140, True), BLUE)
    y += 175
    y = _row(d, y, "Bodega", nombre)
    y = _row(d, y, "Distribuidor", distribuidor)
    y = _row(d, y, "Activada", datetime.now().strftime("%d %b %Y, %I:%M %p"))
    y += 20
    _dash(d, IP, y, W - IP, fill=BLUE, w=3)
    y += 30
    lx = IP + 10
    d.text((lx, y), "Compra hoy. Paga despues.", fill=GREEN, font=_font(30, True))
    y += 42
    d.text((lx, y), "7, 15 o 30 dias. Tu linea se renueva al pagar.", fill=MUTED, font=_font(26))

    buf = io.BytesIO()
    img.save(buf, format="PNG", quality=95)
    return buf.getvalue()


def generate_contract_signed_card(nombre, ruc, linea, contract_hash):
    H = 1300
    img = Image.new("RGB", (W, H), BLUE)
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((PAD, PAD, W - PAD, H - PAD), radius=32, fill=WHITE)
    _holes(d, H, 0.50, BLUE)

    y = PAD + 60
    y = _logo(d, y)
    y += 20
    _check(d, W // 2, y + 55, 58)
    y += 140
    _ct(d, "Contrato firmado", y, _font(48, True), GREEN)
    y += 65
    _ct(d, nombre, y, _font(50, True), BLACK)
    y += 80
    d.line([(IP, y), (W - IP, y)], fill=LINE, width=2)
    y += 35
    y = _row(d, y, "RUC", ruc)
    y = _row(d, y, "Credito", "S/ {:,.2f}".format(linea))
    y = _row(d, y, "Contrato", "Facilidad Financ. v2.0")
    y = _row(d, y, "Hash", (contract_hash[:16] if contract_hash else "---"))
    y += 20
    _dash(d, IP, y, W - IP, fill=BLUE, w=3)
    y += 30
    _ct(d, "Firmado: " + datetime.now().strftime("%d/%m/%Y %H:%M"), y, _font(28), MUTED)
    y += 40
    _ct(d, "Recibiras el contrato completo en PDF", y, _font(28), BLUE)

    buf = io.BytesIO()
    img.save(buf, format="PNG", quality=95)
    return buf.getvalue()


def generate_order_confirmed_card(numero, items_summary, monto, fee, total, dias, vencimiento, monto_productos=0):
    H = 1700
    img = Image.new("RGB", (W, H), BLUE)
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((PAD, PAD, W - PAD, H - PAD), radius=32, fill=WHITE)
    _holes(d, H, 0.45, BLUE)

    y = PAD + 60
    y = _logo(d, y)
    y += 20
    _check(d, W // 2, y + 65, 66)
    y += 160
    _ct(d, "Pedido confirmado!", y, _font(48, True), GREEN)
    y += 70
    _ct(d, numero, y, _font(64, True), BLACK)
    y += 95
    d.line([(IP, y), (W - IP, y)], fill=LINE, width=2)
    y += 45
    lbl = "TOTAL FINANCIADO" if dias > 0 else "TOTAL CONTADO"
    _ct(d, lbl, y, _font(32, True), GREEN)
    y += 55
    _ct(d, "S/ {:,.2f}".format(total), y, _font(120, True), BLACK)
    y += 160
    if monto_productos > 0:
        y = _row(d, y, "Total compra", "S/ {:.2f}".format(monto_productos))
    if dias > 0:
        y = _row(d, y, "Financiado", "S/ {:.2f}".format(monto))
        y = _row(d, y, "Fee ({}d)".format(dias), "S/ {:.2f}".format(fee))
        y = _row(d, y, "Plazo", "{} dias".format(dias))
        y = _row(d, y, "Vence", vencimiento)
    else:
        y = _row(d, y, "Total", "S/ {:.2f}".format(total))
        y = _row(d, y, "Entrega", "Tu distribuidor preparara tu pedido")
    y += 20
    _dash(d, IP, y, W - IP, fill=GREEN, w=3)
    y += 30
    lx = IP + 10
    if dias > 0:
        d.text((lx, y), "Paga por Yape o Plin al 986311567", fill=MUTED, font=_font(28))
        y += 40
    d.text((lx, y), "Recibiras actualizaciones por WhatsApp", fill=BLUE, font=_font(28))
    y += 50
    _ct(d, datetime.now().strftime("%d/%m/%Y %H:%M") + " | Circa", y, _font(26), MUTED)

    buf = io.BytesIO()
    img.save(buf, format="PNG", quality=95)
    return buf.getvalue()


def generate_payment_reminder_card(numero, monto_financiado, fee, total, dias, vencimiento):
    H = 1560
    img = Image.new("RGB", (W, H), BLUE)
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((PAD, PAD, W - PAD, H - PAD), radius=32, fill=WHITE)
    _holes(d, H, 0.48, BLUE)

    y = PAD + 60
    y = _logo(d, y)
    y += 20
    _warning(d, W // 2, y + 65, 66)
    y += 160
    _ct(d, "Recordatorio de pago", y, _font(48, True), RED)
    y += 80
    d.line([(IP, y), (W - IP, y)], fill=LINE, width=2)
    y += 45
    _ct(d, "TOTAL A PAGAR", y, _font(32, True), RED)
    y += 55
    _ct(d, "S/ {:,.2f}".format(total), y, _font(120, True), BLACK)
    y += 160
    y = _row(d, y, "Pedido", numero)
    y = _row(d, y, "Financiado", "S/ {:.2f}".format(monto_financiado))
    y = _row(d, y, "Fee", "S/ {:.2f}".format(fee))
    y = _row(d, y, "Plazo", "{} dias".format(dias))
    y = _row(d, y, "Vence", vencimiento)
    y += 20
    _dash(d, IP, y, W - IP, fill=RED, w=3)
    y += 30
    lx = IP + 10
    d.text((lx, y), "Paga por Yape o Plin al:", fill=BLACK, font=_font(30, True))
    y += 42
    d.text((lx, y), "986311567 — PALI SAC", fill=BLUE, font=_font(34, True))
    y += 50
    d.text((lx, y), "Despues de pagar, escribe YA PAGUE", fill=MUTED, font=_font(26))
    y += 50
    _ct(d, datetime.now().strftime("%d/%m/%Y %H:%M") + " | Circa", y, _font(26), MUTED)

    buf = io.BytesIO()
    img.save(buf, format="PNG", quality=95)
    return buf.getvalue()
