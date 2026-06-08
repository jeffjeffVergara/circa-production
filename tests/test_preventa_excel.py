"""Tests parser Excel preventa DIMAX."""
import io
import os

os.environ.setdefault("SUPABASE_URL", "http://localhost")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "test-key")

from openpyxl import Workbook

from app.services.preventa_excel import parse_filename, parse_preventa_excel


def _preventa_xlsx_bytes():
    headers = ["Codigo", "Descripcion", "Cantidad", "Unidad", "P. Unitario", "SubTotal", "Total"]
    rows = [
        ["00033", "NESTLE Crema de Leche", 1, "UND x 1", 8.81, 8.81, 8.81],
        ["00463", "BONIFICACION MAGGI", 2, "UND x 1", 0.65, 1.30, 0],
    ]
    wb = Workbook()
    ws = wb.active
    ws.append(headers)
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_parse_filename_strips_preventa_suffix():
    nombre, fecha = parse_filename("SANCHEZ MAGIN SANDRA LUCERO_preventa.xlsx")
    assert nombre == "SANCHEZ MAGIN SANDRA LUCERO"
    assert fecha is None


def test_parse_preventa_excel_basic():
    parsed = parse_preventa_excel(
        _preventa_xlsx_bytes(),
        filename="SANCHEZ MAGIN SANDRA LUCERO_preventa.xlsx",
    )
    assert parsed["bodega_nombre"] == "SANCHEZ MAGIN SANDRA LUCERO"
    assert parsed["n_items"] == 1
    assert parsed["n_regalos"] == 1
    assert parsed["total_pedido"] == 8.81
