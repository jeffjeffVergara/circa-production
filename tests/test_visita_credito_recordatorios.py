import asyncio
import os
from unittest.mock import AsyncMock, patch

os.environ.setdefault("SUPABASE_URL", "http://localhost")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "test-key")

from app.services.batch_jobs.preview import preview_recordatorio_visita_credito
from app.services.batch_jobs.visita_credito_jobs import run_recordatorio_visita_credito
from app.services.visita_credito_recordatorios import (
    DEFAULT_TEMPLATE_CONFIG,
    compose_visita_credito_mensaje,
    filter_items_by_test_mode,
    normalize_template_config,
    parse_csv_recipients,
    resolve_item_variables,
)


def test_normalize_template_config_defaults():
    cfg = normalize_template_config()
    assert cfg["template_name"] == "circa_recordatorio_visita_credito"
    assert cfg["language"] == "es_MX"
    assert cfg["variable_keys"] == ["nombre", "aliado", "vendedor", "monto"]


def test_compose_visita_credito_mensaje_shows_csv_vendedor_as_aliado():
    variables = {
        "nombre": "Jeff",
        "aliado": "Carlos",
        "vendedor": "tu vendedor",
        "monto": "500",
    }
    msg = compose_visita_credito_mensaje(
        telefono="51942616682",
        bodega_nombre="Bodega Jeff",
        variables=variables,
    )
    assert "aliado de Carlos" in msg["mensaje_preview"]


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
    assert "Plantilla Meta:" not in msg["mensaje_preview"]
    assert "Dimax (Zoom)" in msg["mensaje_preview"]
    assert msg["body_rendered"] == msg["mensaje_preview"]
    assert msg["mensaje_tipo"] == "whatsapp_template"
    assert len(msg["variables"]) == 4


def test_resolve_item_variables_csv_vendedor_goes_to_aliado():
    vals = resolve_item_variables(
        overrides={"vendedor": "Carlos", "nombre": "Juan", "monto": "500"},
    )
    assert vals["aliado"] == "Carlos"
    assert vals["vendedor"] == "tu vendedor"
    assert vals["nombre"] == "Juan"


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
    csv_text = "nombre,vendedor,monto,telefono\nBodega Test,Ana,800,999888777\n"
    bodega = {
        "id": "b1",
        "nombre_comercial": "Bodega Test",
        "telefono_whatsapp": "51999888777",
        "representante_nombre_corto": "Ana",
        "linea_aprobada": 500,
        "es_test": False,
    }
    with patch(
        "app.services.visita_credito_recordatorios._resolve_bodega_by_nombre",
        return_value=(bodega, ""),
    ), patch(
        "app.services.visita_credito_recordatorios._fetch_bodegas_by_ids",
        return_value={"b1": bodega},
    ), patch(
        "app.services.visita_credito_recordatorios._fetch_vendedores_por_bodega",
        return_value={},
    ):
        items, errors = parse_csv_recipients(csv_text)
    assert not errors
    assert len(items) == 1
    assert items[0]["telefono"] == "51999888777"
    aliado_var = next(v for v in items[0]["variables"] if v["name"] == "aliado")
    assert aliado_var["value"] == "Ana"


def test_parse_csv_uses_csv_telefono_even_when_bodega_has_other_phone():
    csv_text = "nombre,vendedor,monto,telefono\nBodega Test,Luis,500,912345678\n"
    bodega = {
        "id": "b1",
        "nombre_comercial": "Bodega Test",
        "telefono_whatsapp": "51911111111",
        "es_test": False,
    }
    with patch(
        "app.services.visita_credito_recordatorios._resolve_bodega_by_nombre",
        return_value=(bodega, ""),
    ), patch(
        "app.services.visita_credito_recordatorios._fetch_bodegas_by_ids",
        return_value={"b1": bodega},
    ), patch(
        "app.services.visita_credito_recordatorios._fetch_vendedores_por_bodega",
        return_value={},
    ):
        items, errors = parse_csv_recipients(csv_text)
    assert not errors
    assert items[0]["telefono"] == "51912345678"
    assert items[0]["telefono_envio"] == "51912345678"


