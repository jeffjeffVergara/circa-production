import asyncio
import os
from unittest.mock import AsyncMock, patch

os.environ.setdefault("SUPABASE_URL", "http://localhost")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "test-key")

from app.services.batch_jobs.preview import preview_recordatorio_visita_credito
from app.services.visita_credito_recordatorios import (
    DEFAULT_TEMPLATE_CONFIG,
    compose_visita_credito_mensaje,
    normalize_template_config,
    parse_csv_recipients,
    resolve_item_variables,
)


def test_normalize_template_config_defaults():
    cfg = normalize_template_config()
    assert cfg["template_name"] == "circa_recordatorio_visita_credito"
    assert cfg["language"] == "es_MX"
    assert cfg["variable_keys"] == ["nombre", "aliado", "vendedor", "monto"]


def test_compose_visita_credito_mensaje():
    variables = {
        "nombre": "Juan",
        "aliado": "Dimax (Zoom)",
        "vendedor": "Carlos",
        "monto": "500",
    }
    msg = compose_visita_credito_mensaje(
        telefono="51999888777",
        bodega_nombre="Bodega Test",
        variables=variables,
    )
    assert msg["plantilla"] == "circa_recordatorio_visita_credito"
    assert "Juan" in msg["mensaje_preview"]
    assert msg["mensaje_tipo"] == "whatsapp_template"
    assert len(msg["variables"]) == 4


def test_resolve_item_variables_from_bodega():
    bodega = {
        "representante_nombre_corto": "María",
        "linea_aprobada": 1200,
    }
    vendedor = {"nombre": "Pedro"}
    vals = resolve_item_variables(bodega=bodega, vendedor=vendedor)
    assert vals["nombre"] == "María"
    assert vals["vendedor"] == "Pedro"
    assert vals["monto"] == "1200"
    assert vals["aliado"] == "Dimax (Zoom)"


def test_parse_csv_recipients():
    csv_text = "telefono,nombre,vendedor,monto\n999888777,Ana,Luis,800\n"
    items, errors = parse_csv_recipients(csv_text)
    assert not errors
    assert len(items) == 1
    assert items[0]["telefono"] == "51999888777"
    assert items[0]["variables"][0]["value"] == "Ana"


def test_preview_recordatorio_visita_credito_empty():
    preview = asyncio.run(preview_recordatorio_visita_credito(test="real"))
    assert preview["job_id"] == "recordatorio_visita_credito"
    assert preview["total"] == 0
    assert preview["template_config"]["template_name"] == DEFAULT_TEMPLATE_CONFIG["template_name"]


def test_send_visita_credito_batch_respects_selection():
    items = [
        {
            "item_id": "b1",
            "telefono": "51999111222",
            "bodega_nombre": "B1",
            "variable_values": {
                "nombre": "A",
                "aliado": "Dimax",
                "vendedor": "V",
                "monto": "100",
            },
        },
        {
            "item_id": "b2",
            "telefono": "51999333444",
            "bodega_nombre": "B2",
            "variable_values": {
                "nombre": "B",
                "aliado": "Dimax",
                "vendedor": "V",
                "monto": "200",
            },
        },
    ]
    with patch(
        "app.services.visita_credito_recordatorios.send_visita_credito_item",
        new_callable=AsyncMock,
        return_value={"ok": True},
    ) as mock_send:
        from app.services.visita_credito_recordatorios import send_visita_credito_batch

        result = asyncio.run(send_visita_credito_batch(items=items, selected_ids=["b2"]))
    assert result["sent"] == 1
    mock_send.assert_awaited_once()
    assert mock_send.await_args[0][0]["item_id"] == "b2"
