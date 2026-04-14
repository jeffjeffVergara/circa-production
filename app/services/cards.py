"""
Circa branded confirmation cards — sent as images in WhatsApp.
Uses PIL to generate clean, branded cards.
"""
import os
import io
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont

# Circa brand colors
CIRCA_BLUE = (74, 144, 217)
CIRCA_DARK = (26, 26, 46)
WHITE = (255, 255, 255)
LIGHT_GRAY = (245, 248, 250)
GREEN_CHECK = (34, 197, 94)
TEXT_DARK = (34, 34, 34)
TEXT_GRAY = (120, 120, 120)


def _get_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    """Get font — use system fonts available on Railway (Linux)."""
    font_paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    ]
    for fp in font_paths:
        if os.path.exists(fp):
            return ImageFont.truetype(fp, size)
    return ImageFont.load_default()


def _draw_rounded_rect(draw, xy, radius, fill):
    """Draw a rounded rectangle."""
    x1, y1, x2, y2 = xy
    draw.rectangle([x1 + radius, y1, x2 - radius, y2], fill=fill)
    draw.rectangle([x1, y1 + radius, x2, y2 - radius], fill=fill)
    draw.pieslice([x1, y1, x1 + 2*radius, y1 + 2*radius], 180, 270, fill=fill)
    draw.pieslice([x2 - 2*radius, y1, x2, y1 + 2*radius], 270, 360, fill=fill)
    draw.pieslice([x1, y2 - 2*radius, x1 + 2*radius, y2], 90, 180, fill=fill)
    draw.pieslice([x2 - 2*radius, y2 - 2*radius, x2, y2], 0, 90, fill=fill)


