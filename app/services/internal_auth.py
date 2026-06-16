"""Autenticación para endpoints internos/admin expuestos en main.py."""
from __future__ import annotations

import hmac
import os

from fastapi import Depends, Header, HTTPException

from app.config import admin_token_or_raise


async def verify_admin_token(
    x_admin_token: str = Header(..., alias="X-Admin-Token"),
) -> bool:
    expected = admin_token_or_raise()
    if not x_admin_token or not hmac.compare_digest(x_admin_token.strip(), expected):
        raise HTTPException(status_code=401, detail="Token admin inválido")
    return True


AdminDep = Depends(verify_admin_token)
