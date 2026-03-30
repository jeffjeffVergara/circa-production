"""
Circa Financing Engine — Fee Calculation, Eligibility & Line Management.

Core rules:
- Cart can exceed credit line (excess paid cash on delivery)
- Partial financing: 100%, 50%, 25% of financeable amount
- Fee = simple interest (principal × rate), single payment at maturity
- Revolving line: restored when loan is paid
- Financeable amount = min(cart_total, available_line)
"""
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
import logging

logger = logging.getLogger("circa.financing")

# ── Fee table (configurable) ──
# plazo_dias → tasa (as decimal, e.g., 0.05 = 5%)
DEFAULT_FEE_TABLE = {
    7: Decimal("0.05"),    # 5%
    15: Decimal("0.08"),   # 8%
    30: Decimal("0.12"),   # 12%
}


def calculate_eligibility(cart_total: float, linea_disponible: float) -> dict:
    """
    Calculate how much can be financed and how much is cash.
    
    Returns:
        {
            "cart_total": 970.40,
            "linea_disponible": 500.00,
            "financiable_max": 500.00,   # min(cart, line)
            "contado_min": 470.40,       # cart - financiable
            "opciones": [
                {"pct": 100, "monto": 500.00, "contado": 470.40},
                {"pct": 50,  "monto": 250.00, "contado": 720.40},
                {"pct": 25,  "monto": 125.00, "contado": 845.40},
            ]
        }
    """
    cart = Decimal(str(cart_total))
    linea = Decimal(str(linea_disponible))
    financiable = min(cart, linea)
    
    opciones = []
    for pct in [100, 50, 25]:
        monto = (financiable * pct / 100).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        contado = (cart - monto).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        opciones.append({
            "pct": pct,
            "monto": float(monto),
            "contado": float(contado),
            "label": f"{pct}% — S/{monto:.2f}",
        })
    
    return {
        "cart_total": float(cart),
        "linea_disponible": float(linea),
        "financiable_max": float(financiable),
        "contado_min": float(cart - financiable),
        "opciones": opciones,
    }


def calculate_quote(monto_financiar: float, fee_table: dict = None) -> dict:
    """
    Calculate fee quotes for all available terms.
    
    Returns:
        {
            "monto": 250.00,
            "plazos": [
                {"dias": 7,  "tasa": 0.05, "fee": 12.50, "total": 262.50, "vencimiento": "2026-04-06"},
                {"dias": 15, "tasa": 0.08, "fee": 20.00, "total": 270.00, "vencimiento": "2026-04-14"},
                {"dias": 30, "tasa": 0.12, "fee": 30.00, "total": 280.00, "vencimiento": "2026-04-29"},
            ]
        }
    """
    table = fee_table or DEFAULT_FEE_TABLE
    monto = Decimal(str(monto_financiar))
    hoy = date.today()
    
    plazos = []
    for dias, tasa in sorted(table.items()):
        fee = (monto * tasa).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        total = monto + fee
        venc = hoy + timedelta(days=dias)
        
        plazos.append({
            "dias": dias,
            "tasa": float(tasa),
            "tasa_pct": f"{float(tasa) * 100:.1f}%",
            "fee": float(fee),
            "total": float(total),
            "vencimiento": venc.isoformat(),
            "vencimiento_label": venc.strftime("%d %b"),
            "label": f"{dias} días — Fee S/{fee:.2f} — Total S/{total:.2f}",
        })
    
    return {
        "monto": float(monto),
        "plazos": plazos,
    }


def calculate_summary(cart_total: float, monto_financiar: float, plazo_dias: int, fee_table: dict = None) -> dict:
    """
    Calculate the final summary for order confirmation.
    
    Returns:
        {
            "pedido_total": 970.40,
            "monto_financiado": 250.00,
            "tasa": 0.05,
            "plazo_dias": 7,
            "fee": 12.50,
            "total_credito": 262.50,
            "vencimiento": "2026-04-06",
            "pago_contado": 720.40,
        }
    """
    table = fee_table or DEFAULT_FEE_TABLE
    cart = Decimal(str(cart_total))
    monto = Decimal(str(monto_financiar))
    tasa = table.get(plazo_dias, Decimal("0.12"))
    fee = (monto * tasa).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    total_credito = monto + fee
    contado = cart - monto
    venc = date.today() + timedelta(days=plazo_dias)
    
    return {
        "pedido_total": float(cart),
        "monto_financiado": float(monto),
        "tasa": float(tasa),
        "tasa_pct": f"{float(tasa) * 100:.1f}%",
        "plazo_dias": plazo_dias,
        "fee": float(fee),
        "total_credito": float(total_credito),
        "vencimiento": venc.isoformat(),
        "vencimiento_label": venc.strftime("%d %b %Y"),
        "pago_contado": float(contado),
    }


def generate_reminders_schedule(vencimiento: date) -> list[dict]:
    """
    Generate payment reminder schedule.
    
    Returns list of:
        {"tipo": "d5", "dias_antes": 5, "fecha": "2026-04-01", "enviado": False}
    """
    schedule = [
        ("d5", 5),    # 5 días antes
        ("d3", 3),    # 3 días antes
        ("d1", 1),    # 1 día antes
        ("d0", 0),    # Día de vencimiento
        ("d_1", -1),  # 1 día después (vencido)
        ("d_3", -3),  # 3 días después
        ("d_7", -7),  # 7 días después
    ]
    
    return [
        {
            "tipo": tipo,
            "dias_antes": dias,
            "fecha": (vencimiento - timedelta(days=dias)).isoformat(),
            "enviado": False,
        }
        for tipo, dias in schedule
    ]
