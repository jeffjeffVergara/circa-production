"""Tests for internal admin auth."""
import asyncio

import pytest
from fastapi import HTTPException

from app.services import internal_auth


def test_verify_admin_token_rejects_invalid(monkeypatch):
    monkeypatch.setenv("CIRCA_ADMIN_TOKEN", "good-token")
    monkeypatch.setenv("CIRCA_ENV", "development")
    with pytest.raises(HTTPException) as exc:
        asyncio.run(internal_auth.verify_admin_token(x_admin_token="bad-token"))
    assert exc.value.status_code == 401


def test_verify_admin_token_accepts_valid(monkeypatch):
    monkeypatch.setenv("CIRCA_ADMIN_TOKEN", "good-token")
    monkeypatch.setenv("CIRCA_ENV", "development")
    assert asyncio.run(internal_auth.verify_admin_token(x_admin_token="good-token")) is True
