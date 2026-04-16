"""
Circa branded cards — ticket style.
Brand colors: Blue #5B8AF5, Black #0D0D10, White #FFFFFF
Font: DejaVu (reliable on Railway python:3.12-slim)
"""
import os, io
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont

# Brand colors
BLUE = (91, 138, 245)       # #5B8AF5
BLACK = (13, 13, 16)        # #0D0D10
WHITE = (255, 255, 255)
GREEN = (22, 163, 74)       # #16A34A
AMBER = (217, 119, 6)       # #D97706
RED = (220, 38, 38)         # #DC2626
MUTED = (107, 114, 128)
LINE = (229, 231, 235)
DASH = (190, 198, 210)

def _f(size, weight="regular"):
    """Load font — DejaVu guaranteed on Railway."""
    if weight in ("black", "bold"):
        paths = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        ]
    else:
        paths = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        ]
    for p in paths:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                continue
    return ImageFont.load_default()

def _ct(d, t, y, font, fill, W):
    """Center text."""
    tw = d.textlength(t, font=font)
    d.text(((W - tw) / 2, y), t, fill=fill, font=font)

def _rr(d, xy, r, fill):
    """Rounded rectangle."""
    x1, y1, x2, y2 = xy
    d.rectangle([x1 + r, y1, x2 - r, y2], fill=fill)
    d.rectangle([x1, y1 + r, x2, y2 - r], fill=fill)
    for c, a in [((x1, y1), (180, 270)), ((x2 - 2*r, y1), (270, 360)),
                 ((x1, y2 - 2*r), (90, 180)), ((x2 - 2*r, y2 - 2*r), (0, 90))]:
        d.pieslice([c[0], c[1], c[0] + 2*r, c[1] + 2*r], a[0], a[1], fill=fill)

def _dash(d, x1, y, x2, fill=DASH, w=2):
    """Dashed line."""
    x = x1
    while x < x2:
        d.line([(x, y), (min(x + 14, x2), y)], fill=fill, width=w)
        x += 22

def _holes(d, W, H, pad, y_pct, frame_color):
    """Ticket punch holes."""
    cy = pad + int((H - pad * 2) * y_pct)
    d.ellipse([pad - 26, cy - 26, pad + 26, cy + 26], fill=frame_color)
    d.ellipse([W - pad - 26, cy - 26, W - pad + 26, cy + 26], fill=frame_color)

