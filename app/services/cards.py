"""
Circa branded cards — ticket style, Inter font, no emojis.
"""
import os, io
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont

BLUE = (37, 99, 235)
GREEN = (22, 163, 74)
WHITE = (255, 255, 255)
BLACK = (17, 17, 17)
MUTED = (107, 114, 128)
LINE = (229, 231, 235)
DASH = (190, 198, 210)

FONTS_DIR = os.path.join(os.path.dirname(__file__), "..", "static", "fonts")

def _f(size, weight="regular"):
    names = {"black": "Inter.ttf", "bold": "Inter.ttf", "regular": "Inter.ttf"}
    p = os.path.join(FONTS_DIR, names.get(weight, "Inter-Regular.ttf"))
    if os.path.exists(p):
        return ImageFont.truetype(p, size)
    fb = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if weight != "regular" else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    if os.path.exists(fb):
        return ImageFont.truetype(fb, size)
    return ImageFont.load_default()

def _ct(d, t, y, font, fill, W):
    tw = d.textlength(t, font=font)
    d.text(((W-tw)/2, y), t, fill=fill, font=font)

def _rr(d, xy, r, fill):
    x1,y1,x2,y2 = xy
    d.rectangle([x1+r,y1,x2-r,y2], fill=fill)
    d.rectangle([x1,y1+r,x2,y2-r], fill=fill)
    for c,a in [((x1,y1),(180,270)),((x2-2*r,y1),(270,360)),((x1,y2-2*r),(90,180)),((x2-2*r,y2-2*r),(0,90))]:
        d.pieslice([c[0],c[1],c[0]+2*r,c[1]+2*r], a[0], a[1], fill=fill)

def _dash(d, x1, y, x2, fill=DASH, w=2):
    x = x1
    while x < x2:
        d.line([(x,y),(min(x+14,x2),y)], fill=fill, width=w)
        x += 22

def _holes(d, W, H, pad, y_pct, frame_color):
    cy = pad + int((H-pad*2) * y_pct)
    d.ellipse([pad-26, cy-26, pad+26, cy+26], fill=frame_color)
    d.ellipse([W-pad-26, cy-26, W-pad+26, cy+26], fill=frame_color)

