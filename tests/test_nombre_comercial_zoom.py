"""2.3 — mensajes al cliente usan nombre_comercial (ZOOM), no 'DIMAX' hardcodeado."""
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ.setdefault("SUPABASE_URL", "http://localhost")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "test-key")
os.environ.setdefault("SUPABASE_KEY", "test-key")

from app.services.credit_model.whatsapp_generator import generar_mensaje
from app.services import db


def test_get_nombre_comercial_from_distribuidor_id():
    mock_sb = MagicMock()
    mock_sb.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(
        data=[{"nombre_comercial": "ZOOM"}]
    )
    with patch.object(db, "sb", mock_sb):
        assert (
            db.get_nombre_comercial_distribuidor(
                distribuidor_id="d1a2b3c4-0001-4000-8000-000000000002"
            )
            == "ZOOM"
        )


def test_generar_mensaje_usa_nombre_comercial():
    payload = {
        "cliente": {"RazonSocial": "Bodega El Sol", "Telefono": "51999999999"},
        "sql": {"vendedores": [{"nombre": "Juan Perez", "dia_visita": "lunes"}]},
        "distribuidor_id": "d1a2b3c4-0001-4000-8000-000000000002",
    }
    with patch(
        "app.services.db.get_nombre_comercial_distribuidor",
        return_value="ZOOM",
    ):
        msg = generar_mensaje(payload)
    assert "de ZOOM." in msg
    assert "de DIMAX." not in msg
