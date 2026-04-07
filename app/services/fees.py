"""
Circa fee calculation — flat rates by term, minimum S/5.00.

Rates (per contract Contrato_Circa_vsrev.docx):
  7 días  → 3%
  15 días → 5%
  30 días → 7%

Minimum fee: S/5.00
"""

FEE_TABLE = {
    7:  0.03,   # 3%
    15: 0.05,   # 5%
    30: 0.07,   # 7%
}

MIN_FEE = 5.00


def get_fee_rate(amount: float, days: int) -> float:
    """Return flat rate for the given term. Defaults to 7% if unknown term."""
    return FEE_TABLE.get(days, 0.07)


def calculate_fee(amount: float, days: int) -> dict:
    """Calculate fee for a given amount and term, enforcing minimum S/5."""
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
