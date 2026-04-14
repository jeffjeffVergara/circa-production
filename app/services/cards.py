"""
Circa branded confirmation cards — Plin/Yape style.
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
GRAY_300 = (203, 213, 225)
GRAY_500 = (100, 116, 139)
GRAY_700 = (51, 65, 85)
BORDER = (226, 232, 240)

def _get_font(size, bold=False):
    paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    ]
    for fp in paths:
        if os.path.exists(fp):
            return ImageFont.truetype(fp, size)
    return ImageFont.load_default()

def _rounded_rect(draw, xy, radius, fill, outline=None):
    x1, y1, x2, y2 = xy
    draw.rectangle([x1+radius, y1, x2-radius, y2], fill=fill)
    draw.rectangle([x1, y1+radius, x2, y2-radius], fill=fill)
    for corner, angles in [((x1,y1),(180,270)),((x2-2*radius,y1),(270,360)),((x1,y2-2*radius),(90,180)),((x2-2*radius,y2-2*radius),(0,90))]:
        draw.pieslice([corner[0], corner[1], corner[0]+2*radius, corner[1]+2*radius], angles[0], angles[1], fill=fill)
    if outline:
        draw.rounded_rectangle(xy, radius, outline=outline, width=2)

def _draw_check(draw, cx, cy, r):
    draw.ellipse([cx-r, cy-r, cx+r, cy+r], fill=GREEN)
    lw = max(5, r//5)
    draw.line([(cx-r*0.35, cy+r*0.05), (cx-r*0.05, cy+r*0.35), (cx+r*0.4, cy-r*0.25)], fill=WHITE, width=lw)

def _ct(draw, text, y, font, fill, W):
    tw = draw.textlength(text, font=font)
    draw.text(((W - tw) / 2, y), text, fill=fill, font=font)

def _logo(img, draw, W, y=20, h=52):
    iso_path = os.path.join(os.path.dirname(__file__), "..", "static", "circa_isotipo.png")
    iso_w = 0
    if os.path.exists(iso_path):
        iso = Image.open(iso_path).convert("RGBA")
        iso_w = int(iso.width * h / iso.height)
        iso = iso.resize((iso_w, h), Image.LANCZOS)
        total_w = iso_w + 14 + draw.textlength("CIRCA", font=_get_font(38, True))
        start_x = int((W - total_w) / 2)
        img.paste(iso, (start_x, y), iso)
        draw.text((start_x + iso_w + 14, y + 6), "CIRCA", fill=CIRCA_DARK, font=_get_font(38, True))


def generate_account_activated_card(nombre, linea, distribuidor):
    W, H = 700, 560
    img = Image.new("RGB", (W, H), WHITE)
    draw = ImageDraw.Draw(img)
    draw.rectangle([0, 0, W, 7], fill=CIRCA_BLUE)
    _logo(img, draw, W, 20, 52)
    draw.line([50, 88, W-50, 88], fill=BORDER, width=1)
    _draw_check(draw, W//2, 150, 52)
    _ct(draw, "Cuenta activada", 218, _get_font(36, True), CIRCA_DARK, W)
    _ct(draw, "Clave creada con exito", 262, _get_font(20, True), GREEN, W)
    _rounded_rect(draw, (50, 302, W-50, 440), 18, BLUE_LIGHT, outline=CIRCA_BLUE)
    _ct(draw, "CREDITO DISPONIBLE", 316, _get_font(16, True), CIRCA_BLUE, W)
    _ct(draw, "S/ {:,.2f}".format(linea), 345, _get_font(58, True), CIRCA_DARK, W)
    _ct(draw, nombre, 412, _get_font(18, True), GRAY_700, W)
    _ct(draw, "Distribuidor: " + distribuidor, 438, _get_font(16), GRAY_500, W)
    draw.line([50, 465, W-50, 465], fill=BORDER, width=1)
    now = datetime.now()
    _ct(draw, now.strftime("%d/%m/%Y %H:%M") + " | Circa", 480, _get_font(14), GRAY_500, W)
    _ct(draw, "Compra hoy. Paga despues.", 502, _get_font(14), GRAY_500, W)
    draw.rectangle([0, H-6, W, H], fill=CIRCA_BLUE)
    buf = io.BytesIO()
    img.save(buf, format="PNG", quality=95)
    return buf.getvalue()


def generate_contract_signed_card(nombre, ruc, linea, contract_hash):
    W, H = 700, 540
    img = Image.new("RGB", (W, H), WHITE)
    draw = ImageDraw.Draw(img)
    draw.rectangle([0, 0, W, 7], fill=CIRCA_BLUE)
    _logo(img, draw, W, 20, 48)
    draw.line([50, 85, W-50, 85], fill=BORDER, width=1)
    _draw_check(draw, W//2, 140, 40)
    _ct(draw, "Contrato firmado", 195, _get_font(30, True), CIRCA_DARK, W)
    _rounded_rect(draw, (50, 240, W-50, 430), 16, GRAY_100, outline=BORDER)
    fl = _get_font(15)
    fv = _get_font(16, True)
    y = 260
    for label, value in [("Bodega", nombre), ("RUC", ruc), ("Credito aprobado", "S/ {:,.2f}".format(linea)), ("Contrato", "Facilidad de Financiamiento v2.0"), ("Hash", (contract_hash[:16] if contract_hash else "---"))]:
        draw.text((80, y), label, fill=GRAY_500, font=fl)
        draw.text((260, y), value, fill=CIRCA_DARK, font=fv)
        y += 34
    draw.line([50, 450, W-50, 450], fill=BORDER, width=1)
    now = datetime.now()
    _ct(draw, "Firmado: " + now.strftime("%d/%m/%Y %H:%M"), 465, _get_font(14), GRAY_500, W)
    _ct(draw, "Recibiras el contrato completo en PDF", 488, _get_font(14), CIRCA_BLUE, W)
    draw.rectangle([0, H-6, W, H], fill=CIRCA_BLUE)
    buf = io.BytesIO()
    img.save(buf, format="PNG", quality=95)
    return buf.getvalue()


def generate_order_confirmed_card(numero, items_summary, monto, fee, total, dias, vencimiento):
    W, H = 700, 560
    img = Image.new("RGB", (W, H), WHITE)
    draw = ImageDraw.Draw(img)
    draw.rectangle([0, 0, W, 7], fill=GREEN)
    _logo(img, draw, W, 18, 46)
    draw.line([50, 80, W-50, 80], fill=BORDER, width=1)
    _draw_check(draw, W//2, 135, 45)
    _ct(draw, "Pedido " + numero, 195, _get_font(32, True), CIRCA_DARK, W)
    _ct(draw, "CONFIRMADO", 235, _get_font(20, True), GREEN, W)
    _rounded_rect(draw, (50, 275, W-50, 405), 18, GREEN_LIGHT, outline=GREEN)
    if dias > 0:
        _ct(draw, "TOTAL FINANCIADO", 292, _get_font(15, True), GREEN, W)
    else:
        _ct(draw, "TOTAL CONTADO", 292, _get_font(15, True), GREEN, W)
    _ct(draw, "S/ {:,.2f}".format(total), 315, _get_font(52, True), CIRCA_DARK, W)
    if dias > 0:
        _ct(draw, "Monto: S/{:.2f}  |  Fee ({}d): S/{:.2f}".format(monto, dias, fee), 378, _get_font(14), GRAY_700, W)
    y = 425
    if dias > 0:
        _ct(draw, "Plazo: {} dias  |  Vence: {}".format(dias, vencimiento), y, _get_font(16), GRAY_700, W)
        y += 28
        _ct(draw, "Pago a Circa por Yape o Plin al 986311567", y, _get_font(15), GRAY_500, W)
        y += 28
    else:
        _ct(draw, "Tu distribuidor preparara tu pedido", y, _get_font(16), GRAY_700, W)
        y += 28
    _ct(draw, "Recibiras actualizaciones por WhatsApp", y, _get_font(15), CIRCA_BLUE, W)
    draw.line([50, H-60, W-50, H-60], fill=BORDER, width=1)
    now = datetime.now()
    _ct(draw, now.strftime("%d/%m/%Y %H:%M") + " | Circa", H-45, _get_font(13), GRAY_500, W)
    draw.rectangle([0, H-6, W, H], fill=GREEN)
    buf = io.BytesIO()
    img.save(buf, format="PNG", quality=95)
    return buf.getvalue()
