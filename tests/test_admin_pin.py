"""Admin PIN set/reset desde panel de soporte."""
import asyncio
import os
from unittest.mock import patch

import pytest
from fastapi import HTTPException

os.environ["CIRCA_ADMIN_TOKEN"] = "test-admin-token"

from app.routes import distribuidor as dist


def test_verify_admin_action_rejects_bad_token():
    with pytest.raises(HTTPException) as exc:
        dist._verify_admin_action("wrong")
    assert exc.value.status_code == 403


@patch("app.services.twilio_client.send_whatsapp")
@patch("app.services.analytics.track_event")
@patch("app.services.db.upsert_session")
@patch("app.services.db.update_bodega")
@patch("app.routes.distribuidor._sb_get")
def test_admin_reset_pin_ok(mock_get, mock_update, mock_upsert, mock_track, mock_wa):
    mock_get.return_value = [{"id": "b1", "telefono_whatsapp": "+51999999999", "nombre_comercial": "Test"}]

    payload = dist.AdminPinAction(
        comentario="Bodeguero olvidó clave, validé por teléfono",
        autorizacion="test-admin-token",
    )
    result = asyncio.run(dist.admin_reset_pin("b1", payload, admin=True))

    assert result["ok"] is True
    mock_update.assert_called_once()
    mock_upsert.assert_called_once()
    mock_track.assert_called_once()
    assert mock_track.call_args.kwargs["event_type"] == "pin_reset_admin"
    assert mock_track.call_args.kwargs["metadata"]["comentario"] == payload.comentario


@patch("app.services.twilio_client.send_whatsapp")
@patch("app.services.analytics.track_event")
@patch("app.services.db.upsert_session")
@patch("app.services.db.update_bodega")
@patch("app.services.pin.hash_pin", return_value="$2b$hashed")
@patch("app.services.pin.validate_pin_format", return_value=(True, ""))
@patch("app.routes.distribuidor._sb_get")
def test_admin_set_pin_ok(mock_get, mock_validate, mock_hash, mock_update, mock_upsert, mock_track, mock_wa):
    mock_get.return_value = [{"id": "b1", "telefono_whatsapp": "+51999999999"}]

    payload = dist.AdminPinSet(
        comentario="Asignación temporal tras soporte telefónico",
        autorizacion="test-admin-token",
        pin="5678",
        pin_confirm="5678",
    )
    result = asyncio.run(dist.admin_set_pin("b1", payload, admin=True))

    assert result["ok"] is True
    mock_update.assert_called_once()
    mock_hash.assert_called_once_with("5678")
    mock_track.assert_called_once()
    assert mock_track.call_args.kwargs["event_type"] == "pin_set_admin"
