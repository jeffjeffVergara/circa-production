"""Tests resumen WhatsApp preventa vendedor."""
import os

os.environ["SUPABASE_URL"] = "http://localhost"
os.environ["SUPABASE_SERVICE_KEY"] = "test-key"

from app.services.preventa_propuesta import (
    build_preventa_propuesta_mensaje,
    calc_financiable_efectivo,
    resumen_items_text,
)


def test_resumen_items():
    text = resumen_items_text([
        {"cantidad": 2, "nombre": "Producto A", "subtotal": 10.5},
    ])
    assert "2x Producto A" in text
    assert "S/10.50" in text


def test_calc_financiable_sin_linea():
    fin, eff = calc_financiable_efectivo(97.40, 0)
    assert fin == 0
    assert eff == 97.40


def test_mensaje_incluye_aprobar():
    msg = build_preventa_propuesta_mensaje(
        bodega={"nombre_comercial": "Bodega Test", "linea_disponible": 0},
        items=[{"cantidad": 1, "nombre": "Item", "subtotal": 50}],
        total=50,
        linea_disponible=0,
        vendedor_nombre="Pao",
    )
    assert "tu preventa está lista" in msg
    assert "APROBAR" in msg
    assert "RECHAZAR" in msg
    assert "Pagas en efectivo al vendedor" in msg
