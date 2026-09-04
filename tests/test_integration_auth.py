"""Tests auth dual token + issue_access_token."""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

os.environ.setdefault("SUPABASE_URL", "http://localhost")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "test-key")
os.environ.setdefault("SUPABASE_KEY", "test-key")

from app.integration.auth import issue_access_token, path_data_mode, resolve_distribuidor_by_bearer


def test_path_data_mode():
    assert path_data_mode("/bodegas") == "prod"
    assert path_data_mode("/health") == "prod"
    assert path_data_mode("/test/bodegas") == "test"
    assert path_data_mode("/test") == "test"
    assert path_data_mode("/test/health") == "test"


@patch("app.integration.auth.db")
def test_resolve_bearer_prod(mock_db):
    chain = MagicMock()
    chain.select.return_value = chain
    chain.eq.return_value = chain
    chain.limit.return_value = chain
    chain.execute.return_value = MagicMock(
        data=[{"id": "d1", "api_token": "tok-prod", "api_token_test": "tok-test", "estado": "activo"}]
    )
    mock_db.sb.table.return_value = chain
    dist, mode = resolve_distribuidor_by_bearer("tok-prod")
    assert mode == "prod"
    assert dist["id"] == "d1"


@patch("app.integration.auth.db")
def test_resolve_bearer_test(mock_db):
    chain = MagicMock()
    chain.select.return_value = chain
    chain.eq.return_value = chain
    chain.limit.return_value = chain

    def _execute():
        # primera búsqueda (prod) vacía; segunda (test) hit — se simula con side_effect en eq
        return MagicMock(data=[])

    # Simplificar: devolver vacío en prod y hit en test según args de eq
    calls = {"n": 0}

    def execute():
        calls["n"] += 1
        if calls["n"] == 1:
            return MagicMock(data=[])
        return MagicMock(
            data=[{"id": "d1", "api_token": "tok-prod", "api_token_test": "tok-test", "estado": "activo"}]
        )

    chain.execute.side_effect = execute
    mock_db.sb.table.return_value = chain
    dist, mode = resolve_distribuidor_by_bearer("tok-test")
    assert mode == "test"


@patch("app.integration.auth.db")
def test_issue_access_token_prod(mock_db):
    chain = MagicMock()
    chain.select.return_value = chain
    chain.eq.return_value = chain
    chain.limit.return_value = chain
    chain.execute.return_value = MagicMock(
        data=[{
            "id": "d1",
            "nombre_comercial": "ZOOM",
            "estado": "activo",
            "api_client_id": "zoom-client",
            "api_client_secret": "secret-zoom",
            "api_token": "tok-prod",
            "api_token_test": "tok-test",
        }]
    )
    mock_db.sb.table.return_value = chain
    out = issue_access_token(
        client_id="zoom-client",
        client_secret="secret-zoom",
        data_mode="prod",
    )
    assert out["access_token"] == "tok-prod"
    assert out["data_mode"] == "prod"
    assert out["token_type"] == "Bearer"


@patch("app.integration.auth.db")
def test_issue_access_token_test(mock_db):
    chain = MagicMock()
    chain.select.return_value = chain
    chain.eq.return_value = chain
    chain.limit.return_value = chain
    chain.execute.return_value = MagicMock(
        data=[{
            "id": "d1",
            "nombre_comercial": "ZOOM",
            "estado": "activo",
            "api_client_id": "zoom-client",
            "api_client_secret": "secret-zoom",
            "api_token": "tok-prod",
            "api_token_test": "tok-test",
        }]
    )
    mock_db.sb.table.return_value = chain
    out = issue_access_token(
        client_id="zoom-client",
        client_secret="secret-zoom",
        data_mode="test",
    )
    assert out["access_token"] == "tok-test"
    assert out["data_mode"] == "test"


@patch("app.integration.auth.db")
def test_issue_access_token_bad_secret(mock_db):
    chain = MagicMock()
    chain.select.return_value = chain
    chain.eq.return_value = chain
    chain.limit.return_value = chain
    chain.execute.return_value = MagicMock(
        data=[{
            "id": "d1",
            "estado": "activo",
            "api_client_id": "zoom-client",
            "api_client_secret": "secret-zoom",
            "api_token": "tok-prod",
            "api_token_test": "tok-test",
        }]
    )
    mock_db.sb.table.return_value = chain
    with pytest.raises(HTTPException) as ei:
        issue_access_token(
            client_id="zoom-client",
            client_secret="wrong",
            data_mode="prod",
        )
    assert ei.value.status_code == 401
