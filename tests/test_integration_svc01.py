"""Casos de prueba SVC-01 — consultar afiliación y línea (§6.4).

Cubre interpretación de franja UI + listado mockeado.
Ejecutar: python3 -m pytest tests/test_integration_svc01.py -q
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

os.environ.setdefault("SUPABASE_URL", "http://localhost")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "test-key")
os.environ.setdefault("SUPABASE_KEY", "test-key")

import pytest

from app.integration.franja import describir_franja, interpretar_franja_svc01
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


# ── Matriz §6.4 — interpretación de franja ─────────────────────────────────

@pytest.mark.parametrize(
    "kwargs,esperado,accion_substr",
    [
        # TP-01: no encuentra bodega (lista vacía)
        (
            {"http_status": 200, "total": 0, "items": []},
            "sin_linea",
            "Precargar",
        ),
        # TP-02: existe pero inactiva (precarga / sin activar)
        (
            {
                "http_status": 200,
                "items": [_bodega_out(_bodega(estado="inactivo", linea_disponible=0, linea_aprobada=200))],
            },
            "sin_linea",
            "Precargar",
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
            "sin_linea",
            "Precargar",
        ),
        # TP-09: inactiva con linea_aprobada > 0 (aún Caso A)
        (
            {
                "bodega": _bodega_out(
                    _bodega(estado="inactivo", linea_aprobada=800, linea_disponible=0, onboarding_fase="precargada")
                ),
            },
            "sin_linea",
            "Precargar",
        ),
        # TP-10: activa con linea_disponible None → no disponible
        (
            {
                "bodega": {
                    **_bodega_out(_bodega(estado="activo")),
                    "linea_disponible": None,
                },
            },
            "no_disponible",
            "No disponible",
        ),
    ],
    ids=[
        "TP-01_no_encuentra",
        "TP-02_inactiva",
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
    """Si hay varias coincidencias, la franja se evalúa sobre el item elegido (aquí el primero)."""
    items = [
        _bodega_out(_bodega(id="b1", estado="activo", linea_disponible=100, dni="11111111")),
        _bodega_out(_bodega(id="b2", estado="inactivo", linea_disponible=0, dni="22222222")),
    ]
    assert interpretar_franja_svc01(http_status=200, total=2, items=items) == "con_linea"
    # Si BsSoft elige la inactiva a mano:
    assert interpretar_franja_svc01(bodega=items[1]) == "sin_linea"


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
    assert interpretar_franja_svc01(http_status=200, **out) == "sin_linea"


@patch("app.integration.service.db")
def test_tp02_list_bodegas_inactiva(mock_db):
    rows = [_bodega(estado="inactivo", linea_disponible=0, linea_aprobada=200, dni="07631909")]
    mock_db.sb.table.return_value = _mock_table(rows)

    out = list_bodegas(DIST, q="07631909", limit=20)
    assert out["total"] == 1
    item = out["items"][0]
    assert item["estado"] == "inactivo"
    assert item["created"] is False
    assert interpretar_franja_svc01(http_status=200, **out) == "sin_linea"


@patch("app.integration.service.db")
def test_tp03_list_bodegas_activa_sin_cupo(mock_db):
    rows = [_bodega(estado="activo", linea_disponible=0, linea_aprobada=500, dni="07631909")]
    mock_db.sb.table.return_value = _mock_table(rows)

    out = list_bodegas(DIST, q="07631909")
    assert out["items"][0]["linea_aprobada"] == 500.0
    assert out["items"][0]["linea_disponible"] == 0.0
    assert interpretar_franja_svc01(http_status=200, **out) == "no_disponible"


@patch("app.integration.service.db")
def test_tp04_list_bodegas_activa_con_linea(mock_db):
    rows = [_bodega(estado="activo", linea_disponible=350, linea_aprobada=500, dni="07631909")]
    mock_db.sb.table.return_value = _mock_table(rows)

    out = list_bodegas(DIST, q="07631909")
    item = out["items"][0]
    assert item["id"]
    assert item["linea_disponible"] == 350.0
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
def test_list_bodegas_pasa_filtro_es_test(mock_db):
    mock_db.sb.table.return_value = _mock_table([])
    list_bodegas(DIST, es_test=True)
    eq_calls = mock_db.sb.table.return_value.eq.call_args_list
    assert any(c.args[:2] == ("es_test", True) for c in eq_calls)
    list_bodegas(DIST, es_test=False)
    eq_calls = mock_db.sb.table.return_value.eq.call_args_list
    assert any(c.args[:2] == ("es_test", False) for c in eq_calls)


def test_bodega_out_incluye_es_test():
    row = _bodega()
    row["es_test"] = True
    out = _bodega_out(row)
    assert out["es_test"] is True
    assert out["created"] is False
