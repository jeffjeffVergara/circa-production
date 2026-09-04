"""Circa Integration API — paquete público para socios distribuidores."""

from __future__ import annotations

from typing import TYPE_CHECKING

__all__ = ["integration_app"]

if TYPE_CHECKING:
    from fastapi import FastAPI


def __getattr__(name: str):
    if name == "integration_app":
        from app.integration.app import integration_app

        return integration_app
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