def test_parse_csv_uses_csv_telefono_without_bodega_match():
    csv_text = "nombre,vendedor,monto,telefono\nBodega Nueva,Luis,500,912345678\n"
    with patch(
        "app.services.visita_credito_recordatorios._resolve_bodega_by_nombre",
        return_value=(None, "bodega no encontrada"),
    ):
        items, errors = parse_csv_recipients(csv_text)
    assert not errors
    assert len(items) == 1
    assert items[0]["telefono"] == "51912345678"


def test_parse_csv_accepts_legacy_aliado_column_as_vendedor():
    csv_text = "nombre,aliado,monto,telefono\nBodega Legacy,Luis,500,912345678\n"
    with patch(
        "app.services.visita_credito_recordatorios._resolve_bodega_by_nombre",
        return_value=(None, "bodega no encontrada"),
    ):
        items, errors = parse_csv_recipients(csv_text)
    assert not errors
    aliado_var = next(v for v in items[0]["variables"] if v["name"] == "aliado")
    assert aliado_var["value"] == "Luis"


def test_build_items_for_send_uses_csv_telefono_not_bodega():
    bodega = {
        "id": "b1",
        "nombre_comercial": "Bodega Test",
        "telefono_whatsapp": "51911111111",
        "es_test": False,
    }
    custom = [
        {
            "item_id": "csv-1",
            "nombre": "Bodega Test",
            "vendedor": "Ana",
            "monto": "800",
            "telefono": "51999888777",
            "telefono_envio": "51999888777",
            "bodega_id": "b1",
            "source": "csv",
        }
    ]
    with patch(
        "app.services.visita_credito_recordatorios._fetch_bodegas_by_ids",
        return_value={"b1": bodega},
    ), patch(
        "app.services.visita_credito_recordatorios._fetch_vendedores_por_bodega",
        return_value={},
    ):
        from app.services.visita_credito_recordatorios import build_items_for_send

        items = build_items_for_send(custom)
    assert len(items) == 1
    assert items[0]["telefono"] == "51999888777"
    assert items[0]["telefono_envio"] == "51999888777"
    assert items[0]["variable_values"]["aliado"] == "Ana"


def test_parse_csv_rejects_wrong_columns():
    csv_text = "telefono,nombre\n999,Juan\n"
    items, errors = parse_csv_recipients(csv_text)
    assert not items
    assert errors and "nombre (bodega)" in errors[0]


def test_filter_items_by_test_mode_keeps_csv_in_real_mode():
    items = [
        {"item_id": "csv-1", "source": "csv", "es_test": True, "telefono": "51999111222"},
        {"item_id": "b-test", "source": "bodega", "es_test": True, "telefono": "51999222333"},
        {"item_id": "b-real", "source": "bodega", "es_test": False, "telefono": "51999333444"},
    ]
    out = filter_items_by_test_mode(items, "real")
    assert [i["item_id"] for i in out] == ["csv-1", "b-real"]


def test_run_recordatorio_visita_credito_sends_csv_despite_test_bodega_flag():
    custom = [
        {
            "item_id": "csv-1",
            "nombre": "Bodega",
            "vendedor": "Ana",
            "monto": "500",
            "telefono": "51999888777",
            "telefono_envio": "51999888777",
            "bodega_id": "b1",
            "source": "csv",
            "es_test": True,
        }
    ]
    with patch(
        "app.services.visita_credito_recordatorios._fetch_bodegas_by_ids",
        return_value={
            "b1": {
                "id": "b1",
                "nombre_comercial": "Bodega",
                "es_test": True,
            }
        },
    ), patch(
        "app.services.visita_credito_recordatorios._fetch_vendedores_por_bodega",
        return_value={},
    ), patch(
        "app.services.visita_credito_recordatorios.send_visita_credito_item",
        new_callable=AsyncMock,
        return_value={"ok": True, "plantilla": "circa_recordatorio_visita_credito"},
    ) as mock_send:
        result = asyncio.run(
            run_recordatorio_visita_credito(
                dry_run=False,
                test="real",
                selected_ids=["csv-1"],
                custom_items=custom,
            )
        )
    assert result["ok"] == 1
    mock_send.assert_awaited_once()


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
