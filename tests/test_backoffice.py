"""Tests backoffice auth y rutas básicas."""
import asyncio
import os

import pytest
from fastapi import HTTPException

os.environ["BACKOFFICE_EMAIL"] = "soporte@test.pe"
os.environ["BACKOFFICE_PASSWORD"] = "test-pass-123"
os.environ["BACKOFFICE_VIEWER_EMAIL"] = "lectura@test.pe"
os.environ["BACKOFFICE_VIEWER_PASSWORD"] = "viewer-pass-456"
os.environ["BACKOFFICE_JWT_SECRET"] = "test-jwt-secret"
os.environ["CIRCA_ADMIN_TOKEN"] = "test-admin-token"
os.environ["SUPABASE_URL"] = "http://localhost"
os.environ["SUPABASE_SERVICE_KEY"] = "test-key"

from app.services import backoffice_auth as auth
from app.routes import backoffice as bo


def test_create_and_decode_token():
    tok = auth.create_token("u1", "soporte@test.pe", auth.ROLE_ADMIN)
    payload = auth.decode_token(tok)
    assert payload["email"] == "soporte@test.pe"
    assert payload["sub"] == "u1"
    assert payload["role"] == auth.ROLE_ADMIN


def test_verify_password_env():
    assert auth.verify_password("test-pass-123")
    assert not auth.verify_password("wrong")


def test_authenticate_admin_and_viewer():
    admin = auth.authenticate("soporte@test.pe", "test-pass-123")
    assert admin and admin["role"] == auth.ROLE_ADMIN
    viewer = auth.authenticate("lectura@test.pe", "viewer-pass-456")
    assert viewer and viewer["role"] == auth.ROLE_VIEWER
    assert auth.authenticate("lectura@test.pe", "wrong") is None


def test_authenticate_viewer_from_credentials_env(monkeypatch):
    monkeypatch.delenv("BACKOFFICE_VIEWER_EMAIL", raising=False)
    monkeypatch.delenv("BACKOFFICE_VIEWER_PASSWORD", raising=False)
    monkeypatch.setenv("BACKOFFICE_VIEWER_CREDENTIALS", "otro@test.pe:clave-otra")
    from importlib import reload
    from app import config
    from app.services import backoffice_auth as ba

    reload(config)
    reload(ba)
    user = ba.authenticate("otro@test.pe", "clave-otra")
    assert user and user["role"] == ba.ROLE_VIEWER


def test_login_ok():
    result = asyncio.run(bo.login(bo.LoginRequest(email="soporte@test.pe", password="test-pass-123")))
    assert result["ok"] is True
    assert result["token"]
    assert result["user"]["role"] == auth.ROLE_ADMIN


def test_login_viewer_ok():
    result = asyncio.run(bo.login(bo.LoginRequest(email="lectura@test.pe", password="viewer-pass-456")))
    assert result["ok"] is True
    assert result["user"]["role"] == auth.ROLE_VIEWER


def test_login_bad_password():
    with pytest.raises(HTTPException) as exc:
        asyncio.run(bo.login(bo.LoginRequest(email="soporte@test.pe", password="bad")))
    assert exc.value.status_code == 401


def test_verify_reauth_password():
    auth.verify_reauth_password("test-pass-123")
    with pytest.raises(HTTPException):
        auth.verify_reauth_password("nope")


def test_viewer_blocked_from_writer_dependency():
    tok = auth.create_token("bootstrap-viewer", "lectura@test.pe", auth.ROLE_VIEWER)

    async def _check():
        from fastapi.security import HTTPAuthorizationCredentials

        creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=tok)
        user = await auth.get_backoffice_user(creds)
        assert user["role"] == auth.ROLE_VIEWER
        with pytest.raises(HTTPException) as exc:
            await auth.get_backoffice_writer(user)
        assert exc.value.status_code == 403

    asyncio.run(_check())
