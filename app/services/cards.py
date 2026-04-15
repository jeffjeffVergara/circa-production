"""
Circa branded cards — ticket style matching HTML mockup.
Blue frame, white card, punch holes, large typography.
"""
import os, io, math
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont

# Colors matching the HTML
BLUE = (37, 99, 235)
GREEN = (22, 163, 74)
GREEN_LIGHT = (220, 252, 231)
WHITE = (255, 255, 255)
BLACK = (17, 17, 17)
MUTED = (107, 114, 128)
LINE = (229, 231, 235)
DASH_LINE = (209, 213, 219)
CARD_BG = WHITE
FRAME_BG = BLUE

def _f(size, bold=False):
    for fp in ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
               "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"]:
        if os.path.exists(fp): return ImageFont.truetype(fp, size)
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

def _dashed_line(d, x1, y, x2, fill=DASH_LINE, dash=12, gap=8):
    x = x1
    while x < x2:
        d.line([(x, y), (min(x+dash, x2), y)], fill=fill, width=2)
        x += dash + gap

def _punch_holes(d, W, H, y_pct=0.64, r=22):
    cy = int(H * y_pct)
    d.ellipse([-r, cy-r, r, cy+r], fill=FRAME_BG)
    d.ellipse([W-r, cy-r, W+r, cy+r], fill=FRAME_BG)

def _logo(img, d, W, y=40, h=70):
    p = os.path.join(os.path.dirname(__file__), "..", "static", "circa_isotipo.png")
    fl = _f(52, True)
    tw = d.textlength("CIRCA", font=fl)
    if os.path.exists(p):
        iso = Image.open(p).convert("RGBA")
        iw = int(iso.width * h / iso.height)
        iso = iso.resize((iw, h), Image.LANCZOS)
        total = iw + 18 + tw
        sx = int((W - total) / 2)
        img.paste(iso, (sx, y), iso)
        d.text((sx + iw + 18, y + 8), "CIRCA", fill=BLACK, font=fl)
    else:
        _ct(d, "CIRCA", y, fl, BLUE, W)

