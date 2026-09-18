"""Casos de prueba SVC-01 — consultar afiliación y línea (§6.4).

Cubre interpretación de situacion/franja UI + listado mockeado.
Ejecutar: python3 -m pytest tests/test_integration_svc01.py -q
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

os.environ.setdefault("SUPABASE_URL", "http://localhost")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "test-key")
os.environ.setdefault("SUPABASE_KEY", "test-key")

import pytest

from app.integration.franja import calcular_situacion, describir_franja, interpretar_franja_svc01
from app.integration.service import _bodega_out, list_bodegas


# ── Fixtures de bodega ─────────────────────────────────────────────────────

def _bodega(
    *,
    estado: str = "activo",
    linea_aprobada: float = 500,
    linea_disponible: float = 350,
    dni: str = "07631909",
    **extra,
) -> dict:
    row = {
        "id": extra.get("id", "b-test-001"),
        "external_id": extra.get("external_id", "CLI-07631909"),
        "telefono_whatsapp": "+51987654321",
        "dni_representante": dni,
        "ruc": extra.get("ruc"),
        "razon_social": extra.get("razon_social", "BODEGA DEMO"),
        "nombre_comercial": "Bodega Demo",
        "estado": estado,
        "onboarding_fase": extra.get("onboarding_fase", "activo"),
        "kyc_nivel": extra.get("kyc_nivel", "dni"),
        "linea_aprobada": linea_aprobada,
        "linea_disponible": linea_disponible,
    }
    return row


# ── Matriz §6.4 — interpretación de situacion ──────────────────────────────

@pytest.mark.parametrize(
    "kwargs,esperado,accion_substr",
    [
        # TP-01: no encuentra bodega (lista vacía)
        (
            {"http_status": 200, "total": 0, "items": []},
            "no_registrada",
            "Precargar",
        ),
        # TP-02: existe pero inactiva (precarga / en evaluación)
        (
            {
                "http_status": 200,
                "items": [_bodega_out(_bodega(estado="inactivo", linea_disponible=0, linea_aprobada=200))],
            },
            "en_evaluacion",
            "reconsultar",
        ),
        # TP-03: activa sin cupo (linea_disponible = 0)
        (
            {
                "http_status": 200,
                "items": [_bodega_out(_bodega(estado="activo", linea_disponible=0, linea_aprobada=500))],
            },
            "no_disponible",
            "No disponible",
        ),
        # TP-04: activa con línea (happy path)
        (
            {
                "http_status": 200,
                "items": [_bodega_out(_bodega(estado="activo", linea_disponible=350, linea_aprobada=500))],
            },
            "con_linea",
            "SVC-04",
        ),
        # TP-05: timeout / sin conexión
        (
            {"timed_out": True},
            "sin_conexion",
            "contado",
        ),
        # TP-06: 5xx
        (
            {"http_status": 503},
            "sin_conexion",
            "contado",
        ),
        # TP-07: 401 token inválido → tratar como sin conexión en UI
        (
            {"http_status": 401},
            "sin_conexion",
            "contado",
        ),
        # TP-08: SVC-01b 404 (UUID inexistente)
        (
            {"http_status": 404},
            "no_registrada",
            "Precargar",
        ),
        # TP-09: inactiva con linea_aprobada > 0 → en evaluación
        (
            {
                "bodega": _bodega_out(
                    _bodega(estado="inactivo", linea_aprobada=800, linea_disponible=0, onboarding_fase="precargada")
                ),
            },
            "en_evaluacion",
            "reconsultar",
        ),
        # TP-10: activa con linea_disponible None → no disponible
        (
            {
                "bodega": {
                    **_bodega_out(_bodega(estado="activo")),
                    "linea_disponible": None,
                    "situacion": "no_disponible",
                },
            },
            "no_disponible",
            "No disponible",
        ),
    ],
    ids=[
        "TP-01_no_encuentra",
        "TP-02_inactiva_en_evaluacion",
        "TP-03_activa_sin_cupo",
        "TP-04_activa_con_linea",
        "TP-05_timeout",
        "TP-06_5xx",
        "TP-07_401",
        "TP-08_404_svc01b",
        "TP-09_inactiva_con_tope",
        "TP-10_disponible_null",
    ],
)
def test_interpretar_franja_matriz(kwargs, esperado, accion_substr):
    franja = interpretar_franja_svc01(**kwargs)
    assert franja == esperado
    assert accion_substr.lower() in describir_franja(franja).lower()


def test_tp04_elige_primer_item_del_listado():
    """Si hay varias coincidencias, la situacion se evalúa sobre el item elegido (aquí el primero)."""
    items = [
        _bodega_out(_bodega(id="b1", estado="activo", linea_disponible=100, dni="11111111")),
        _bodega_out(_bodega(id="b2", estado="inactivo", linea_disponible=0, dni="22222222")),
    ]
    assert interpretar_franja_svc01(http_status=200, total=2, items=items) == "con_linea"
    assert interpretar_franja_svc01(bodega=items[1]) == "en_evaluacion"


def test_calcular_situacion_matriz():
    assert calcular_situacion(_bodega(estado="inactivo", linea_disponible=0)) == "en_evaluacion"
    assert calcular_situacion(_bodega(estado="activo", linea_disponible=0)) == "no_disponible"
    assert calcular_situacion(_bodega(estado="activo", linea_disponible=10)) == "con_linea"


# ── list_bodegas (SVC-01) con DB mock ──────────────────────────────────────

DIST = {"id": "dist-zoom", "nombre_comercial": "ZOOM"}


def _mock_table(rows: list[dict]):
    chain = MagicMock()
    chain.select.return_value = chain
    chain.eq.return_value = chain
    chain.order.return_value = chain
    chain.range.return_value = chain
    chain.execute.return_value = MagicMock(data=rows)
    return chain


@patch("app.integration.service.db")
def test_tp01_list_bodegas_q_sin_match(mock_db):
    rows = [_bodega(dni="07631909", razon_social="OTRA BODEGA")]
    mock_db.sb.table.return_value = _mock_table(rows)

    out = list_bodegas(DIST, q="99999999", limit=20)
    assert out["total"] == 0
    assert out["items"] == []
    assert out["situacion"] == "no_registrada"
    assert interpretar_franja_svc01(http_status=200, **out) == "no_registrada"


@patch("app.integration.service.db")
def test_tp02_list_bodegas_inactiva(mock_db):
    rows = [_bodega(estado="inactivo", linea_disponible=0, linea_aprobada=200, dni="07631909")]
    mock_db.sb.table.return_value = _mock_table(rows)

    out = list_bodegas(DIST, q="07631909", limit=20)
    assert out["total"] == 1
    item = out["items"][0]
    assert item["estado"] == "inactivo"
    assert item["situacion"] == "en_evaluacion"
    assert out["situacion"] == "en_evaluacion"
    assert item["created"] is False
    assert interpretar_franja_svc01(http_status=200, **out) == "en_evaluacion"


@patch("app.integration.service.db")
def test_tp03_list_bodegas_activa_sin_cupo(mock_db):
    rows = [_bodega(estado="activo", linea_disponible=0, linea_aprobada=500, dni="07631909")]
    mock_db.sb.table.return_value = _mock_table(rows)

    out = list_bodegas(DIST, q="07631909")
    assert out["items"][0]["linea_aprobada"] == 500.0
    assert out["items"][0]["linea_disponible"] == 0.0
    assert out["items"][0]["situacion"] == "no_disponible"
    assert out["situacion"] == "no_disponible"
    assert interpretar_franja_svc01(http_status=200, **out) == "no_disponible"


@patch("app.integration.service.db")
def test_tp04_list_bodegas_activa_con_linea(mock_db):
    rows = [_bodega(estado="activo", linea_disponible=350, linea_aprobada=500, dni="07631909")]
    mock_db.sb.table.return_value = _mock_table(rows)

    out = list_bodegas(DIST, q="07631909")
    item = out["items"][0]
    assert item["id"]
    assert item["linea_disponible"] == 350.0
    assert item["situacion"] == "con_linea"
    assert out["situacion"] == "con_linea"
    assert interpretar_franja_svc01(http_status=200, **out) == "con_linea"


@patch("app.integration.service.db")
def test_list_bodegas_busca_por_external_id_y_telefono(mock_db):
    row = _bodega(dni="11111111")
    row["external_id"] = "CLI-AAA"
    row["telefono_whatsapp"] = "+51911111111"
    mock_db.sb.table.return_value = _mock_table([row])

    by_ext = list_bodegas(DIST, q="CLI-AAA")
    assert by_ext["total"] == 1

    by_tel = list_bodegas(DIST, q="51911111111")
    assert by_tel["total"] == 1


@patch("app.integration.service.db")
def test_tp11_list_bodegas_match_por_razon_social_o_nombre(mock_db):
    """TP-11: q parcial case-insensitive sobre razon_social / nombre_comercial."""
    rows = [
        _bodega(
            id="b-jon",
            dni="46843088",
            razon_social="JONATHAN TEST SAC",
            estado="activo",
            linea_disponible=500,
        ),
        _bodega(
            id="b-otra",
            dni="99999999",
            razon_social="OTRA BODEGA",
            estado="activo",
            linea_disponible=100,
        ),
    ]
    rows[0]["nombre_comercial"] = "Jonathan Test"
    rows[1]["nombre_comercial"] = "Otra"
    mock_db.sb.table.return_value = _mock_table(rows)

    by_full = list_bodegas(DIST, q="JONATHAN TEST")
    assert by_full["total"] == 1
    assert by_full["items"][0]["id"] == "b-jon"
    assert by_full["situacion"] == "con_linea"

    by_partial = list_bodegas(DIST, q="jonathan")
    assert by_partial["total"] == 1
    assert by_partial["items"][0]["razon_social"] == "JONATHAN TEST SAC"

    by_nombre = list_bodegas(DIST, q="Jonathan Test")
    assert by_nombre["total"] == 1
    assert by_nombre["items"][0]["nombre_comercial"] == "Jonathan Test"


@patch("app.integration.service.db")
def test_list_bodegas_pasa_filtro_es_test(mock_db):
    mock_db.sb.table.return_value = _mock_table([])
    list_bodegas(DIST, es_test=True)
    eq_calls = mock_db.sb.table.return_value.eq.call_args_list
    assert any(c.args[:2] == ("es_test", True) for c in eq_calls)
    list_bodegas(DIST, es_test=False)
    eq_calls = mock_db.sb.table.return_value.eq.call_args_list
    assert any(c.args[:2] == ("es_test", False) for c in eq_calls)


def test_bodega_out_incluye_es_test_y_situacion():
    row = _bodega()
    row["es_test"] = True
    out = _bodega_out(row)
    assert out["es_test"] is True
    assert out["created"] is False
    assert out["situacion"] == "con_linea"
    assert out["tiene_foto_dueno"] is False
    assert out["tiene_foto_bodega"] is False


def test_bodega_out_flags_fotos():
    row = _bodega(estado="inactivo", linea_disponible=0)
    row["foto_dueno_url"] = "prospecto/+51987654321/dueno_x.jpg"
    row["foto_bodega_url"] = "prospecto/+51987654321/local_x.jpg"
    out = _bodega_out(row)
    assert out["tiene_foto_dueno"] is True
    assert out["tiene_foto_bodega"] is True
    assert out["situacion"] == "en_evaluacion"


@patch("app.integration.service.db")
def test_upsert_guarda_paths_fotos(mock_db):
    from app.integration.service import upsert_bodega

    chain = _mock_table([])
    # find returns empty; insert returns row
    inserted = _bodega(estado="inactivo", linea_disponible=0, linea_aprobada=200)
    inserted["foto_dueno_url"] = "prospecto/+51987654321/dueno.jpg"
    inserted["foto_bodega_url"] = "prospecto/+51987654321/local.jpg"
    inserted["es_test"] = False

    def _table(_name):
        t = MagicMock()
        t.select.return_value = t
        t.eq.return_value = t
        t.limit.return_value = t
        t.execute.return_value = MagicMock(data=[])
        t.insert.return_value = MagicMock(execute=MagicMock(return_value=MagicMock(data=[inserted])))
        return t

    mock_db.sb.table.side_effect = _table

    out = upsert_bodega(
        DIST,
        {
            "telefono_whatsapp": "987654321",
            "dni_representante": "07631909",
            "razon_social": "BODEGA DEMO",
            "foto_dueno_url": inserted["foto_dueno_url"],
            "foto_bodega_url": inserted["foto_bodega_url"],
        },
        es_test=False,
    )
    assert out["created"] is True
    assert out["tiene_foto_dueno"] is True
    assert out["tiene_foto_bodega"] is True
    assert out["situacion"] == "en_evaluacion"
