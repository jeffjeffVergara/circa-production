"""Tests parser Excel DIMAX bodega."""
import io
import os
from pathlib import Path

os.environ["SUPABASE_URL"] = "http://localhost"
os.environ["SUPABASE_SERVICE_KEY"] = "test-key"

import pytest
from fastapi import HTTPException
from openpyxl import Workbook

from app.services import dimax_bodega_excel as dimax

FIXTURE = Path("/Users/jefferson/Documents/Circa/formatos/SANCHEZ MAGIN SANDRA LUCERO_bodega.xlsx")


def _dimax_xlsx_bytes(**overrides):
    row = {
        "Codigo": "1040879",
        "DNI/RUC": "75808577",
        "RazonSocial": "SANCHEZ MAGIN SANDRA LUCERO",
        "Direccion": "Jr TACNA Nro. 921",
        "TELEFONO": "986557671",
        "Distrito": "MAGDALENA DEL MAR",
        "COD VENDEDOR 1": "VW172",
        "VENDEDOR 1": "ESTRADA TRAVEZAN CARLOS ALBERTO",
    }
    row.update(overrides)
    headers = list(row.keys())
    wb = Workbook()
    ws = wb.active
    ws.title = "clientes"
    ws.append(headers)
    ws.append([row[h] for h in headers])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_parse_dimax_bodega_synthetic():
    parsed = dimax.parse_dimax_bodega_excel(_dimax_xlsx_bytes())
    assert parsed["ruc"] == "75808577"
    assert parsed["solo_dni_sin_ruc"] is True
    assert parsed["telefono_whatsapp"] == "+51986557671"
    assert parsed["vendedor_codigo"] == "VW172"


@pytest.mark.skipif(not FIXTURE.is_file(), reason="fixture Excel no disponible en CI")
def test_parse_dimax_bodega_fixture():
    parsed = dimax.parse_dimax_bodega_excel(FIXTURE.read_bytes())
    assert parsed["formato"] == "dimax_clientes"
    assert parsed["ruc"] == "75808577"
    assert parsed["solo_dni_sin_ruc"] is True
    assert parsed["razon_social"] == "SANCHEZ MAGIN SANDRA LUCERO"
    assert parsed["telefono_whatsapp"] == "+51986557671"
    assert parsed["distrito"] == "MAGDALENA DEL MAR"
    assert parsed["codigo_dimax"] == "1040879"
    assert parsed["vendedor_codigo"] == "VW172"


def test_parse_documento_dni_y_ruc():
    dni, solo = dimax._parse_documento("75808577")
    assert dni == "75808577"
    assert solo is True
    ruc, solo2 = dimax._parse_documento("20123456789")
    assert ruc == "20123456789"
    assert solo2 is False


def test_parse_empty_raises():
    with pytest.raises(HTTPException) as exc:
        dimax.parse_dimax_bodega_excel(b"not-an-xlsx")
    assert exc.value.status_code == 400
