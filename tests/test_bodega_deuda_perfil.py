"""Tests desglose deuda en perfil de bodega."""
import os
from datetime import date
from unittest.mock import patch

os.environ.setdefault("SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "test-key")
os.environ.setdefault("SUPABASE_KEY", "test-key")

from app.routes.backoffice import _build_deuda_perfil


def test_build_deuda_perfil_suma_total():
    pedidos = [
        {
            "id": "p1",
            "numero": "CRC-064",
            "estado": "entregado",
            "monto_financiado": 100,
            "fee_monto": 1.4,
            "plazo_dias": 7,
            "fecha_vencimiento": "2026-07-21",
            "fecha_entregado": "2026-07-14T19:05:11+00:00",
        },
        {
            "id": "p2",
            "numero": "CRC-OLD",
            "estado": "pagado",
            "monto_financiado": 50,
            "fee_monto": 0.7,
            "plazo_dias": 7,
            "fecha_vencimiento": "2026-06-01",
            "fecha_entregado": "2026-05-20T00:00:00+00:00",
            "fecha_pagado": "2026-05-28T00:00:00+00:00",
        },
    ]
    with patch("app.routes.backoffice.total_pagar_desde_pedido") as mock_tp:
        mock_tp.return_value = {
            "fee_congelado": 1.4,
            "fee_vigente": 1.4,
            "fee_delta": 0.0,
            "fee_tasa_vigente": 0.014,
            "plazo_origen": 7,
            "plazo_vigente": 7,
            "dias_desde_entrega": 1,
            "escalonado": False,
            "mora_dias": 0,
            "mora_monto": 0.0,
            "saldo_adeudado": 101.4,
            "total_pagar": 101.4,
        }
        out = _build_deuda_perfil(pedidos)
    assert out["resumen"]["n_abiertos"] == 1
    assert out["resumen"]["total_pagar"] == 101.4
    assert out["items"][0]["numero"] == "CRC-064"
    assert out["items"][0]["status"] == "al_dia"
    mock_tp.assert_called_once()
