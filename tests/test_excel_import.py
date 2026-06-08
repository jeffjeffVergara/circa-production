"""Tests importación Excel backoffice."""
import io
import os

os.environ.setdefault("SUPABASE_URL", "http://localhost")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "test-key")

import pytest
from openpyxl import Workbook

from app.services import excel_import as xls


def _xlsx_bytes(headers, rows):
    wb = Workbook()
    ws = wb.active
    ws.append(headers)
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_parse_xlsx_bodegas():
    data = _xlsx_bytes(
        ["ruc", "razon_social", "telefono_whatsapp"],
        [["20123456789", "Test SAC", "999888777"]],
    )
    rows = xls.parse_xlsx(data)
    assert len(rows) == 1
    assert rows[0]["ruc"] == "20123456789"
    assert rows[0]["_fila"] == 2


def test_group_pedido_rows():
    rows = [
        {"ref_pedido": "P1", "ruc_bodega": "20111111111", "_fila": 2},
        {"ref_pedido": "P1", "ruc_bodega": "20111111111", "_fila": 3},
        {"ref_pedido": "P2", "ruc_bodega": "20222222222", "_fila": 4},
    ]
    g = xls._group_pedido_rows(rows)
    assert len(g) == 2
    assert len(g["P1"]) == 2


def test_cell_bool():
    assert xls._cell_bool("si") is True
    assert xls._cell_bool("0") is False
    assert xls._cell_bool(None, default=True) is True


def test_preview_bodegas_rows_ok(monkeypatch):
    monkeypatch.setattr(xls.db, "get_bodega_by_ruc", lambda _r: None)
    monkeypatch.setattr(xls.db, "get_bodega_by_phone", lambda _t: None)
    rows = [
        {
            "_fila": 2,
            "ruc": "20123456789",
            "razon_social": "Test SAC",
            "telefono_whatsapp": "999888777",
            "nombre_comercial": "Minimarket",
        }
    ]
    preview = xls.preview_bodegas_rows(rows)
    assert preview["summary"]["listas"] == 1
    assert preview["rows"][0]["status"] == "ok"
    assert preview["rows"][0]["telefono_whatsapp"] == "+51999888777"


def test_preview_bodegas_rows_duplicate_ruc(monkeypatch):
    monkeypatch.setattr(xls.db, "get_bodega_by_ruc", lambda _r: {"id": "x"})
    monkeypatch.setattr(xls.db, "get_bodega_by_phone", lambda _t: None)
    rows = [{"_fila": 2, "ruc": "20123456789", "razon_social": "Test SAC", "telefono_whatsapp": "999888777"}]
    preview = xls.preview_bodegas_rows(rows)
    assert preview["summary"]["omitidas"] == 1
    assert preview["rows"][0]["status"] == "omitir"