def _check(d, cx, cy, r):
    """Green checkmark circle."""
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=GREEN)
    lw = max(8, r // 4)
    pts = [(cx - r*0.32, cy + r*0.05), (cx - r*0.05, cy + r*0.35), (cx + r*0.42, cy - r*0.28)]
    d.line(pts, fill=WHITE, width=lw)

def _logo_text(d, W, y, h):
    """Draw CIRCA logo text centered."""
    fl = _f(int(h * 0.78), "black")
    # Draw two overlapping circles (isotipo)
    tw = d.textlength("CIRCA", font=fl)
    total_w = int(h * 1.2) + 16 + tw
    sx = int((W - total_w) / 2)
    cr = int(h * 0.4)
    cx1 = sx + cr
    cx2 = sx + int(h * 0.7)
    cy = y + int(h * 0.5)
    d.ellipse([cx1 - cr, cy - cr, cx1 + cr, cy + cr], outline=BLUE, width=5)
    d.ellipse([cx2 - cr, cy - cr, cx2 + cr, cy + cr], outline=BLUE, width=5)
    d.text((sx + int(h * 1.2) + 16, y + int(h * 0.12)), "CIRCA", fill=BLACK, font=fl)

def _detail_row(d, x, y, label, value, W, pad):
    """Detail row with dashed separator."""
    _dash(d, x, y, W - pad - 60)
    y += 22
    d.text((x, y), label, fill=MUTED, font=_f(32, "bold"))
    d.text((x + 280, y), value, fill=BLACK, font=_f(32))
    return y + 65


def generate_account_activated_card(nombre, linea, distribuidor):
    """Card 1: Cuenta activada — blue frame."""
    W, H = 1080, 1480
    P = 36
    img = Image.new("RGB", (W, H), BLUE)
    d = ImageDraw.Draw(img)
    _rr(d, (P, P, W - P, H - P), 32, WHITE)
    _holes(d, W, H, P, 0.57, BLUE)

    y = P + 55
    _logo_text(d, W, y, 100)
    y += 140
    _check(d, W // 2, y, 80)
    y += 110
    _ct(d, "Cuenta activada!", y, _f(52, "bold"), GREEN, W)
    y += 75
    _ct(d, nombre, y, _f(60, "black"), BLACK, W)
    y += 90

    d.line([(P + 55, y), (W - P - 55, y)], fill=LINE, width=2)
    y += 45
    _ct(d, "CREDITO DISPONIBLE", y, _f(34, "black"), BLUE, W)
    y += 55
    amt = "S/ {:,.2f}".format(linea)
    _ct(d, amt, y, _f(130, "black"), BLUE, W)
    y += 165

    x = P + 70
    y = _detail_row(d, x, y, "Bodega", nombre, W, P)
    y = _detail_row(d, x, y, "Distribuidor", distribuidor, W, P)
    now = datetime.now()
    y = _detail_row(d, x, y, "Activada", now.strftime("%d %b %Y, %H:%M"), W, P)
    y += 15

    _dash(d, P + 55, y, W - P - 55, fill=BLUE, w=3)
    y += 30
    d.text((x, y), "Compra hoy. Paga despues.", fill=GREEN, font=_f(26, "bold"))
    y += 38
    d.text((x, y), "7, 15 o 30 dias. Tu linea se renueva al pagar.", fill=MUTED, font=_f(22))

    buf = io.BytesIO()
    img.save(buf, format="PNG", quality=95)
    return buf.getvalue()


def generate_contract_signed_card(nombre, ruc, linea, contract_hash):
    """Card: Contrato firmado — blue frame."""
    W, H = 1080, 1120
    P = 36
    img = Image.new("RGB", (W, H), BLUE)
    d = ImageDraw.Draw(img)
    _rr(d, (P, P, W - P, H - P), 32, WHITE)
    _holes(d, W, H, P, 0.52, BLUE)

    y = P + 55
    _logo_text(d, W, y, 72)
    y += 100
    _check(d, W // 2, y, 52)
    y += 75
    _ct(d, "Contrato firmado", y, _f(40, "bold"), GREEN, W)
    y += 58
    _ct(d, nombre, y, _f(42, "black"), BLACK, W)
    y += 70

    d.line([(P + 55, y), (W - P - 55, y)], fill=LINE, width=2)
    y += 30

    x = P + 70
    y = _detail_row(d, x, y, "RUC", ruc, W, P)
    y = _detail_row(d, x, y, "Credito", "S/ {:,.2f}".format(linea), W, P)
    y = _detail_row(d, x, y, "Contrato", "Facilidad Financiamiento v2.0", W, P)
    y = _detail_row(d, x, y, "Hash", (contract_hash[:16] if contract_hash else "---"), W, P)
    y += 15

    _dash(d, P + 55, y, W - P - 55, fill=BLUE, w=3)
    y += 30
    now = datetime.now()
    _ct(d, "Firmado: " + now.strftime("%d/%m/%Y %H:%M"), y, _f(24), MUTED, W)
    y += 38
    _ct(d, "Recibiras el contrato completo en PDF", y, _f(24), BLUE, W)

    buf = io.BytesIO()
    img.save(buf, format="PNG", quality=95)
    return buf.getvalue()


def generate_order_confirmed_card(numero, items_summary, monto, fee, total, dias, vencimiento):
    """Card 2: Pedido confirmado — green frame."""
    W, H = 1080, 1520
    P = 36
    img = Image.new("RGB", (W, H), GREEN)
    d = ImageDraw.Draw(img)
    _rr(d, (P, P, W - P, H - P), 32, WHITE)
    _holes(d, W, H, P, 0.48, GREEN)

    y = P + 50
    _logo_text(d, W, y, 100)
    y += 140
    _check(d, W // 2, y, 80)
    y += 110
    _ct(d, "Pedido confirmado!", y, _f(52, "bold"), GREEN, W)
    y += 75
    _ct(d, numero, y, _f(68, "black"), BLACK, W)
    y += 100

    d.line([(P + 55, y), (W - P - 55, y)], fill=LINE, width=2)
    y += 45
    lbl = "TOTAL FINANCIADO" if dias > 0 else "TOTAL CONTADO"
    _ct(d, lbl, y, _f(34, "black"), GREEN, W)
    y += 55
    _ct(d, "S/ {:,.2f}".format(total), y, _f(120, "black"), BLACK, W)
    y += 155

    x = P + 70
    if dias > 0:
        y = _detail_row(d, x, y, "Financiado", "S/ {:.2f}".format(monto), W, P)
        y = _detail_row(d, x, y, "Fee ({}d)".format(dias), "S/ {:.2f}".format(fee), W, P)
        y = _detail_row(d, x, y, "Plazo", "{} dias".format(dias), W, P)
        y = _detail_row(d, x, y, "Vence", vencimiento, W, P)
    else:
        y = _detail_row(d, x, y, "Total", "S/ {:.2f}".format(total), W, P)
        y = _detail_row(d, x, y, "Entrega", "Tu distribuidor preparara tu pedido", W, P)
    y += 15

    _dash(d, P + 55, y, W - P - 55, fill=GREEN, w=3)
    y += 28
    if dias > 0:
        d.text((x, y), "Paga por Yape o Plin al 986311567", fill=MUTED, font=_f(24))
        y += 38
    d.text((x, y), "Recibiras actualizaciones por WhatsApp", fill=BLUE, font=_f(24))
    y += 45
    now = datetime.now()
    _ct(d, now.strftime("%d/%m/%Y %H:%M") + " | Circa", y, _f(22), MUTED, W)

    buf = io.BytesIO()
    img.save(buf, format="PNG", quality=95)
    return buf.getvalue()


def generate_payment_reminder_card(numero, monto_financiado, fee, total, dias, vencimiento):
    """Card 3: Recordatorio de pago — black frame."""
    W, H = 1080, 1480
    P = 36
    img = Image.new("RGB", (W, H), BLACK)
    d = ImageDraw.Draw(img)
    _rr(d, (P, P, W - P, H - P), 32, WHITE)
    _holes(d, W, H, P, 0.50, BLACK)

    y = P + 50
    _logo_text(d, W, y, 100)
    y += 140

    # Warning icon (circle with !)
    cx, cy = W // 2, y
    r = 70
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=RED)
    ef = _f(60, "black")
    tw = d.textlength("!", font=ef)
    d.text(((W - tw) / 2, cy - 34), "!", fill=WHITE, font=ef)
    y += 80

    _ct(d, "Recordatorio de pago", y, _f(52, "bold"), RED, W)
    y += 80

    d.line([(P + 55, y), (W - P - 55, y)], fill=LINE, width=2)
    y += 45

    _ct(d, "TOTAL A PAGAR", y, _f(34, "black"), RED, W)
    y += 55
    _ct(d, "S/ {:,.2f}".format(total), y, _f(120, "black"), BLACK, W)
    y += 155

    x = P + 70
    y = _detail_row(d, x, y, "Pedido", numero, W, P)
    y = _detail_row(d, x, y, "Financiado", "S/ {:.2f}".format(monto_financiado), W, P)
    y = _detail_row(d, x, y, "Fee", "S/ {:.2f}".format(fee), W, P)
    y = _detail_row(d, x, y, "Plazo", "{} dias".format(dias), W, P)
    y = _detail_row(d, x, y, "Vence", vencimiento, W, P)
    y += 15

    _dash(d, P + 55, y, W - P - 55, fill=RED, w=3)
    y += 28
    d.text((x, y), "Paga por Yape o Plin al:", fill=BLACK, font=_f(24, "bold"))
    y += 38
    d.text((x, y), "986311567 — PALI SAC", fill=BLUE, font=_f(28, "bold"))
    y += 45
    d.text((x, y), "Despues de pagar, escribe YA PAGUE", fill=MUTED, font=_f(22))
    y += 45
    now = datetime.now()
    _ct(d, now.strftime("%d/%m/%Y %H:%M") + " | Circa", y, _f(22), MUTED, W)

    buf = io.BytesIO()
    img.save(buf, format="PNG", quality=95)
    return buf.getvalue()
