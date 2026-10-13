"""Estado y totales de un entrante, sin tocar la base."""
import os

os.environ.setdefault("SUPABASE_URL", "http://localhost")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "test-key")
os.environ.setdefault("SUPABASE_KEY", "test-key")

import pytest
from fastapi import HTTPException

from app.integration.entrantes import _fecha_lima, _parse_fecha, estado_entrante, totales_items


def test_sin_bodega_queda_sin_match():
    assert estado_entrante(bodega_id=None, monto_credito=40, pago_confirmado=True) == "sin_match"


def test_con_bodega_sin_monto_queda_pendiente():
    assert estado_entrante(bodega_id="b1", monto_credito=None, pago_confirmado=False) == "pendiente_monto"
    assert estado_entrante(bodega_id="b1", monto_credito=0, pago_confirmado=True) == "pendiente_monto"


def test_con_monto_sin_pago():
    assert estado_entrante(bodega_id="b1", monto_credito=30, pago_confirmado=False) == "pendiente_pago"


def test_lista_cuando_hay_match_monto_y_pago():
    assert estado_entrante(bodega_id="b1", monto_credito=30, pago_confirmado=True) == "lista"


def test_descartada_pisa_los_checks():
    assert estado_entrante(
        bodega_id="b1", monto_credito=30, pago_confirmado=True, descartada=True,
    ) == "descartada"


def test_total_sale_de_los_items_si_no_viene():
    total, desc, productos = totales_items(
        [{"cantidad": 2, "precio_unitario": 10.5, "subtotal": None}],
        None,
        1,
    )
    assert total == 21.0
    assert desc == 1
    assert productos == 22.0


def test_solo_dia_queda_a_medianoche_gmt5():
    assert _fecha_lima(_parse_fecha("2026-10-12")) == "2026-10-12T00:00:00-05:00"


def test_hora_sin_zona_se_toma_en_gmt5():
    assert _fecha_lima(_parse_fecha("2026-10-12T22:52:00")) == "2026-10-12T22:52:00-05:00"


def test_utc_se_muestra_en_gmt5():
    assert _fecha_lima("2026-10-13T03:52:36.900215+00:00") == "2026-10-12T22:52:36-05:00"


def test_fecha_invalida():
    with pytest.raises(HTTPException):
        _parse_fecha("12/10/2026")
