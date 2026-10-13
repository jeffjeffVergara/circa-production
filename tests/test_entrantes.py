"""Estado y totales de un entrante, sin tocar la base."""
import os

os.environ.setdefault("SUPABASE_URL", "http://localhost")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "test-key")
os.environ.setdefault("SUPABASE_KEY", "test-key")

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.integration.entrantes import _fecha_lima, _norm_items, _parse_fecha, estado_entrante, totales_items
from app.integration.schemas import EntranteCreateRequest


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


def test_total_cobra_el_total_y_el_descuento_sale_del_subtotal():
    items = _norm_items([
        {
            "codigo": "004521",
            "descripcion": "CAFETAL SELECTO 24x200g",
            "cantidad": 3,
            "unidad": "UND x 24",
            "precio_unitario": 10.30,
            "subtotal": 32.10,
            "total": 30.90,
        },
        {
            "codigo": "001102",
            "descripcion": "BONIFICACION GALLETA SODA",
            "cantidad": 1,
            "unidad": "UND",
            "precio_unitario": 0,
            "subtotal": 2.50,
            "total": 0,
        },
    ])
    assert items[0]["sku"] == "4521"
    assert items[0]["es_regalo"] is False
    assert items[1]["es_regalo"] is True
    total, desc, productos = totales_items(items)
    assert total == 30.90
    assert desc == 1.20
    assert productos == 32.10


def test_subtotal_menor_que_total_se_rechaza():
    with pytest.raises(HTTPException):
        _norm_items([{
            "codigo": "1",
            "descripcion": "CAFETAL",
            "cantidad": 1,
            "precio_unitario": 10,
            "subtotal": 8,
            "total": 10,
        }])


def test_el_pedido_exige_las_columnas_del_excel():
    body = EntranteCreateRequest.model_validate({
        "external_id": "PV-2026-000451",
        "bodega_nombre": "URBANO CHIHUANTITO DAVID GENARO",
        "fecha": "2026-10-12T09:40:00",
        "items": [{
            "codigo": "004521",
            "descripcion": "CAFETAL SELECTO 24x200g",
            "cantidad": 3,
            "unidad": "UND x 24",
            "precio_unitario": 10.30,
            "subtotal": 32.10,
            "total": 30.90,
        }],
    })
    assert body.fecha == "2026-10-12T09:40:00"
    assert body.pago_confirmado is False
    assert body.monto_credito is None


def test_sin_total_de_linea_no_entra():
    with pytest.raises(ValidationError):
        EntranteCreateRequest.model_validate({
            "external_id": "PV-1",
            "bodega_nombre": "BODEGA",
            "fecha": "2026-10-12T09:40:00",
            "items": [{
                "codigo": "004521",
                "descripcion": "CAFETAL",
                "cantidad": 1,
                "precio_unitario": 10,
                "subtotal": 10,
            }],
        })


def test_solo_dia_queda_a_medianoche_gmt5():
    assert _fecha_lima(_parse_fecha("2026-10-12")) == "2026-10-12T00:00:00-05:00"


def test_hora_sin_zona_se_toma_en_gmt5():
    assert _fecha_lima(_parse_fecha("2026-10-12T22:52:00")) == "2026-10-12T22:52:00-05:00"


def test_utc_se_muestra_en_gmt5():
    assert _fecha_lima("2026-10-13T03:52:36.900215+00:00") == "2026-10-12T22:52:36-05:00"


def test_fecha_invalida():
    with pytest.raises(HTTPException):
        _parse_fecha("12/10/2026")
