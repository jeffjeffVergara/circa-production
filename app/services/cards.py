"""
Circa branded confirmation cards — Plin/Yape style.
Clean, light backgrounds, large amounts, professional.
"""
import os
import io
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont

# Colors
WHITE = (255, 255, 255)
BG_LIGHT = (248, 250, 252)
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
RED_SOFT = (254, 226, 226)
ORANGE = (234, 88, 12)


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
    draw.pieslice([x1, y1, x1+2*radius, y1+2*radius], 180, 270, fill=fill)
    draw.pieslice([x2-2*radius, y1, x2, y1+2*radius], 270, 360, fill=fill)
    draw.pieslice([x1, y2-2*radius, x1+2*radius, y2], 90, 180, fill=fill)
    draw.pieslice([x2-2*radius, y2-2*radius, x2, y2], 0, 90, fill=fill)
    if outline:
        draw.arc([x1, y1, x1+2*radius, y1+2*radius], 180, 270, fill=outline, width=2)
        draw.arc([x2-2*radius, y1, x2, y1+2*radius], 270, 360, fill=outline, width=2)
        draw.arc([x1, y2-2*radius, x1+2*radius, y2], 90, 180, fill=outline, width=2)
        draw.arc([x2-2*radius, y2-2*radius, x2, y2], 0, 90, fill=outline, width=2)
        draw.line([x1+radius, y1, x2-radius, y1], fill=outline, width=2)
        draw.line([x1+radius, y2, x2-radius, y2], fill=outline, width=2)
        draw.line([x1, y1+radius, x1, y2-radius], fill=outline, width=2)
        draw.line([x2, y1+radius, x2, y2-radius], fill=outline, width=2)


