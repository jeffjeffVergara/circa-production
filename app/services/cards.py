"""
Circa branded cards — large canvas for WhatsApp readability.
"""
import os, io
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont

WHITE = (255, 255, 255)
CIRCA_BLUE = (37, 99, 235)
CIRCA_DARK = (15, 23, 42)
GREEN = (22, 163, 74)
GREEN_LIGHT = (220, 252, 231)
BLUE_LIGHT = (219, 234, 254)
GRAY_100 = (241, 245, 249)
GRAY_500 = (100, 116, 139)
GRAY_700 = (51, 65, 85)
BORDER = (226, 232, 240)

def _f(size, bold=False):
    for fp in ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
               "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"]:
        if os.path.exists(fp): return ImageFont.truetype(fp, size)
    return ImageFont.load_default()

def _rr(draw, xy, r, fill, outline=None):
    x1, y1, x2, y2 = xy
    draw.rectangle([x1+r, y1, x2-r, y2], fill=fill)
    draw.rectangle([x1, y1+r, x2, y2-r], fill=fill)
    for c, a in [((x1,y1),(180,270)),((x2-2*r,y1),(270,360)),((x1,y2-2*r),(90,180)),((x2-2*r,y2-2*r),(0,90))]:
        draw.pieslice([c[0],c[1],c[0]+2*r,c[1]+2*r], a[0], a[1], fill=fill)
    if outline:
        try: draw.rounded_rectangle(xy, r, outline=outline, width=3)
        except: pass

