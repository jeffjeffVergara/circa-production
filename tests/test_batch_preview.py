import asyncio
import os

os.environ.setdefault("SUPABASE_URL", "http://localhost")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "test-key")

from unittest.mock import MagicMock, patch

from app.services.batch_jobs.preview import build_preview, preview_marcar_vencidos


def test_preview_unknown_job():
    try:
        asyncio.run(build_preview("no_existe"))
        assert False, "expected ValueError"
    except ValueError as e:
        assert "desconocido" in str(e).lower()


def test_preview_marcar_vencidos_filters_test():
    with patch("app.services.batch_jobs.preview.db") as mock_db:
        mock_db.sb.table.return_value.select.return_value.eq.return_value.lt.return_value.execute.return_value = MagicMock(
            data=[
                {
                    "id": "f1",
                    "bodega_id": "b1",
                    "monto_total": 100,
                    "fecha_vencimiento": "2020-01-01",
                    "pedidos": {"numero": "P-1"},
                    "bodegas": {
                        "nombre_comercial": "Real SA",
                        "telefono_whatsapp": "999111222",
                        "es_test": False,
                    },
                },
                {
                    "id": "f2",
                    "bodega_id": "b2",
                    "monto_total": 50,
                    "fecha_vencimiento": "2020-01-01",
                    "pedidos": {"numero": "P-2"},
                    "bodegas": {
                        "nombre_comercial": "Test SA",
                        "telefono_whatsapp": "999333444",
                        "es_test": True,
                    },
                },
            ]
        )
        preview = asyncio.run(preview_marcar_vencidos(test="real"))
    assert preview["total"] == 1
    assert preview["items"][0]["bodega_nombre"] == "Real SA"
    assert preview["items"][0]["telefono"] == "999111222"


def test_preview_score_job():
    with patch("app.services.batch_jobs.preview.run_bodega_scoring_batch") as mock_score:
        mock_score.return_value = {
            "bodegas": [
                {
                    "bodega_id": "b1",
                    "nombre": "Bodega Uno",
                    "telefono_whatsapp": "987654321",
                    "es_test": False,
                    "score": 80,
                    "grade": "B",
                    "scoring_anterior": 75,
                    "linea_disponible": 200,
                }
            ]
        }
        preview = asyncio.run(build_preview("score_bodegas_diario", test="real"))
    assert preview["total"] == 1
    assert preview["items"][0]["telefono"] == "987654321"
    assert "Score 80" in preview["items"][0]["detalle"]
