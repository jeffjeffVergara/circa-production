"""
Tests — contrato v4.0: comisión por tramo de pago (1-7 → 1.4%, 8-14 → 3%, 15-30 → 6%)
y mora 0.03% diaria desde el día 31. Reloj = fecha_entregado.

El corte es por fecha de evaluación (FECHA_VIGENCIA_TRAMOS = 2026-08-28):
antes se evalúa con los escalones 15/30 del contrato v3.0.
"""
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services import fees

ENTREGA = date(2026, 9, 1)          # posterior al corte
VENC = ENTREGA + timedelta(days=7)  # vencimiento del plan 7d


def _tp(dias_desde_entrega: int, mf=100, fee=1.4, plazo=7):
    return fees.calcular_total_a_pagar(
        mf, fee, VENC,
        hoy=ENTREGA + timedelta(days=dias_desde_entrega),
        fecha_entregado=ENTREGA,
        plazo_dias=plazo,
    )


# ── Tramo 1: días 1-7 → 1.4% ──────────────────────────────────

def test_tramo_bajo_dia_4():
    r = _tp(4)
    assert r["escalonado"] is False
    assert r["fee_vigente"] == 1.40
    assert r["mora_monto"] == 0.0
    assert r["total_pagar"] == 101.40


def test_tramo_bajo_dia_7_es_el_ultimo():
    r = _tp(7)
    assert r["fee_vigente"] == 1.40
    assert r["total_pagar"] == 101.40


# ── Tramo 2: días 8-14 → 3% (el que no existía en v3.0) ───────

def test_tramo_medio_arranca_dia_8():
    r = _tp(8)
    assert r["escalonado"] is True
    assert r["plazo_vigente"] == 15
    assert r["fee_vigente"] == 3.00
    assert r["fee_delta"] == 1.60
    assert r["mora_monto"] == 0.0
    assert r["total_pagar"] == 103.00


def test_tramo_medio_dia_10():
    assert _tp(10)["total_pagar"] == 103.00


def test_tramo_medio_dia_14_es_el_ultimo():
    r = _tp(14)
    assert r["fee_vigente"] == 3.00
    assert r["total_pagar"] == 103.00


# ── Tramo 3: días 15-30 → 6% ──────────────────────────────────

def test_tramo_alto_arranca_dia_15():
    r = _tp(15)
    assert r["plazo_vigente"] == 30
    assert r["fee_vigente"] == 6.00
    assert r["mora_monto"] == 0.0
    assert r["total_pagar"] == 106.00


def test_tramo_alto_dia_22_ejemplo_del_contrato():
    """Ejemplo literal de la Cláusula 4: S/100 pagado el día 22 → S/106.00."""
    assert _tp(22)["total_pagar"] == 106.00


def test_tramo_alto_dia_30_sin_mora_todavia():
    r = _tp(30)
    assert r["fee_vigente"] == 6.00
    assert r["mora_monto"] == 0.0
    assert r["mora_dias"] == 0
    assert r["total_pagar"] == 106.00


# ── Día 31+: mora 0.03% diaria sobre el saldo ─────────────────

def test_mora_arranca_dia_31():
    r = _tp(31)
    assert r["fee_vigente"] == 6.00
    assert r["mora_dias"] == 1
    assert r["mora_monto"] == 0.03   # 106.00 * 0.0003 * 1
    assert r["total_pagar"] == 106.03


def test_mora_acumula_dia_40():
    r = _tp(40)
    assert r["mora_dias"] == 10
    assert r["mora_monto"] == 0.32   # 106.00 * 0.0003 * 10
    assert r["total_pagar"] == 106.32


# ── Ejemplos del contrato con otros montos ────────────────────

def test_ejemplo_200_soles():
    assert _tp(6, mf=200, fee=2.80)["total_pagar"] == 202.80
    assert _tp(12, mf=200, fee=2.80)["total_pagar"] == 206.00
    assert _tp(25, mf=200, fee=2.80)["total_pagar"] == 212.00


def test_comision_minima_se_respeta():
    """S/50 al día 3: 1.4% = S/0.70 → cobra el mínimo de S/1.00."""
    assert fees.calcular_comision_por_plan(50, 7)["fee"] == 1.00


# ── El true-up nunca baja un plan mayor ───────────────────────

def test_plan_30_no_baja_en_tramo_bajo():
    r = _tp(3, fee=6.0, plazo=30)
    assert r["fee_vigente"] == 6.00
    assert r["escalonado"] is False


# ── Corte de vigencia ─────────────────────────────────────────

def test_antes_del_corte_usa_escalones_v3():
    """Mismo día 10 desde entrega, evaluado antes del corte: sigue en 1.4% + mora."""
    entrega = date(2026, 8, 1)
    r = fees.calcular_total_a_pagar(
        100, 1.4, entrega + timedelta(days=7),
        hoy=date(2026, 8, 11),           # anterior a 2026-08-28
        fecha_entregado=entrega,
        plazo_dias=7,
    )
    assert r["escalonado"] is False
    assert r["fee_vigente"] == 1.40
    assert r["mora_dias"] == 3


def test_dia_del_corte_ya_aplica_tramos():
    """Un pedido entregado el 18/08 el día 28/08 está en día 10 → 3%."""
    entrega = date(2026, 8, 18)
    r = fees.calcular_total_a_pagar(
        100, 1.4, entrega + timedelta(days=7),
        hoy=fees.FECHA_VIGENCIA_TRAMOS,
        fecha_entregado=entrega,
        plazo_dias=7,
    )
    assert r["dias_desde_entrega"] == 10
    assert r["escalonado"] is True
    assert r["fee_vigente"] == 3.00


def test_vispera_del_corte_no_aplica_tramos():
    entrega = date(2026, 8, 18)
    r = fees.calcular_total_a_pagar(
        100, 1.4, entrega + timedelta(days=7),
        hoy=fees.FECHA_VIGENCIA_TRAMOS - timedelta(days=1),
        fecha_entregado=entrega,
        plazo_dias=7,
    )
    assert r["escalonado"] is False
    assert r["fee_vigente"] == 1.40


def test_regimen_persistido_en_pedido_nuevo():
    assert fees.fee_regimen_para_pedido_nuevo(date(2026, 8, 27)) == fees.FEE_REGIME_PLAN_FIJO
    assert fees.fee_regimen_para_pedido_nuevo(date(2026, 8, 28)) == fees.FEE_REGIME_TRAMOS
