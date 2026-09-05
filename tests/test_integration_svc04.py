"""SVC-04 — preventa con monto_a_financiar y plazo_dias."""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

os.environ.setdefault("SUPABASE_URL", "http://localhost")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "test-key")
os.environ.setdefault("SUPABASE_KEY", "test-key")

import pytest
from fastapi import HTTPException

from app.integration.service import create_preventa

DIST = {"id": "dist-zoom"}
BODEGA = {
    "id": "b-1",
    "estado": "activo",
    "linea_disponible": 500,
    "es_test": False,
}


def _body(**extra):
    base = {
        "bodega_id": "b-1",
        "monto_a_financiar": 31.0,
        "plazo_dias": 7,
        "items": [
            {"sku": "P1", "nombre": "Prod", "cantidad": 2, "precio_unitario": 15.5},
        ],
    }
    base.update(extra)
    return base


@patch("app.integration.service.find_bodega", return_value=BODEGA)
@patch("app.integration.service.db")
def test_create_preventa_guarda_monto_y_plazo(mock_db, _find):
    inserted = {
        "id": "p-1",
        "external_id": None,
        "numero": "PV-1",
        "bodega_id": "b-1",
        "estado": "preventa_confirmada",
        "tipo_operacion": "preventa",
        "total_pedido": 31.0,
        "monto_financiado": 31.0,
        "plazo_dias": 7,
        "created_at": "2026-09-05T12:00:00Z",
        "items_json": [],
    }
    mock_db.sb.table.return_value.insert.return_value.execute.return_value = MagicMock(
        data=[inserted]
    )

    out = create_preventa(DIST, _body())
    assert out["monto_financiado"] == 31.0
    assert out["plazo_dias"] == 7
    payload = mock_db.sb.table.return_value.insert.call_args.args[0]
    assert payload["monto_financiado"] == 31.0
    assert payload["plazo_dias"] == 7
    assert payload["monto_contado"] == 0.0


@patch("app.integration.service.find_bodega", return_value=BODEGA)
def test_create_preventa_plazo_invalido(_find):
    with pytest.raises(HTTPException) as ei:
        create_preventa(DIST, _body(plazo_dias=10))
    assert ei.value.status_code == 400


@patch(
    "app.integration.service.find_bodega",
    return_value={**BODEGA, "linea_disponible": 10},
)
def test_create_preventa_supera_linea(_find):
    with pytest.raises(HTTPException) as ei:
        create_preventa(DIST, _body(monto_a_financiar=31.0))
    assert ei.value.status_code == 409


@patch(
    "app.integration.service.find_bodega",
    return_value={**BODEGA, "estado": "inactivo", "linea_disponible": 0},
)
def test_create_preventa_sin_linea(_find):
    with pytest.raises(HTTPException) as ei:
        create_preventa(DIST, _body())
    assert ei.value.status_code == 409