def _draw_check_circle(draw, cx, cy, r):
    draw.ellipse([cx-r, cy-r, cx+r, cy+r], fill=GREEN)
    # White checkmark
    draw.line([(cx-r*0.35, cy), (cx-r*0.08, cy+r*0.3), (cx+r*0.4, cy-r*0.3)], fill=WHITE, width=max(4, r//6))


def _draw_circa_logo(draw, cx, y, size=20):
    font = _get_font(size, bold=True)
    tw = draw.textlength("CIRCA", font=font)
    draw.text((cx - tw//2, y), "CIRCA", fill=CIRCA_BLUE, font=font)


def _draw_isotipo(img, x, y, h=36):
    iso_path = os.path.join(os.path.dirname(__file__), "..", "static", "circa_isotipo.png")
    if os.path.exists(iso_path):
        iso = Image.open(iso_path).convert("RGBA")
        iso_w = int(iso.width * h / iso.height)
        iso = iso.resize((iso_w, h), Image.LANCZOS)
        img.paste(iso, (x, y), iso)
        return iso_w
    return 0


def _center_text(draw, text, y, font, fill, W):
    tw = draw.textlength(text, font=font)
    draw.text((W//2 - tw//2, y), text, fill=fill, font=font)


def generate_account_activated_card(nombre, linea, distribuidor):
    W, H = 650, 520
    img = Image.new("RGB", (W, H), WHITE)
    draw = ImageDraw.Draw(img)

    # Top blue bar
    draw.rectangle([0, 0, W, 6], fill=CIRCA_BLUE)

    # Isotipo + CIRCA centered
    iso_w = _draw_isotipo(img, W//2 - 70, 28, 32)
    f_logo = _get_font(24, bold=True)
    draw.text((W//2 - 70 + iso_w + 10, 30), "CIRCA", fill=CIRCA_DARK, font=f_logo)

    # Divider
    draw.line([60, 75, W-60, 75], fill=BORDER, width=1)

    # Green check circle
    _draw_check_circle(draw, W//2, 130, 40)

    # Title
    f_title = _get_font(28, bold=True)
    _center_text(draw, "Cuenta activada", 185, f_title, CIRCA_DARK, W)

    f_sub = _get_font(16)
    _center_text(draw, "Clave creada con exito", 220, f_sub, GREEN, W)

    # Name
    f_name = _get_font(18, bold=True)
    _center_text(draw, nombre, 255, f_name, GRAY_700, W)

    # Credit box
    _rounded_rect(draw, (60, 295, W-60, 420), 16, BLUE_LIGHT, outline=CIRCA_BLUE)

    f_label = _get_font(14)
    _center_text(draw, "CREDITO DISPONIBLE", 310, f_label, CIRCA_BLUE, W)

    f_amount = _get_font(48, bold=True)
    amount_str = f"S/ {linea:,.2f}"
    _center_text(draw, amount_str, 335, f_amount, CIRCA_DARK, W)

    f_dist = _get_font(14)
    _center_text(draw, f"Distribuidor: {distribuidor}", 395, f_dist, GRAY_500, W)

    # Footer
    draw.line([60, 440, W-60, 440], fill=BORDER, width=1)
    f_footer = _get_font(12)
    now = datetime.now()
    _center_text(draw, f"{now.strftime('%d/%m/%Y %H:%M')} | Circa", 455, f_footer, GRAY_500, W)
    _center_text(draw, "Compra hoy. Paga despues.", 475, f_footer, GRAY_500, W)

    # Bottom bar
    draw.rectangle([0, H-5, W, H], fill=CIRCA_BLUE)

    buf = io.BytesIO()
    img.save(buf, format="PNG", quality=95)
    return buf.getvalue()


def generate_contract_signed_card(nombre, ruc, linea, contract_hash):
    W, H = 650, 500
    img = Image.new("RGB", (W, H), WHITE)
    draw = ImageDraw.Draw(img)

    draw.rectangle([0, 0, W, 6], fill=CIRCA_BLUE)

    iso_w = _draw_isotipo(img, W//2 - 70, 28, 32)
    f_logo = _get_font(24, bold=True)
    draw.text((W//2 - 70 + iso_w + 10, 30), "CIRCA", fill=CIRCA_DARK, font=f_logo)

    draw.line([60, 75, W-60, 75], fill=BORDER, width=1)

    _draw_check_circle(draw, W//2, 125, 32)

    f_title = _get_font(24, bold=True)
    _center_text(draw, "Contrato firmado", 170, f_title, CIRCA_DARK, W)

    # Details box
    _rounded_rect(draw, (60, 210, W-60, 400), 14, GRAY_100, outline=BORDER)

    f_label = _get_font(13)
    f_value = _get_font(14, bold=True)
    y = 230
    details = [
        ("Bodega", nombre),
        ("RUC", ruc),
        ("Credito aprobado", f"S/ {linea:,.2f}"),
        ("Contrato", "Facilidad de Financiamiento v2.0"),
        ("Hash", contract_hash[:16] if contract_hash else "---"),
    ]
    for label, value in details:
        draw.text((85, y), label, fill=GRAY_500, font=f_label)
        draw.text((250, y), value, fill=CIRCA_DARK, font=f_value)
        y += 32

    # Footer
    draw.line([60, 415, W-60, 415], fill=BORDER, width=1)
    f_footer = _get_font(12)
    now = datetime.now()
    _center_text(draw, f"Firmado: {now.strftime('%d/%m/%Y %H:%M')}", 430, f_footer, GRAY_500, W)
    _center_text(draw, "Recibiras el contrato completo en PDF", 450, f_footer, CIRCA_BLUE, W)

    draw.rectangle([0, H-5, W, H], fill=CIRCA_BLUE)

    buf = io.BytesIO()
    img.save(buf, format="PNG", quality=95)
    return buf.getvalue()


def generate_order_confirmed_card(numero, items_summary, monto, fee, total, dias, vencimiento):
    W, H = 650, 520
    img = Image.new("RGB", (W, H), WHITE)
    draw = ImageDraw.Draw(img)

    # Top green bar (order = green theme)
    draw.rectangle([0, 0, W, 6], fill=GREEN)

    # Logo
    iso_w = _draw_isotipo(img, W//2 - 70, 24, 30)
    f_logo = _get_font(22, bold=True)
    draw.text((W//2 - 70 + iso_w + 10, 26), "CIRCA", fill=CIRCA_DARK, font=f_logo)

    draw.line([60, 68, W-60, 68], fill=BORDER, width=1)

    # Check + pedido
    _draw_check_circle(draw, W//2, 115, 35)

    f_title = _get_font(26, bold=True)
    _center_text(draw, f"Pedido {numero}", 160, f_title, CIRCA_DARK, W)

    f_status = _get_font(16, bold=True)
    _center_text(draw, "CONFIRMADO", 193, f_status, GREEN, W)

    # Amount box
    _rounded_rect(draw, (60, 230, W-60, 350), 16, GREEN_LIGHT, outline=GREEN)

    f_label2 = _get_font(13)
    if dias > 0:
        _center_text(draw, "TOTAL FINANCIADO", 248, f_label2, GREEN, W)
    else:
        _center_text(draw, "TOTAL CONTADO", 248, f_label2, GREEN, W)

    f_big = _get_font(44, bold=True)
    _center_text(draw, f"S/ {total:,.2f}", 270, f_big, CIRCA_DARK, W)

    if dias > 0:
        f_detail = _get_font(13)
        _center_text(draw, f"Monto: S/{monto:.2f}  |  Fee ({dias}d): S/{fee:.2f}", 325, f_detail, GRAY_700, W)

    # Details
    f_info = _get_font(14)
    y = 370
    if dias > 0:
        _center_text(draw, f"Plazo: {dias} dias  |  Vence: {vencimiento}", y, f_info, GRAY_700, W)
        y += 25
        _center_text(draw, "Pago a Circa por Yape o Plin al 986311567", y, f_info, GRAY_500, W)
        y += 25
    else:
        _center_text(draw, "Tu distribuidor preparara tu pedido", y, f_info, GRAY_700, W)
        y += 25

    f_tracking = _get_font(13)
    _center_text(draw, "Recibiras actualizaciones por WhatsApp", y, f_tracking, CIRCA_BLUE, W)

    # Footer
    draw.line([60, H-65, W-60, H-65], fill=BORDER, width=1)
    f_footer = _get_font(12)
    now = datetime.now()
    _center_text(draw, f"{now.strftime('%d/%m/%Y %H:%M')} | Circa", H-50, f_footer, GRAY_500, W)

    draw.rectangle([0, H-5, W, H], fill=GREEN)

    buf = io.BytesIO()
    img.save(buf, format="PNG", quality=95)
    return buf.getvalue()
