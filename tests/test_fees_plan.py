"""Tests — comisión por plan, mora híbrida y true-up 15/30 desde entrega."""
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services import fees


def test_plan_7_commission_100():
    r = fees.calcular_comision_por_plan(100, 7)
    assert r["fee"] == 1.40
    assert r["total"] == 101.40
    assert r["rate"] == 0.014


def test_plan_7_minimum_on_small_amount():
    r = fees.calcular_comision_por_plan(50, 7)
    assert r["fee"] == 1.00


def test_plan_15_and_30():
    assert fees.calcular_comision_por_plan(100, 15)["fee"] == 3.00
    assert fees.calcular_comision_por_plan(100, 30)["fee"] == 6.00


def test_mora_zero_on_time():
    assert fees.calcular_mora(100, 0) == 0.0


def test_mora_after_vencimiento():
    # 100 saldo, 10 días → 100 * 0.0003 * 10 = 0.30
    assert fees.calcular_mora(100, 10) == 0.30


def test_total_a_pagar_sin_mora():
    r = fees.calcular_total_a_pagar(
        100, 1.4, date(2026, 6, 1),
        hoy=date(2026, 5, 30),
        fecha_entregado=date(2026, 5, 25),
        plazo_dias=7,
    )
    assert r["mora_monto"] == 0
    assert r["total_pagar"] == 101.4
    assert r["escalonado"] is False


def test_total_a_pagar_con_mora_hibrida_pre_escalon():
    """Día 11 desde entrega, ya venció plan 7d → mora, sin true-up aún."""
    # entrega 1/5, vencimiento 8/5, hoy 12/5 → 11 días desde entrega, 4 atraso
    r = fees.calcular_total_a_pagar(
        100, 1.4, date(2026, 5, 8),
        hoy=date(2026, 5, 12),
        fecha_entregado=date(2026, 5, 1),
        plazo_dias=7,
    )
    assert r["dias_desde_entrega"] == 11
    assert r["escalonado"] is False
    assert r["fee_vigente"] == 1.4
    assert r["mora_dias"] == 4
    assert r["mora_monto"] == 0.12  # 101.4 * 0.0003 * 4
    assert r["total_pagar"] == 101.52


def test_trueup_dia_15_limpia_mora():
    """Día 15 desde entrega → fee 3%, mora = 0 (opción A)."""
    r = fees.calcular_total_a_pagar(
        100, 1.4, date(2026, 5, 8),
        hoy=date(2026, 5, 16),  # 15 días desde 1/5
        fecha_entregado=date(2026, 5, 1),
        plazo_dias=7,
    )
    assert r["dias_desde_entrega"] == 15
    assert r["escalonado"] is True
    assert r["plazo_vigente"] == 15
    assert r["fee_vigente"] == 3.0
    assert r["fee_delta"] == 1.6
    assert r["mora_monto"] == 0.0
    assert r["mora_dias"] == 0
    assert r["total_pagar"] == 103.0


def test_trueup_dia_30_a_6():
    r = fees.calcular_total_a_pagar(
        100, 1.4, date(2026, 5, 8),
        hoy=date(2026, 5, 31),  # 30 días desde 1/5
        fecha_entregado=date(2026, 5, 1),
        plazo_dias=7,
    )
    assert r["dias_desde_entrega"] == 30
    assert r["plazo_vigente"] == 30
    assert r["fee_vigente"] == 6.0
    assert r["mora_monto"] == 0.0
    assert r["total_pagar"] == 106.0


def test_plan_15_no_baja_en_dia_15():
    """Pedido originado a 15d: el día 15 no baja; solo mora tras vencimiento hasta día 30."""
    r = fees.calcular_total_a_pagar(
        100, 3.0, date(2026, 5, 16),
        hoy=date(2026, 5, 20),  # 19 días desde entrega, vencido, < 30
        fecha_entregado=date(2026, 5, 1),
        plazo_dias=15,
    )
    assert r["escalonado"] is False
    assert r["fee_vigente"] == 3.0
    assert r["mora_dias"] == 4
    assert r["mora_monto"] == 0.12  # 103 * 0.0003 * 4


def test_plan_15_salta_a_6_en_dia_30():
    r = fees.calcular_total_a_pagar(
        100, 3.0, date(2026, 5, 16),
        hoy=date(2026, 5, 31),
        fecha_entregado=date(2026, 5, 1),
        plazo_dias=15,
    )
    assert r["escalonado"] is True
    assert r["fee_vigente"] == 6.0
    assert r["mora_monto"] == 0.0
    assert r["total_pagar"] == 106.0


def test_garcia_poma_crc048_dia_11():
    """Sanity: CRC-048 el 14/07 (11d desde entrega 03/07) → mora, sin escalón."""
    r = fees.calcular_total_a_pagar(
        230.70, 3.23, date(2026, 7, 10),
        hoy=date(2026, 7, 14),
        fecha_entregado=date(2026, 7, 3),
        plazo_dias=7,
    )
    assert r["dias_desde_entrega"] == 11
    assert r["escalonado"] is False
    assert r["fee_vigente"] == 3.23
    assert r["mora_dias"] == 4
    assert r["mora_monto"] == 0.28
    assert r["total_pagar"] == 234.21


def test_garcia_poma_crc048_dia_15():
    r = fees.calcular_total_a_pagar(
        230.70, 3.23, date(2026, 7, 10),
        hoy=date(2026, 7, 18),
        fecha_entregado=date(2026, 7, 3),
        plazo_dias=7,
    )
    assert r["dias_desde_entrega"] == 15
    assert r["escalonado"] is True
    assert r["fee_vigente"] == 6.92  # 230.70 * 3%
    assert r["mora_monto"] == 0.0
    assert r["total_pagar"] == 237.62


def test_total_pagar_desde_pedido_usa_entrega():
    pedido = {
        "monto_financiado": 100,
        "fee_monto": 1.4,
        "plazo_dias": 7,
        "fecha_vencimiento": "2026-05-08",
        "fecha_entregado": "2026-05-01T12:00:00+00:00",
    }
    r = fees.total_pagar_desde_pedido(pedido, hoy=date(2026, 5, 16))
    assert r["fee_vigente"] == 3.0
    assert r["mora_monto"] == 0.0


def test_calculate_fee_compat():
    r = fees.calculate_fee(200, 15)
    assert r["fee"] == 6.00
