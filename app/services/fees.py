"""
Circa — comisión por plan + mora híbrida con escalón por antigüedad desde entrega.

Al confirmar:
  Plan 7 días  → 1.4%
  Plan 15 días → 3%
  Plan 30 días → 6%
  Comisión mínima: S/1.00 por operación

Post-entrega (reloj = fecha_entregado), si no pagan:
  Días 1–7 (o hasta vencimiento del plan): fee congelado, sin mora
  Tras vencimiento y antes del siguiente escalón: mora 0.03% diaria sobre saldo
  Día 15+ desde entrega: true-up a fee 3% (si el plan origen era menor); mora se limpia
  Día 30+ desde entrega: true-up a fee 6%; mora se limpia

El true-up solo sube (`max`); nunca baja un plan 15d/30d.
Pedidos legacy (fee_regimen != plan_fijo_v20260520): misma lógica de cobro vigente
usando fee_tasa/fee_monto persistidos como base.
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

# Escalones de true-up medidos en días calendario desde fecha_entregado
ESCALON_15_DIAS = 15
ESCALON_30_DIAS = 30


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


def _parse_date(value: date | str | None) -> Optional[date]:
    if not value:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).date()
    except (ValueError, TypeError):
        return None


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
    """Comisión según plan (origen o escalón de true-up)."""
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
    hoy = hoy or hoy_peru()
    fv = _parse_date(fecha_vencimiento)
    if not fv:
        return 0
    return max(0, (hoy - fv).days)


def dias_desde_entrega(
    fecha_entregado: date | str | None,
    hoy: date | None = None,
) -> int | None:
    """Días calendario desde la entrega (0 = día de entrega). None si no hay fecha."""
    hoy = hoy or hoy_peru()
    fe = _parse_date(fecha_entregado)
    if not fe:
        return None
    return max(0, (hoy - fe).days)


def escalon_plazo_por_antiguedad(dias_desde_entrega: int | None) -> int | None:
    """
    Escalón de true-up según antigüedad desde entrega.
    None = aún no aplica salto (se mantiene fee de origen + mora híbrida si vence).
    """
    if dias_desde_entrega is None:
        return None
    if dias_desde_entrega >= ESCALON_30_DIAS:
        return 30
    if dias_desde_entrega >= ESCALON_15_DIAS:
        return 15
    return None


def plazo_vigente_con_escalon(plazo_origen: int, dias_desde_entrega: int | None) -> int:
    """Plazo efectivo = max(origen, escalón). Solo sube."""
    origen = int(plazo_origen or 7)
    if origen not in PAYMENT_PLANS:
        origen = 7
    esc = escalon_plazo_por_antiguedad(dias_desde_entrega)
    if esc is None:
        return origen
    return max(origen, esc)


def fee_vigente_trueup(
    monto_financiado: float,
    fee_congelado: float,
    plazo_origen: int,
    dias_desde_entrega: int | None,
) -> dict:
    """
    Comisión vigente con true-up al escalón 15/30.
    Devuelve fee_vigente >= fee_congelado y si hubo salto.
    """
    congelado = _money(_d(fee_congelado))
    plazo_v = plazo_vigente_con_escalon(plazo_origen, dias_desde_entrega)
    quote = calcular_comision_por_plan(monto_financiado, plazo_v)
    vigente = max(congelado, quote["fee"])
    escalonado = vigente > congelado + 1e-9
    return {
        "fee_congelado": congelado,
        "fee_vigente": vigente,
        "fee_delta": _money(_d(vigente) - _d(congelado)),
        "fee_tasa_vigente": quote["rate"],
        "plazo_origen": int(plazo_origen or quote["days"]),
        "plazo_vigente": plazo_v,
        "escalonado": escalonado,
        "rate_pct": format_rate_pct(quote["rate"]),
    }


def calcular_mora(saldo_adeudado: float, dias_atraso: int) -> float:
    """Mora diaria 0.03% sobre saldo (solo ventana híbrida pre-escalón)."""
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
    *,
    fecha_entregado: date | str | None = None,
    plazo_dias: int | None = None,
) -> dict:
    """
    Total a pagar con fee true-up + mora híbrida (opción A).

    - Si hay salto de escalón (15/30 desde entrega): fee vigente sube; mora = 0.
    - Si aún no hay salto y ya venció: mora 0.03%/día sobre saldo con fee congelado.
    """
    hoy = hoy or hoy_peru()
    dias_ent = dias_desde_entrega(fecha_entregado, hoy)
    plazo_o = int(plazo_dias or 7)
    if plazo_o not in PAYMENT_PLANS:
        plazo_o = 7

    tu = fee_vigente_trueup(monto_financiado, fee_monto, plazo_o, dias_ent)
    fee_v = tu["fee_vigente"]
    credito_fijo = _money(_d(monto_financiado) + _d(tu["fee_congelado"]))
    saldo = calcular_saldo_adeudado(monto_financiado, fee_v, monto_pagado)
    dias_atraso = dias_atraso_desde_vencimiento(fecha_vencimiento, hoy)

    # Opción A: al escalar, se limpia la mora acumulada
    if tu["escalonado"]:
        mora = 0.0
        mora_dias = 0
    else:
        mora = calcular_mora(saldo, dias_atraso)
        mora_dias = dias_atraso

    return {
        "credito_fijo": credito_fijo,
        "fee_congelado": tu["fee_congelado"],
        "fee_vigente": fee_v,
        "fee_delta": tu["fee_delta"],
        "fee_tasa_vigente": tu["fee_tasa_vigente"],
        "plazo_origen": tu["plazo_origen"],
        "plazo_vigente": tu["plazo_vigente"],
        "escalonado": tu["escalonado"],
        "dias_desde_entrega": dias_ent,
        "saldo_adeudado": saldo,
        "mora_monto": mora,
        "mora_dias": mora_dias,
        "total_pagar": _money(_d(saldo) + _d(mora)),
    }


def resolver_fecha_entrega_pedido(pedido: dict) -> Optional[date]:
    """Base del reloj de escalón: entrega → confirmación → created_at."""
    for key in ("fecha_entregado", "confirmado_at", "created_at"):
        d = _parse_date(pedido.get(key))
        if d:
            return d
    return None


def resolver_fecha_vencimiento_pedido(pedido: dict, hoy: date | None = None) -> Optional[date]:
    """fecha_vencimiento en BD o entrega/confirmación + plazo_dias."""
    fv = _parse_date(pedido.get("fecha_vencimiento"))
    if fv:
        return fv
    plazo = int(pedido.get("plazo_dias") or 0)
    if plazo <= 0:
        return None
    base = resolver_fecha_entrega_pedido(pedido)
    if not base:
        return None
    return base + timedelta(days=plazo)


def total_pagar_desde_pedido(pedido: dict, monto_pagado: float = 0, hoy: date | None = None) -> dict:
    """Total vigente para cobranza (fee true-up + mora híbrida si aplica)."""
    mf = float(pedido.get("monto_financiado") or 0)
    fee = float(pedido.get("fee_monto") or 0)
    if mf <= 0 and fee <= 0:
        tc = float(pedido.get("monto_total_credito") or pedido.get("total") or 0)
        if tc > 0:
            return {
                "credito_fijo": tc,
                "fee_congelado": 0.0,
                "fee_vigente": 0.0,
                "fee_delta": 0.0,
                "fee_tasa_vigente": 0.0,
                "plazo_origen": int(pedido.get("plazo_dias") or 0),
                "plazo_vigente": int(pedido.get("plazo_dias") or 0),
                "escalonado": False,
                "dias_desde_entrega": None,
                "saldo_adeudado": max(0.0, tc - monto_pagado),
                "mora_monto": 0.0,
                "mora_dias": 0,
                "total_pagar": max(0.0, tc - monto_pagado),
            }
    fv = resolver_fecha_vencimiento_pedido(pedido, hoy)
    fe = resolver_fecha_entrega_pedido(pedido)
    plazo = int(pedido.get("plazo_dias") or 7)
    return calcular_total_a_pagar(
        mf,
        fee,
        fv,
        monto_pagado,
        hoy,
        fecha_entregado=fe,
        plazo_dias=plazo,
    )


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
