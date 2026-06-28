import os

os.environ.setdefault("SUPABASE_URL", "http://localhost")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "test-key")

from unittest.mock import patch

from app.services.batch_jobs.selection import filter_preview_items
from app.services.bodega_scoring_batch import run_bodega_scoring_batch


def test_filter_preview_items():
    preview = {
        "items": [
            {"item_id": "a", "bodega_nombre": "A"},
            {"item_id": "b", "bodega_nombre": "B"},
        ],
        "note": "base",
    }
    out = filter_preview_items(preview, ["a"])
    assert out["total"] == 1
    assert out["items"][0]["item_id"] == "a"


def test_scoring_batch_filters_bodega_ids():
    with patch("app.services.bodega_scoring_batch._fetch_bodegas") as mock_fetch:
        mock_fetch.return_value = [
            {"id": "b1", "nombre_comercial": "Uno", "es_test": False},
            {"id": "b2", "nombre_comercial": "Dos", "es_test": False},
        ]
        with patch("app.services.bodega_scoring_batch._fetch_features", return_value={}):
            with patch("app.services.bodega_scoring_batch._fetch_pedidos", return_value={"b1": [], "b2": []}):
                with patch("app.services.bodega_scoring_batch.compute_bodega_score") as mock_score:
                    mock_score.return_value = {
                        "score": 70,
                        "grade": "B",
                        "label": "Bueno",
                        "breakdown": {},
                        "metrics": {},
                    }
                    result = run_bodega_scoring_batch(test="real", persist=False, bodega_ids=["b2"])
    assert result["total"] == 1
    assert result["bodegas"][0]["bodega_id"] == "b2"
