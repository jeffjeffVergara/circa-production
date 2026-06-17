"""Auth unificada: JWT backoffice válido en API de soporte."""
import os

os.environ["SUPABASE_URL"] = "http://localhost"
os.environ["SUPABASE_KEY"] = "test-key"
os.environ["BACKOFFICE_JWT_SECRET"] = "test-jwt-secret-unified"
os.environ["SUPPORT_CONSOLE_AGENT_ID"] = "a0000000-0000-4000-8000-000000000001"

import pytest
from fastapi import HTTPException

from app.services.backoffice_auth import create_token
from app.support import security

_CONSOLE_AGENT = {
    "id": "a0000000-0000-4000-8000-000000000001",
    "display_name": "Consola",
    "role": "agent",
    "status": "online",
}


@pytest.fixture(autouse=True)
def _fake_db(monkeypatch):
    monkeypatch.setattr(security, "_load_console_agent", lambda: _CONSOLE_AGENT.copy())


def test_backoffice_jwt_resolves_console_agent():
    tok = create_token("bootstrap-support", "soporte@test.pe", "admin")
    agent = security.resolve_support_agent_from_token(tok)
    assert agent["id"] == _CONSOLE_AGENT["id"]


def test_viewer_backoffice_jwt_rejected_by_support():
    tok = create_token("bootstrap-viewer", "lectura@test.pe", "viewer")
    with pytest.raises(HTTPException) as exc:
        security.resolve_support_agent_from_token(tok)
    assert exc.value.status_code == 403


def test_bootstrap_secret_still_works(monkeypatch):
    monkeypatch.setenv("SUPPORT_BOOTSTRAP_SECRET", "legacy-secret-phrase")
    agent = security.resolve_support_agent_from_token("legacy-secret-phrase")
    assert agent["id"] == _CONSOLE_AGENT["id"]
