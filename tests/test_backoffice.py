"""Tests backoffice auth y rutas básicas."""
import asyncio
import os

import pytest
from fastapi import HTTPException

os.environ["BACKOFFICE_EMAIL"] = "soporte@test.pe"
os.environ["BACKOFFICE_PASSWORD"] = "test-pass-123"
os.environ["BACKOFFICE_JWT_SECRET"] = "test-jwt-secret"
os.environ["CIRCA_ADMIN_TOKEN"] = "test-admin-token"

from app.services import backoffice_auth as auth
from app.routes import backoffice as bo


def test_create_and_decode_token():
    tok = auth.create_token("u1", "soporte@test.pe")
    payload = auth.decode_token(tok)
    assert payload["email"] == "soporte@test.pe"
    assert payload["sub"] == "u1"


def test_verify_password_env():
    assert auth.verify_password("test-pass-123")
    assert not auth.verify_password("wrong")


def test_login_ok():
    result = asyncio.run(bo.login(bo.LoginRequest(email="soporte@test.pe", password="test-pass-123")))
    assert result["ok"] is True
    assert result["token"]


def test_login_bad_password():
    with pytest.raises(HTTPException) as exc:
        asyncio.run(bo.login(bo.LoginRequest(email="soporte@test.pe", password="bad")))
    assert exc.value.status_code == 401


def test_verify_reauth_password():
    auth.verify_reauth_password("test-pass-123")
    with pytest.raises(HTTPException):
        auth.verify_reauth_password("nope")
