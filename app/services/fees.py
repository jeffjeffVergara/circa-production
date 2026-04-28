"""
Circa fee calculation — flat rates by term, minimum S/3.00.

Rates (per contract Contrato_Circa_vsrev.docx):
  7 días  → 3%
  15 días → 5%
  30 días → 7%

Minimum fee: S/3.00
"""

FEE_TABLE = {
    7:  0.03,   # 3%
    15: 0.05,   # 5%
    30: 0.07,   # 7%
}

MIN_FEE = 3.00


def get_fee_rate(amount: float, days: int) -> float:
    """Return flat rate for the given term. Defaults to 7% if unknown term."""
    return FEE_TABLE.get(days, 0.07)


def calculate_fee(amount: float, days: int) -> dict:
    """Calculate fee for a given amount and term, enforcing minimum S/3."""
    rate = get_fee_rate(amount, days)
    fee = round(amount * rate, 2)
    fee = max(fee, MIN_FEE)
    total = round(amount + fee, 2)
    return {
        "rate": rate,
        "rate_pct": f"{rate * 100:.1f}%",
        "fee": fee,
        "total": total,
        "amount": amount,
        "days": days,
    }


def get_all_term_options(amount: float) -> list[dict]:
    """Return fee quotes for all 3 terms (7, 15, 30 days)."""
    return [calculate_fee(amount, d) for d in [7, 15, 30]]


def get_finance_options(max_amount: float) -> list[dict]:
    """Returns 100%, 50%, 25% options with absolute amounts."""
    options = []
    for pct, label in [(1.0, "Total"), (0.5, "50%"), (0.25, "25%")]:
        amt = round(max_amount * pct, 2)
        options.append({"pct": pct, "label": label, "amount": amt})
    return options


# ============================================================
# Tasa escalonada por día efectivo de pago
# Política de Crédito Circa (vigente desde 28-abr-2026)
# ============================================================
#
# Tramos:
#   Día 1-7   → 3%
#   Día 8-15  → 5%
#   Día 16-30 → 7%
#   Día 31+   → 7% + mora 0.03% diaria sobre adeudado
#
# Mora se calcula sobre (amount + fee del 7%), no sobre el principal.

MORA_RATE_DIARIA = 0.0003  # 0.03% diario


def calcular_fee_por_dia_pago(amount: float, dias_desde_compra: int) -> dict:
    """
    Calcula fee según el día efectivo de pago (NO el plazo elegido).
    
    Returns:
        {
            "amount": principal financiado,
            "rate": tasa decimal del tramo,
            "rate_pct": tasa formateada (ej. "5.0%"),
            "fee": cargo del tramo (mín. S/3),
            "tramo": "1-7" | "8-15" | "16-30" | "31+",
            "dias_desde_compra": días pasados,
            "mora_dias": días en mora (0 si no aplica),
            "mora_monto": monto de mora (0 si no aplica),
            "total": amount + fee + mora_monto
        }
    """
    if dias_desde_compra <= 7:
        rate, tramo = 0.03, "1-7"
    elif dias_desde_compra <= 15:
        rate, tramo = 0.05, "8-15"
    elif dias_desde_compra <= 30:
        rate, tramo = 0.07, "16-30"
    else:
        rate, tramo = 0.07, "31+"
    
    fee = max(round(amount * rate, 2), MIN_FEE)
    adeudado = amount + fee
    
    if dias_desde_compra > 30:
        mora_dias = dias_desde_compra - 30
        mora_monto = round(adeudado * MORA_RATE_DIARIA * mora_dias, 2)
    else:
        mora_dias = 0
        mora_monto = 0.0
    
    total = round(adeudado + mora_monto, 2)
    
    return {
        "amount": amount,
        "rate": rate,
        "rate_pct": f"{rate * 100:.1f}%",
        "fee": fee,
        "tramo": tramo,
        "dias_desde_compra": dias_desde_compra,
        "mora_dias": mora_dias,
        "mora_monto": mora_monto,
        "total": total,
    }