def _check(d, cx, cy, r):
    d.ellipse([cx-r, cy-r, cx+r, cy+r], fill=GREEN)
    lw = max(8, r//4)
    pts = [(cx-r*0.32, cy+r*0.05), (cx-r*0.05, cy+r*0.35), (cx+r*0.42, cy-r*0.28)]
    d.line(pts, fill=WHITE, width=lw)

def _logo(img, d, W, y, h):
    p = os.path.join(os.path.dirname(__file__), "..", "static", "circa_isotipo.png")
    fl = _f(int(h*0.78), "black")
    tw = d.textlength("CIRCA", font=fl)
    if os.path.exists(p):
        iso = Image.open(p).convert("RGBA")
        iw = int(iso.width * h / iso.height)
        iso = iso.resize((iw, h), Image.LANCZOS)
        total = iw + 16 + tw
        sx = int((W - total) / 2)
        img.paste(iso, (sx, y), iso)
        d.text((sx + iw + 16, y + int(h*0.12)), "CIRCA", fill=BLACK, font=fl)
    else:
        _ct(d, "CIRCA", y, fl, BLUE, W)

def _detail_row(d, x, y, label, value, W, pad):
    _dash(d, x, y, W-pad-60)
    y += 20
    d.text((x, y), label, fill=MUTED, font=_f(26, "bold"))
    d.text((x + 240, y), value, fill=BLACK, font=_f(26))
    return y + 55


def generate_account_activated_card(nombre, linea, distribuidor):
    W, H = 1080, 1280
    P = 36
    img = Image.new("RGB", (W, H), BLUE)
    d = ImageDraw.Draw(img)
    _rr(d, (P, P, W-P, H-P), 32, WHITE)
    _holes(d, W, H, P, 0.57, BLUE)

    y = P + 55
    _logo(img, d, W, y, 80)
    y += 110

    _check(d, W//2, y, 64)
    y += 90

    _ct(d, "Cuenta activada!", y, _f(40, "bold"), GREEN, W)
    y += 60
    _ct(d, nombre, y, _f(46, "black"), BLACK, W)
    y += 75

    d.line([(P+55, y), (W-P-55, y)], fill=LINE, width=2)
    y += 40

    _ct(d, "CREDITO DISPONIBLE", y, _f(28, "black"), BLUE, W)
    y += 50
    amt = "S/ {:,.2f}".format(linea)
    _ct(d, amt, y, _f(100, "black"), BLUE, W)
    y += 130

    x = P + 70
    y = _detail_row(d, x, y, "Bodega", nombre, W, P)
    y = _detail_row(d, x, y, "Distribuidor", distribuidor, W, P)
    now = datetime.now()
    y = _detail_row(d, x, y, "Activada", now.strftime("%d %b %Y, %H:%M"), W, P)
    y += 15

    _dash(d, P+55, y, W-P-55, fill=BLUE, w=3)
    y += 30
    d.text((x, y), "Compra hoy. Paga despues.", fill=GREEN, font=_f(26, "bold"))
    y += 38
    d.text((x, y), "7, 15 o 30 dias. Tu linea se renueva al pagar.", fill=MUTED, font=_f(22))

    buf = io.BytesIO()
    img.save(buf, format="PNG", quality=95)
    return buf.getvalue()


def generate_contract_signed_card(nombre, ruc, linea, contract_hash):
    W, H = 1080, 1120
    P = 36
    img = Image.new("RGB", (W, H), BLUE)
    d = ImageDraw.Draw(img)
    _rr(d, (P, P, W-P, H-P), 32, WHITE)
    _holes(d, W, H, P, 0.52, BLUE)

    y = P + 55
    _logo(img, d, W, y, 72)
    y += 100
    _check(d, W//2, y, 52)
    y += 75
    _ct(d, "Contrato firmado", y, _f(40, "bold"), GREEN, W)
    y += 58
    _ct(d, nombre, y, _f(42, "black"), BLACK, W)
    y += 70

    d.line([(P+55, y), (W-P-55, y)], fill=LINE, width=2)
    y += 30

    x = P + 70
    y = _detail_row(d, x, y, "RUC", ruc, W, P)
    y = _detail_row(d, x, y, "Credito", "S/ {:,.2f}".format(linea), W, P)
    y = _detail_row(d, x, y, "Contrato", "Facilidad Financiamiento v2.0", W, P)
    y = _detail_row(d, x, y, "Hash", (contract_hash[:16] if contract_hash else "---"), W, P)
    y += 15

    _dash(d, P+55, y, W-P-55, fill=BLUE, w=3)
    y += 30
    now = datetime.now()
    _ct(d, "Firmado: " + now.strftime("%d/%m/%Y %H:%M"), y, _f(24), MUTED, W)
    y += 38
    _ct(d, "Recibiras el contrato completo en PDF", y, _f(24), BLUE, W)

    buf = io.BytesIO()
    img.save(buf, format="PNG", quality=95)
    return buf.getvalue()


def generate_order_confirmed_card(numero, items_summary, monto, fee, total, dias, vencimiento):
    W, H = 1080, 1300
    P = 36
    img = Image.new("RGB", (W, H), GREEN)
    d = ImageDraw.Draw(img)
    _rr(d, (P, P, W-P, H-P), 32, WHITE)
    _holes(d, W, H, P, 0.48, GREEN)

    y = P + 50
    _logo(img, d, W, y, 68)
    y += 95
    _check(d, W//2, y, 58)
    y += 80
    _ct(d, "Pedido confirmado!", y, _f(38, "bold"), GREEN, W)
    y += 55
    _ct(d, numero, y, _f(52, "black"), BLACK, W)
    y += 78

    d.line([(P+55, y), (W-P-55, y)], fill=LINE, width=2)
    y += 35

    lbl = "TOTAL FINANCIADO" if dias > 0 else "TOTAL CONTADO"
    _ct(d, lbl, y, _f(26, "black"), GREEN, W)
    y += 45
    _ct(d, "S/ {:,.2f}".format(total), y, _f(92, "black"), BLACK, W)
    y += 120

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

    _dash(d, P+55, y, W-P-55, fill=GREEN, w=3)
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