def _chk(draw, cx, cy, r):
    draw.ellipse([cx-r, cy-r, cx+r, cy+r], fill=GREEN)
    draw.line([(cx-r*0.35, cy+r*0.05),(cx-r*0.05, cy+r*0.35),(cx+r*0.4, cy-r*0.25)], fill=WHITE, width=max(7,r//4))

def _ct(d, t, y, f, c, W):
    tw = d.textlength(t, font=f)
    d.text(((W-tw)/2, y), t, fill=c, font=f)

def _logo(img, draw, W, y=30, h=72):
    p = os.path.join(os.path.dirname(__file__), "..", "static", "circa_isotipo.png")
    fl = _f(54, True)
    tw = draw.textlength("CIRCA", font=fl)
    if os.path.exists(p):
        iso = Image.open(p).convert("RGBA")
        iw = int(iso.width * h / iso.height)
        iso = iso.resize((iw, h), Image.LANCZOS)
        total = iw + 20 + tw
        sx = int((W - total) / 2)
        img.paste(iso, (sx, y), iso)
        draw.text((sx + iw + 20, y + 8), "CIRCA", fill=CIRCA_DARK, font=fl)
    else:
        draw.text(((W-tw)/2, y), "CIRCA", fill=CIRCA_BLUE, font=fl)


def generate_account_activated_card(nombre, linea, distribuidor):
    W, H = 1080, 880
    img = Image.new("RGB", (W, H), WHITE)
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, W, 10], fill=CIRCA_BLUE)
    _logo(img, d, W, 30, 72)
    d.line([70, 130, W-70, 130], fill=BORDER, width=2)
    _chk(d, W//2, 220, 75)
    _ct(d, "Cuenta activada", 320, _f(52, True), CIRCA_DARK, W)
    _ct(d, "Clave creada con exito", 385, _f(30, True), GREEN, W)
    _rr(d, (70, 445, W-70, 660), 24, BLUE_LIGHT, outline=CIRCA_BLUE)
    _ct(d, "CREDITO DISPONIBLE", 470, _f(24, True), CIRCA_BLUE, W)
    _ct(d, "S/ {:,.2f}".format(linea), 510, _f(84, True), CIRCA_DARK, W)
    _ct(d, nombre, 620, _f(26, True), GRAY_700, W)
    _ct(d, "Distribuidor: " + distribuidor, 660, _f(24), GRAY_500, W)
    d.line([70, 710, W-70, 710], fill=BORDER, width=2)
    now = datetime.now()
    _ct(d, now.strftime("%d/%m/%Y %H:%M") + " | Circa", 730, _f(22), GRAY_500, W)
    _ct(d, "Compra hoy. Paga despues.", 762, _f(22), GRAY_500, W)
    d.rectangle([0, H-8, W, H], fill=CIRCA_BLUE)
    buf = io.BytesIO()
    img.save(buf, format="PNG", quality=95)
    return buf.getvalue()


def generate_contract_signed_card(nombre, ruc, linea, contract_hash):
    W, H = 1080, 840
    img = Image.new("RGB", (W, H), WHITE)
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, W, 10], fill=CIRCA_BLUE)
    _logo(img, d, W, 28, 66)
    d.line([70, 125, W-70, 125], fill=BORDER, width=2)
    _chk(d, W//2, 210, 60)
    _ct(d, "Contrato firmado", 290, _f(44, True), CIRCA_DARK, W)
    _rr(d, (70, 360, W-70, 650), 20, GRAY_100, outline=BORDER)
    fl = _f(22)
    fv = _f(24, True)
    y = 390
    for label, value in [("Bodega", nombre), ("RUC", ruc), ("Credito aprobado", "S/ {:,.2f}".format(linea)), ("Contrato", "Facilidad de Financiamiento v2.0"), ("Hash", (contract_hash[:16] if contract_hash else "---"))]:
        d.text((110, y), label, fill=GRAY_500, font=fl)
        d.text((370, y), value, fill=CIRCA_DARK, font=fv)
        y += 50
    d.line([70, 675, W-70, 675], fill=BORDER, width=2)
    now = datetime.now()
    _ct(d, "Firmado: " + now.strftime("%d/%m/%Y %H:%M"), 700, _f(22), GRAY_500, W)
    _ct(d, "Recibiras el contrato completo en PDF", 735, _f(22), CIRCA_BLUE, W)
    d.rectangle([0, H-8, W, H], fill=CIRCA_BLUE)
    buf = io.BytesIO()
    img.save(buf, format="PNG", quality=95)
    return buf.getvalue()


def generate_order_confirmed_card(numero, items_summary, monto, fee, total, dias, vencimiento):
    W, H = 1080, 880
    img = Image.new("RGB", (W, H), WHITE)
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, W, 10], fill=GREEN)
    _logo(img, d, W, 26, 64)
    d.line([70, 120, W-70, 120], fill=BORDER, width=2)
    _chk(d, W//2, 205, 65)
    _ct(d, "Pedido " + numero, 290, _f(48, True), CIRCA_DARK, W)
    _ct(d, "CONFIRMADO", 350, _f(28, True), GREEN, W)
    _rr(d, (70, 405, W-70, 590), 24, GREEN_LIGHT, outline=GREEN)
    if dias > 0:
        _ct(d, "TOTAL FINANCIADO", 425, _f(22, True), GREEN, W)
    else:
        _ct(d, "TOTAL CONTADO", 425, _f(22, True), GREEN, W)
    _ct(d, "S/ {:,.2f}".format(total), 460, _f(76, True), CIRCA_DARK, W)
    if dias > 0:
        _ct(d, "Monto: S/{:.2f}  |  Fee ({}d): S/{:.2f}".format(monto, dias, fee), 560, _f(22), GRAY_700, W)
    y = 620
    if dias > 0:
        _ct(d, "Plazo: {} dias  |  Vence: {}".format(dias, vencimiento), y, _f(24), GRAY_700, W)
        y += 40
        _ct(d, "Pago a Circa por Yape o Plin al 986311567", y, _f(22), GRAY_500, W)
        y += 40
    else:
        _ct(d, "Tu distribuidor preparara tu pedido", y, _f(24), GRAY_700, W)
        y += 40
    _ct(d, "Recibiras actualizaciones por WhatsApp", y, _f(22), CIRCA_BLUE, W)
    d.line([70, H-80, W-70, H-80], fill=BORDER, width=2)
    now = datetime.now()
    _ct(d, now.strftime("%d/%m/%Y %H:%M") + " | Circa", H-60, _f(20), GRAY_500, W)
    d.rectangle([0, H-8, W, H], fill=GREEN)
    buf = io.BytesIO()
    img.save(buf, format="PNG", quality=95)
    return buf.getvalue()
