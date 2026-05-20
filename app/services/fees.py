"""
Circa — comisión por plan (congelada al confirmar) + mora post-vencimiento.

Contrato vigente (nuevas operaciones desde 20/05/2026):
  Plan 7 días  → 1.4%
  Plan 15 días → 3%
  Plan 30 días → 6%
  Comisión mínima: S/1.00 por operación
  Mora: 0.03% diaria sobre saldo adeudado después del vencimiento del plan

Pedidos legacy (fee_regimen != plan_fijo_v20260520): usar fee_tasa/fee_monto persistidos.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional
from zoneinfo import ZoneInfo

TZ_PERU = ZoneInfo("America/Lima")

FEE_REGIME_LEGACY = "legacy_v20260428"
FEE_REGIME_CURRENT = "plan_fijo_v20260520"

# Legacy (solo pedidos originados antes del corte; no usar en nuevos pedidos)
LEGACY_FEE_TABLE = {7: Decimal("0.03"), 15: Decimal("0.05"), 30: Decimal("0.07")}
LEGACY_MIN_FEE = Decimal("3.00")

MORA_DAILY_RATE = Decimal("0.0003")
MIN_COMMISSION = Decimal("1.00")
VALID_PLAZOS = (7, 15, 30)


@dataclass(frozen=True)
class PaymentPlan:
    days: int
    fee_percentage: Decimal
    label: str


PAYMENT_PLANS: dict[int, PaymentPlan] = {
    7: PaymentPlan(7, Decimal("0.014"), "Plan 7 días"),
    15: PaymentPlan(15, Decimal("0.03"), "Plan 15 días"),
    30: PaymentPlan(30, Decimal("0.06"), "Plan 30 días"),
}

# Compat aliases (evitar hardcodes en imports viejos)
FEE_TABLE = {d: float(p.fee_percentage) for d, p in PAYMENT_PLANS.items()}
MIN_FEE = float(MIN_COMMISSION)
MORA_RATE_DIARIA = float(MORA_DAILY_RATE)


def _d(value) -> Decimal:
    return Decimal(str(value))


def _money(value: Decimal) -> float:
    return float(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def hoy_peru() -> date:
    return datetime.now(TZ_PERU).date()


def format_rate_pct(rate: float | Decimal) -> str:
    pct = float(rate) * 100
    rounded = round(pct, 2)
    if abs(rounded - round(rounded)) < 0.05:
        return f"{int(round(rounded))}%"
    return f"{rounded:.1f}%"


def obtener_plan(plazo_dias: int) -> PaymentPlan:
    plan = PAYMENT_PLANS.get(int(plazo_dias))
    if not plan:
        raise ValueError(f"Plazo inválido: {plazo_dias}. Use 7, 15 o 30.")
    return plan


def calcular_comision_por_plan(monto_financiado: float, plazo_dias: int) -> dict:
    """Comisión fija según plan elegido al originar (no depende del día de pago)."""
    plan = obtener_plan(plazo_dias)
    monto = _d(monto_financiado)
    fee = (monto * plan.fee_percentage).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    fee = max(fee, MIN_COMMISSION)
    total = (monto + fee).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    rate = plan.fee_percentage
    return {
        "rate": float(rate),
        "rate_pct": format_rate_pct(rate),
        "fee": _money(fee),
        "total": _money(total),
        "amount": _money(monto),
        "days": plan.days,
        "plan_label": plan.label,
        "fee_regimen": FEE_REGIME_CURRENT,
    }


def calcular_total_financiado(monto_financiado: float, plazo_dias: int) -> float:
    return calcular_comision_por_plan(monto_financiado, plazo_dias)["total"]


def dias_atraso_desde_vencimiento(
    fecha_vencimiento: date | str | None,
    hoy: date | None = None,
) -> int:
    """Días calendario después del vencimiento (0 si aún no vence)."""
    if not fecha_vencimiento:
        return 0
    hoy = hoy or hoy_peru()
    if isinstance(fecha_vencimiento, str):
        fv = datetime.fromisoformat(fecha_vencimiento.replace("Z", "+00:00")).date()
    else:
        fv = fecha_vencimiento
    delta = (hoy - fv).days
    return max(0, delta)


def calcular_mora(saldo_adeudado: float, dias_atraso: int) -> float:
    """Mora diaria 0.03% sobre saldo; no altera comisión original."""
    if dias_atraso <= 0 or saldo_adeudado <= 0:
        return 0.0
    saldo = _d(saldo_adeudado)
    mora = saldo * MORA_DAILY_RATE * _d(dias_atraso)
    return _money(mora)


def calcular_saldo_adeudado(
    monto_financiado: float,
    fee_monto: float,
    monto_pagado: float = 0,
) -> float:
    credito = _d(monto_financiado) + _d(fee_monto)
    pagado = _d(monto_pagado)
    saldo = max(Decimal("0"), credito - pagado)
    return _money(saldo)


def calcular_total_a_pagar(
    monto_financiado: float,
    fee_monto: float,
    fecha_vencimiento: date | str | None,
    monto_pagado: float = 0,
    hoy: date | None = None,
) -> dict:
    credito_fijo = _money(_d(monto_financiado) + _d(fee_monto))
    saldo = calcular_saldo_adeudado(monto_financiado, fee_monto, monto_pagado)
    dias_atraso = dias_atraso_desde_vencimiento(fecha_vencimiento, hoy)
    mora = calcular_mora(saldo, dias_atraso)
    return {
        "credito_fijo": credito_fijo,
        "saldo_adeudado": saldo,
        "mora_monto": mora,
        "mora_dias": dias_atraso,
        "total_pagar": _money(_d(saldo) + _d(mora)),
    }


def resolver_fecha_vencimiento_pedido(pedido: dict, hoy: date | None = None) -> Optional[date]:
    """fecha_vencimiento en BD o entrega/confirmación + plazo_dias."""
    fv = pedido.get("fecha_vencimiento")
    if fv:
        try:
            return datetime.fromisoformat(str(fv).replace("Z", "+00:00")).date()
        except (ValueError, TypeError):
            pass
    plazo = int(pedido.get("plazo_dias") or 0)
    if plazo <= 0:
        return None
    base = pedido.get("fecha_entregado") or pedido.get("confirmado_at") or pedido.get("created_at")
    if not base:
        return None
    try:
        bd = datetime.fromisoformat(str(base).replace("Z", "+00:00")).date()
        return bd + timedelta(days=plazo)
    except (ValueError, TypeError):
        return None


def total_pagar_desde_pedido(pedido: dict, monto_pagado: float = 0, hoy: date | None = None) -> dict:
    """Total vigente para cobranza (crédito congelado + mora si aplica)."""
    mf = float(pedido.get("monto_financiado") or 0)
    fee = float(pedido.get("fee_monto") or 0)
    if mf <= 0 and fee <= 0:
        tc = float(pedido.get("monto_total_credito") or pedido.get("total") or 0)
        if tc > 0:
            return {
                "credito_fijo": tc,
                "saldo_adeudado": max(0.0, tc - monto_pagado),
                "mora_monto": 0.0,
                "mora_dias": 0,
                "total_pagar": max(0.0, tc - monto_pagado),
            }
    fv = resolver_fecha_vencimiento_pedido(pedido, hoy)
    return calcular_total_a_pagar(mf, fee, fv, monto_pagado, hoy)


# ── API compatible (delega al motor por plan) ─────────────────

def get_fee_rate(amount: float, days: int) -> float:
    return calcular_comision_por_plan(amount, days)["rate"]


def calculate_fee(amount: float, days: int) -> dict:
    return calcular_comision_por_plan(amount, days)


def get_all_term_options(amount: float) -> list[dict]:
    return [calcular_comision_por_plan(amount, d) for d in VALID_PLAZOS]


def get_finance_options(max_amount: float) -> list[dict]:
    options = []
    for pct, label in [(1.0, "Total"), (0.5, "50%"), (0.25, "25%")]:
        amt = round(max_amount * pct, 2)
        options.append({"pct": pct, "label": label, "amount": amt})
    return options


def fee_regimen_para_pedido_nuevo() -> str:
    return FEE_REGIME_CURRENT
