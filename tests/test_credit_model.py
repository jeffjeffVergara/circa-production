"""Tests del modelo de líneas de crédito (regresión vs cargar_bodega)."""

from __future__ import annotations

import io
from datetime import date, timedelta

import openpyxl

from app.services.credit_model.helpers import tier_para
from app.services.credit_model.risk_analyzer import analizar, clasificar_avisos
from app.services.credit_model.credit_model_service import process_bytes
from app.services.credit_model.sql_generator import generar_sql, sql_para_archivo


def _build_dimax_xlsx(
    *,
    codigo: str = "B001",
    razon: str = "Bodega De La Prueba SAC",
    telefono: str = "942616682",
    doc: str = "12345678",
    pedidos: int = 8,
    monto_por_pedido: float = 80.0,
    dias_entre: int = 5,
) -> bytes:
    wb = openpyxl.Workbook()
    ws_cli = wb.active
    ws_cli.title = "Cliente"
    headers = [
        "Codigo", "RazonSocial", "DNI/RUC", "TELEFONO", "Direccion", "Distrito",
        "Clasificacion", "COD VENDEDOR 1", "VENDEDOR 1", "GRUPO 1",
        "SUPERVISOR 1", "DIA VISITA 1", "DIA ENTREGA 1",
    ]
    ws_cli.append(headers)
    ws_cli.append([
        codigo, razon, doc, telefono, "jr lima 123", "miraflores", "A",
        "V01", "Juan Perez", "ABN", "Sup A", "lunes", "martes",
    ])
    ws_hist = wb.create_sheet("Historial")
    ws_hist.append(["a", "b", "fecha", "d", "sellout"])
    base = date.today()
    for i in range(pedidos):
        f = base - timedelta(days=(pedidos - i) * dias_entre)
        ws_hist.append(["", "", f, "", monto_por_pedido])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_tier_para_conservador():
    assert tier_para(50) == 100
    assert tier_para(100) == 100
    assert tier_para(101) == 200
    assert tier_para(500) == 500
    assert tier_para(999) == 500


def test_analizar_y_avisos_historial_corto():
    hist = []
    base = date.today()
    for i in range(3):
        hist.append(("", "", base - timedelta(days=i * 7), "", 100.0))
    a = analizar(hist)
    assert a is not None
    avisos = clasificar_avisos(a)
    assert any("Historial corto" in x for x in avisos["revisar"])


def test_process_bytes_genera_sql_y_mensaje():
    content = _build_dimax_xlsx()
    b, err = process_bytes(content, "test.xlsx")
    assert err is None
    assert b is not None
    assert b["analisis"]["tier"] in (100, 200, 300, 400, 500)
    assert "INSERT INTO bodegas" in b["sql"]["inserts"]
    assert "Buenas Don" in b["mensaje"]
    block = sql_para_archivo(b)
    assert "BEGIN;" in block and "COMMIT;" in block


def test_process_files_api_shape():
    content = _build_dimax_xlsx()
    from app.services.credit_model.credit_model_service import process_files

    out = process_files([(content, "a.xlsx")])
    assert out["total"] == 1
    row = out["bodegas"][0]
    assert row["telefono"].startswith("+51")
    assert row["sql_inserts"]
    assert row["necesita_revision"] is False or isinstance(row["necesita_revision"], bool)


def test_patch_sql_linea_cambia_linea_aprobada():
    content = _build_dimax_xlsx()
    raw = process_bytes(content, "t.xlsx")[0]
    sql = generar_sql(raw)
    original = sql["inserts"]
    tier_orig = raw["analisis"]["tier"]
    nueva_linea = tier_orig + 100 if tier_orig < 400 else 200
    from app.services.credit_model.sql_generator import patch_sql_linea

    patched = patch_sql_linea(original, nueva_linea)
    assert patched != original
    assert f"false, true, 'inactivo', {nueva_linea}, 0," in patched


def test_apply_linea_to_load_item():
    content = _build_dimax_xlsx()
    from app.services.credit_model.credit_model_service import apply_linea_to_load_item, process_files

    out = process_files([(content, "a.xlsx")])
    row = out["bodegas"][0]
    patched = apply_linea_to_load_item({**row, "linea_aprobada": 350})
    assert patched["tier"] == 350
    assert "false, true, 'inactivo', 350, 0," in patched["sql_inserts"]
    assert "Linea aprobada: S/350" in patched["sql_block"]


def test_load_bodegas_records_via_supabase_when_no_db_url(monkeypatch):
    monkeypatch.delenv("CIRCA_DB_URL", raising=False)
    import app.services.credit_model.db_loader as loader

    record = {
        "cliente": {"RazonSocial": "Bodega Test SAC", "DNI/RUC": "12345678"},
        "razon_social": "Bodega Test SAC",
        "telefono": "+51999988877",
        "linea_aprobada": 200,
        "vendedores": [],
        "avisos": {"revisar": [], "notas": []},
        "_confirmar_revision": False,
        "sql": {"inserts": "--", "verificacion": "--", "telefono": "+51999988877"},
    }
    monkeypatch.setattr(
        loader,
        "ejecutar_bodega_supabase",
        lambda _r: (True, [("bodega", "Bodega Test SAC", "200", "0", "inactivo")]),
    )
    out = loader.load_bodegas_records([record])
    assert out["ok"] == 1
    assert out["via"] == "supabase"


def test_generar_sql_telefono_e164():
    content = _build_dimax_xlsx(telefono="51942616682")
    raw = process_bytes(content, "t.xlsx")[0]
    sql = generar_sql(raw)
    assert sql["telefono"] == "+51942616682"