def generate_account_activated_card(nombre: str, linea: float, distribuidor: str) -> bytes:
    """Generate account activation confirmation card."""
    W, H = 600, 500
    img = Image.new("RGB", (W, H), CIRCA_DARK)
    draw = ImageDraw.Draw(img)
    
    # Top accent bar
    draw.rectangle([0, 0, W, 6], fill=CIRCA_BLUE)
    
    # Circa logo text
    font_logo = _get_font(28, bold=True)
    draw.text((30, 25), "CIRCA", fill=CIRCA_BLUE, font=font_logo)
    
    # Check circle
    cx, cy, cr = W//2, 120, 35
    draw.ellipse([cx-cr, cy-cr, cx+cr, cy+cr], fill=GREEN_CHECK)
    font_check = _get_font(40, bold=True)
    cw = draw.textlength("\u2713", font=font_check)
    draw.text((cx - cw//2, cy - 22), "\u2713", fill=WHITE, font=font_check)
    
    # Title
    font_title = _get_font(26, bold=True)
    title = "Cuenta activada"
    tw = draw.textlength(title, font=font_title)
    draw.text((W//2 - tw//2, 170), title, fill=WHITE, font=font_title)
    
    # Bodega name
    font_name = _get_font(18)
    nw = draw.textlength(nombre, font=font_name)
    draw.text((W//2 - nw//2, 210), nombre, fill=TEXT_GRAY, font=font_name)
    
    # Credit amount card
    _draw_rounded_rect(draw, (60, 250, W-60, 370), 15, CIRCA_BLUE)
    font_label = _get_font(16)
    font_amount = _get_font(42, bold=True)
    
    label = "Credito disponible"
    lw = draw.textlength(label, font=font_label)
    draw.text((W//2 - lw//2, 265), label, fill=(200, 220, 255), font=font_label)
    
    amount_str = f"S/{linea:,.2f}"
    aw = draw.textlength(amount_str, font=font_amount)
    draw.text((W//2 - aw//2, 295), amount_str, fill=WHITE, font=font_amount)
    
    # Distribuidor
    font_small = _get_font(14)
    dist_text = f"Distribuidor: {distribuidor}"
    dw = draw.textlength(dist_text, font=font_small)
    draw.text((W//2 - dw//2, 345), dist_text, fill=(180, 200, 230), font=font_small)
    
    # Footer
    font_footer = _get_font(13)
    now = datetime.now()
    footer = f"{now.strftime('%d/%m/%Y %H:%M')} | Circa"
    fw = draw.textlength(footer, font=font_footer)
    draw.text((W//2 - fw//2, 400), footer, fill=TEXT_GRAY, font=font_footer)
    
    # Bottom line
    draw.rectangle([60, 440, W-60, 441], fill=(60, 60, 80))
    font_tiny = _get_font(11)
    legal = "Pide mercaderia y paga despues. Tu credito se renueva al pagar."
    legw = draw.textlength(legal, font=font_tiny)
    draw.text((W//2 - legw//2, 455), legal, fill=TEXT_GRAY, font=font_tiny)
    
    buf = io.BytesIO()
    img.save(buf, format="PNG", quality=95)
    return buf.getvalue()


def generate_contract_signed_card(nombre: str, ruc: str, linea: float, contract_hash: str) -> bytes:
    """Generate contract signed confirmation card."""
    W, H = 600, 480
    img = Image.new("RGB", (W, H), CIRCA_DARK)
    draw = ImageDraw.Draw(img)
    
    draw.rectangle([0, 0, W, 6], fill=CIRCA_BLUE)
    
    font_logo = _get_font(28, bold=True)
    draw.text((30, 25), "CIRCA", fill=CIRCA_BLUE, font=font_logo)
    
    # Check
    cx, cy, cr = W//2, 110, 30
    draw.ellipse([cx-cr, cy-cr, cx+cr, cy+cr], fill=GREEN_CHECK)
    font_check = _get_font(34, bold=True)
    cw = draw.textlength("\u2713", font=font_check)
    draw.text((cx - cw//2, cy - 19), "\u2713", fill=WHITE, font=font_check)
    
    # Title
    font_title = _get_font(22, bold=True)
    title = "Contrato firmado digitalmente"
    tw = draw.textlength(title, font=font_title)
    draw.text((W//2 - tw//2, 155), title, fill=WHITE, font=font_title)
    
    # Details box
    _draw_rounded_rect(draw, (50, 200, W-50, 390), 12, (35, 35, 55))
    
    font_detail = _get_font(15)
    font_value = _get_font(15, bold=True)
    y = 220
    details = [
        ("Bodega:", nombre),
        ("RUC:", ruc),
        ("Credito aprobado:", f"S/{linea:,.2f}"),
        ("Contrato:", "Facilidad de Financiamiento Circa v2.0"),
        ("Hash:", contract_hash[:16] if contract_hash else "---"),
    ]
    for label, value in details:
        draw.text((75, y), label, fill=TEXT_GRAY, font=font_detail)
        draw.text((240, y), value, fill=WHITE, font=font_value)
        y += 32
    
    # Footer
    font_footer = _get_font(13)
    now = datetime.now()
    draw.text((75, 400), f"Firmado: {now.strftime('%d/%m/%Y %H:%M')}", fill=TEXT_GRAY, font=font_footer)
    draw.text((75, 420), "Recibiras el contrato completo en PDF", fill=CIRCA_BLUE, font=font_footer)
    
    # Bottom bar
    draw.rectangle([0, H-4, W, H], fill=CIRCA_BLUE)
    
    buf = io.BytesIO()
    img.save(buf, format="PNG", quality=95)
    return buf.getvalue()


def generate_order_confirmed_card(numero: str, items_summary: str, 
                                   monto: float, fee: float, total: float,
                                   dias: int, vencimiento: str) -> bytes:
    """Generate order confirmation card."""
    W, H = 600, 420
    img = Image.new("RGB", (W, H), CIRCA_DARK)
    draw = ImageDraw.Draw(img)
    
    draw.rectangle([0, 0, W, 6], fill=CIRCA_BLUE)
    
    font_logo = _get_font(28, bold=True)
    draw.text((30, 25), "CIRCA", fill=CIRCA_BLUE, font=font_logo)
    
    # Check + order number
    cx, cy, cr = 55, 90, 22
    draw.ellipse([cx-cr, cy-cr, cx+cr, cy+cr], fill=GREEN_CHECK)
    font_check = _get_font(26, bold=True)
    cw = draw.textlength("\u2713", font=font_check)
    draw.text((cx - cw//2, cy - 15), "\u2713", fill=WHITE, font=font_check)
    
    font_title = _get_font(22, bold=True)
    draw.text((90, 78), f"Pedido {numero} confirmado", fill=WHITE, font=font_title)
    
    # Amount box
    _draw_rounded_rect(draw, (40, 130, W-40, 260), 12, CIRCA_BLUE)
    
    font_amt_label = _get_font(14)
    font_amt = _get_font(36, bold=True)
    font_detail = _get_font(14)
    
    draw.text((70, 145), "Total financiado", fill=(200, 220, 255), font=font_amt_label)
    draw.text((70, 170), f"S/{total:,.2f}", fill=WHITE, font=font_amt)
    
    draw.text((70, 220), f"Monto: S/{monto:.2f}  |  Fee ({dias}d): S/{fee:.2f}", fill=(200, 220, 255), font=font_detail)
    
    # Details
    font_info = _get_font(15)
    draw.text((70, 280), f"Plazo: {dias} dias  |  Vence: {vencimiento}", fill=TEXT_GRAY, font=font_info)
    draw.text((70, 310), "Pago a Circa por Yape o Plin", fill=TEXT_GRAY, font=font_info)
    draw.text((70, 340), "Recibiras actualizaciones por WhatsApp", fill=CIRCA_BLUE, font=font_info)
    
    # Footer
    font_footer = _get_font(12)
    now = datetime.now()
    draw.text((70, 380), f"{now.strftime('%d/%m/%Y %H:%M')} | Circa", fill=TEXT_GRAY, font=font_footer)
    
    draw.rectangle([0, H-4, W, H], fill=CIRCA_BLUE)
    
    buf = io.BytesIO()
    img.save(buf, format="PNG", quality=95)
    return buf.getvalue()
