"""Tests for pedido flow progress (backoffice BPMN)."""
import os

os.environ.setdefault("SUPABASE_URL", "http://localhost")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "test-key")

from app.services.pedido_flow import build_pedido_flow_progress, flujo_resumen


def test_venta_en_preparacion_mid_flow():
    p = {
        "id": "p1",
        "numero": "CRC-00001-001",
        "tipo_operacion": "venta",
        "estado": "en_preparacion",
        "monto_financiado": 100,
    }
    flow = build_pedido_flow_progress(p)
    assert flow["step_index"] == 2
    assert flow["total_steps"] == 8  # 6 logística + 2 cobranza
    assert flow["remaining_steps"] == 5
    assert flow["current_step"]["id"] == "en_preparacion"
    assert flow["next_step"]["id"] == "despachado"


def test_venta_entregado_sin_financiamiento():
    p = {
        "tipo_operacion": "venta",
        "estado": "entregado",
        "monto_financiado": 0,
    }
    flow = build_pedido_flow_progress(p)
    assert flow["total_steps"] == 6
    assert flow["is_success"] is True
    assert flow["percent"] == 100


def test_preventa_confirmada():
    p = {
        "tipo_operacion": "preventa",
        "estado": "preventa_confirmada",
        "monto_financiado": 0,
    }
    flow = build_pedido_flow_progress(p)
    assert flow["current_step"]["id"] == "preventa_confirmada"
    assert flow["next_step"]["id"] == "preventa_aceptada"


def test_flujo_resumen_lightweight():
    p = {"tipo_operacion": "venta", "estado": "recibido", "monto_financiado": 50}
    s = flujo_resumen(build_pedido_flow_progress(p))
    assert "percent" in s
    assert s["total_steps"] >= 6
    assert s["current_label"] == "Recibido"