def _check(d, cx, cy, r=58):
    d.ellipse([cx-r, cy-r, cx+r, cy+r], fill=GREEN)
    lw = max(8, r//5)
    d.line([(cx-r*0.32, cy+r*0.05),(cx-r*0.05, cy+r*0.35),(cx+r*0.42, cy-r*0.3)], fill=WHITE, width=lw)


def generate_account_activated_card(nombre, linea, distribuidor):
    W, H = 1080, 1360
    PAD = 40
    CW, CH = W - PAD*2, H - PAD*2

    img = Image.new("RGB", (W, H), FRAME_BG)
    d = ImageDraw.Draw(img)
    _rr(d, (PAD, PAD, W-PAD, H-PAD), 36, CARD_BG)

    # Punch holes at ~64%
    _punch_holes(d, CW, CH, 0.58, 24)
    # Redraw punch on actual coords
    hole_y = PAD + int(CH * 0.58)
    d.ellipse([PAD-24, hole_y-24, PAD+24, hole_y+24], fill=FRAME_BG)
    d.ellipse([W-PAD-24, hole_y-24, W-PAD+24, hole_y+24], fill=FRAME_BG)

    cx = W // 2
    y = PAD + 50
    _logo(img, d, W, y, 70)
    y += 100

    _check(d, cx, y, 58)
    y += 80

    _ct(d, "Cuenta activada!", y, _f(36, True), GREEN, W)
    y += 55
    _ct(d, nombre, y, _f(44, True), BLACK, W)
    y += 70

    d.line([(PAD+50, y), (W-PAD-50, y)], fill=LINE, width=2)
    y += 30

    _ct(d, "CREDITO DISPONIBLE", y, _f(26, True), BLUE, W)
    y += 45

    amt = "S/ {:,.2f}".format(linea)
    _ct(d, amt, y, _f(96, True), BLUE, W)
    y += 130

    # Detail rows with emojis
    left = PAD + 70
    _dashed_line(d, left, y, W-PAD-70)
    y += 25
    d.text((left, y), "🏪", fill=BLACK, font=_f(28))
    d.text((left+50, y), "Bodega", fill=MUTED, font=_f(24, True))
    d.text((left+220, y), nombre, fill=BLACK, font=_f(24))
    y += 55

    _dashed_line(d, left, y, W-PAD-70)
    y += 25
    d.text((left, y), "🏢", fill=BLACK, font=_f(28))
    d.text((left+50, y), "Distribuidor", fill=MUTED, font=_f(24, True))
    d.text((left+220, y), distribuidor, fill=BLACK, font=_f(24))
    y += 55

    _dashed_line(d, left, y, W-PAD-70)
    y += 25
    now = datetime.now()
    d.text((left, y), "📅", fill=BLACK, font=_f(28))
    d.text((left+50, y), "Activada", fill=MUTED, font=_f(24, True))
    d.text((left+220, y), now.strftime("%d %b %Y, %H:%M"), fill=BLACK, font=_f(24))
    y += 70

    # Footer dashed blue line
    _dashed_line(d, PAD+50, y, W-PAD-50, fill=BLUE, dash=10, gap=8)
    y += 30
    d.text((left, y), "🛡️", fill=GREEN, font=_f(28))
    d.text((left+50, y), "Compra hoy. Paga despues.", fill=GREEN, font=_f(22, True))
    y += 35
    d.text((left+50, y), "7, 15 o 30 dias. Tu linea se renueva al pagar.", fill=MUTED, font=_f(20))

    buf = io.BytesIO()
    img.save(buf, format="PNG", quality=95)
    return buf.getvalue()


def generate_contract_signed_card(nombre, ruc, linea, contract_hash):
    W, H = 1080, 1200
    PAD = 40
    img = Image.new("RGB", (W, H), FRAME_BG)
    d = ImageDraw.Draw(img)
    _rr(d, (PAD, PAD, W-PAD, H-PAD), 36, CARD_BG)

    hole_y = PAD + int((H-PAD*2) * 0.55)
    d.ellipse([PAD-24, hole_y-24, PAD+24, hole_y+24], fill=FRAME_BG)
    d.ellipse([W-PAD-24, hole_y-24, W-PAD+24, hole_y+24], fill=FRAME_BG)

    cx = W // 2
    y = PAD + 50
    _logo(img, d, W, y, 65)
    y += 95
    _check(d, cx, y, 50)
    y += 70
    _ct(d, "Contrato firmado", y, _f(38, True), GREEN, W)
    y += 55
    _ct(d, nombre, y, _f(40, True), BLACK, W)
    y += 65

    d.line([(PAD+50, y), (W-PAD-50, y)], fill=LINE, width=2)
    y += 30

    left = PAD + 70
    rows = [
        ("📋", "RUC", ruc),
        ("💰", "Credito", "S/ {:,.2f}".format(linea)),
        ("📄", "Contrato", "Facilidad Financiamiento v2.0"),
        ("🔒", "Hash", (contract_hash[:16] if contract_hash else "---")),
    ]
    for emoji, label, value in rows:
        _dashed_line(d, left, y, W-PAD-70)
        y += 22
        d.text((left, y), emoji, fill=BLACK, font=_f(26))
        d.text((left+50, y), label, fill=MUTED, font=_f(22, True))
        d.text((left+220, y), value, fill=BLACK, font=_f(22))
        y += 50

    y += 20
    _dashed_line(d, PAD+50, y, W-PAD-50, fill=BLUE, dash=10, gap=8)
    y += 30
    now = datetime.now()
    _ct(d, "Firmado: " + now.strftime("%d/%m/%Y %H:%M"), y, _f(22), MUTED, W)
    y += 35
    _ct(d, "Recibiras el contrato completo en PDF", y, _f(22), BLUE, W)

    buf = io.BytesIO()
    img.save(buf, format="PNG", quality=95)
    return buf.getvalue()


def generate_order_confirmed_card(numero, items_summary, monto, fee, total, dias, vencimiento):
    W, H = 1080, 1360
    PAD = 40
    img = Image.new("RGB", (W, H), GREEN)
    d = ImageDraw.Draw(img)
    _rr(d, (PAD, PAD, W-PAD, H-PAD), 36, CARD_BG)

    hole_y = PAD + int((H-PAD*2) * 0.50)
    d.ellipse([PAD-24, hole_y-24, PAD+24, hole_y+24], fill=GREEN)
    d.ellipse([W-PAD-24, hole_y-24, W-PAD+24, hole_y+24], fill=GREEN)

    cx = W // 2
    y = PAD + 50
    _logo(img, d, W, y, 65)
    y += 95
    _check(d, cx, y, 55)
    y += 75

    _ct(d, "Pedido confirmado!", y, _f(36, True), GREEN, W)
    y += 50
    _ct(d, numero, y, _f(48, True), BLACK, W)
    y += 70

    d.line([(PAD+50, y), (W-PAD-50, y)], fill=LINE, width=2)
    y += 30

    if dias > 0:
        _ct(d, "TOTAL FINANCIADO", y, _f(24, True), GREEN, W)
    else:
        _ct(d, "TOTAL CONTADO", y, _f(24, True), GREEN, W)
    y += 40
    _ct(d, "S/ {:,.2f}".format(total), y, _f(88, True), BLACK, W)
    y += 115

    left = PAD + 70
    if dias > 0:
        rows = [
            ("💰", "Financiado", "S/ {:.2f}".format(monto)),
            ("📊", "Fee ({}d)".format(dias), "S/ {:.2f}".format(fee)),
            ("📅", "Plazo", "{} dias".format(dias)),
            ("⏰", "Vence", vencimiento),
        ]
    else:
        rows = [
            ("💰", "Total", "S/ {:.2f}".format(total)),
            ("🚚", "Entrega", "Tu distribuidor preparara tu pedido"),
        ]
    for emoji, label, value in rows:
        _dashed_line(d, left, y, W-PAD-70)
        y += 22
        d.text((left, y), emoji, fill=BLACK, font=_f(26))
        d.text((left+50, y), label, fill=MUTED, font=_f(22, True))
        d.text((left+250, y), value, fill=BLACK, font=_f(22, True))
        y += 50

    y += 20
    _dashed_line(d, PAD+50, y, W-PAD-50, fill=GREEN, dash=10, gap=8)
    y += 25
    if dias > 0:
        d.text((left, y), "📱", fill=GREEN, font=_f(26))
        d.text((left+50, y), "Paga por Yape o Plin al 986311567", fill=MUTED, font=_f(22))
        y += 40
    d.text((left, y), "📩", fill=GREEN, font=_f(26))
    d.text((left+50, y), "Recibiras actualizaciones por WhatsApp", fill=BLUE, font=_f(22))
    y += 50
    now = datetime.now()
    _ct(d, now.strftime("%d/%m/%Y %H:%M") + " | Circa", y, _f(20), MUTED, W)

    buf = io.BytesIO()
    img.save(buf, format="PNG", quality=95)
    return buf.getvalue()
