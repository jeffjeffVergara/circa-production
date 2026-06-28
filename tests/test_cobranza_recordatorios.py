import asyncio
import os
from datetime import date, datetime, timezone

os.environ.setdefault("SUPABASE_URL", "http://localhost")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "test-key")

from unittest.mock import AsyncMock, MagicMock, patch

from app.services.batch_jobs.preview import preview_recordatorios
from app.services.cobranza_recordatorios import (
    compose_recordatorio_mensaje,
    pedido_elegible_recordatorio,
    plantilla_recordatorio_key,
    status_cobranza_pedido,
)


def test_compose_recordatorio_mensaje():
    pedido = {
        "numero": "CRC-100",
        "monto_financiado": 200,
        "fee_monto": 20,
        "monto_total_credito": 220,
        "fecha_entregado": "2026-06-01T12:00:00+00:00",
        "plazo_dias": 7,
    }
    bodega = {
        "nombre_comercial": "Bodega Test",
        "telefono_whatsapp": "51999888777",
        "representante_nombre_corto": "Juan",
        "linea_aprobada": 500,
    }
    msg = compose_recordatorio_mensaje(pedido, bodega)
    assert msg["plantilla"]
    assert "51999888777" in msg["mensaje_preview"]
    assert "{1} nombre" in msg["mensaje_preview"]
    assert msg["mensaje_tipo"] == "whatsapp_template"


    hoy = date(2026, 6, 3)
    assert pedido_elegible_recordatorio({"estado": "entregado", "monto_financiado": 100}, hoy)
    assert pedido_elegible_recordatorio({"estado": "pago_reportado", "monto_financiado": 50}, hoy)
    assert not pedido_elegible_recordatorio({"estado": "pagado", "monto_financiado": 100}, hoy)
    assert not pedido_elegible_recordatorio({"estado": "entregado", "monto_financiado": 0}, hoy)
    assert not pedido_elegible_recordatorio({"estado": "confirmado", "monto_financiado": 100}, hoy)


def test_status_cobranza_pedido():
    hoy = date(2026, 6, 10)
    assert status_cobranza_pedido({"estado": "pagado"}, hoy) == "pagado"
    assert status_cobranza_pedido({"estado": "pago_reportado"}, hoy) == "pago_reportado"
    ped = {
        "estado": "entregado",
        "fecha_vencimiento": "2026-06-20",
        "plazo_dias": 7,
    }
    assert status_cobranza_pedido(ped, hoy) == "al_dia"
    ped_venc = {"estado": "entregado", "fecha_vencimiento": "2026-06-05"}
    assert status_cobranza_pedido(ped_venc, hoy) == "vencido"


def test_plantilla_recordatorio_key():
    hace_2 = (datetime.now(timezone.utc)).isoformat()
    assert plantilla_recordatorio_key({"fecha_entregado": hace_2}) == "dia2"


def test_preview_recordatorios_uses_pedidos():
    pedidos = [
        {
            "id": "p1",
            "numero": "CRC-001",
            "bodega_id": "b1",
            "estado": "entregado",
            "monto_financiado": 200,
            "fee_monto": 20,
            "monto_total_credito": 220,
            "fecha_vencimiento": "2026-07-01",
            "fecha_entregado": "2026-06-01T12:00:00+00:00",
            "plazo_dias": 7,
        },
        {
            "id": "p2",
            "numero": "CRC-002",
            "bodega_id": "b2",
            "estado": "pagado",
            "monto_financiado": 100,
        },
    ]
    bodegas = [
        {
            "id": "b1",
            "nombre_comercial": "Bodega Real",
            "telefono_whatsapp": "999888777",
            "es_test": False,
        }
    ]

    mock_pedidos = MagicMock()
    mock_pedidos.select.return_value.in_.return_value.order.return_value.limit.return_value.execute.return_value = MagicMock(
        data=pedidos
    )
    mock_bodegas = MagicMock()
    mock_bodegas.select.return_value.in_.return_value.execute.return_value = MagicMock(data=bodegas)
    mock_test_bodegas = MagicMock()
    mock_test_bodegas.select.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(
        data=[{"id": "b1"}]
    )

    def table_router(name):
        if name == "pedidos":
            return mock_pedidos
        if name == "bodegas":
            t = MagicMock()
            t.select.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(
                data=[{"id": "b1"}]
            )
            t.select.return_value.in_.return_value.execute.return_value = MagicMock(data=bodegas)
            return t
        return MagicMock()

    with patch("app.services.cobranza_recordatorios.db") as mock_db:
        mock_db.sb.table.side_effect = table_router
        preview = asyncio.run(preview_recordatorios(test="real"))

    assert preview["total"] == 1
    assert preview["items"][0]["item_id"] == "p1"
    assert preview["items"][0]["pedido_id"] == "p1"
    assert preview["items"][0]["telefono"] == "999888777"


def test_send_recordatorios_batch_respects_selection():
    items = [
        {"pedido_id": "p1", "telefono": "999"},
        {"pedido_id": "p2", "telefono": "888"},
    ]
    with patch(
        "app.services.cobranza_recordatorios.list_recordatorio_preview_items",
        return_value=items,
    ):
        with patch(
            "app.services.cobranza_recordatorios.send_recordatorio_pedido",
            new_callable=AsyncMock,
            return_value={"ok": True, "pedido": "CRC-1"},
        ) as mock_send:
            from app.services.cobranza_recordatorios import send_recordatorios_batch

            result = asyncio.run(send_recordatorios_batch(pedido_ids=["p2"]))
    assert result["sent"] == 1
    mock_send.assert_awaited_once_with("p2")
