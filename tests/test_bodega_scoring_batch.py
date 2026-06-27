import os

os.environ.setdefault("SUPABASE_URL", "http://localhost")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "test-key")

from unittest.mock import MagicMock, patch

from app.services.bodega_scoring_batch import run_bodega_scoring_batch


def test_batch_empty():
    with patch("app.services.bodega_scoring_batch.db") as mock_db:
        mock_db.sb.table.return_value.select.return_value.order.return_value.limit.return_value.execute.return_value = MagicMock(data=[])
        result = run_bodega_scoring_batch(test="real", persist=False)
    assert result["total"] == 0
    assert result["bodegas"] == []


def test_batch_scores_and_persist_flag():
    bodega = {
        "id": "b1",
        "nombre_comercial": "Test",
        "razon_social": "Test SAC",
        "representante_legal": "",
        "telefono_whatsapp": "+51999999999",
        "estado": "activo",
        "es_test": False,
        "linea_aprobada": 500,
        "linea_disponible": 500,
        "scoring": 0,
        "distrito": "Lima",
    }

    def table_router(name):
        t = MagicMock()
        if name == "bodegas":
            chain = t.select.return_value.eq.return_value.order.return_value.limit.return_value
            chain.execute.return_value = MagicMock(data=[bodega])
            t.update.return_value.eq.return_value.execute.return_value = MagicMock(data=[bodega])
        elif name == "bodega_features_v1":
            t.select.return_value.in_.return_value.limit.return_value.execute.return_value = MagicMock(
                data=[{"bodega_id": "b1", "frecuencia_compra": 2}]
            )
        elif name == "pedidos":
            t.select.return_value.in_.return_value.order.return_value.limit.return_value.execute.return_value = MagicMock(data=[])
        return t

    with patch("app.services.bodega_scoring_batch.db") as mock_db:
        mock_db.sb.table.side_effect = table_router
        preview = run_bodega_scoring_batch(test="real", persist=False)
        saved = run_bodega_scoring_batch(test="real", persist=True)

    assert preview["total"] == 1
    assert preview["bodegas"][0]["score"] >= 0
    assert preview["persistido"] is False
    assert saved["persistido"] is True
    assert saved["actualizadas"] == 1
