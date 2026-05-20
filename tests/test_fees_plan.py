"""Tests — comisión por plan y mora (Circa fees)."""
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
    r = fees.calcular_total_a_pagar(100, 1.4, date(2026, 6, 1), hoy=date(2026, 5, 30))
    assert r["mora_monto"] == 0
    assert r["total_pagar"] == 101.4


def test_total_a_pagar_con_mora():
    r = fees.calcular_total_a_pagar(100, 1.4, date(2026, 5, 1), hoy=date(2026, 5, 11))
    assert r["mora_dias"] == 10
    assert r["mora_monto"] == 0.30
    assert r["total_pagar"] == 101.70


def test_calculate_fee_compat():
    r = fees.calculate_fee(200, 15)
    assert r["fee"] == 6.00
