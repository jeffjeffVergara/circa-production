"""Minimal test: hardcoded response for data_exchange."""
import logging
import json

logger = logging.getLogger("circa.flows.catalogo")

async def handle_catalogo(flow_data: dict) -> dict:
    action = flow_data.get("action", "")
    data = flow_data.get("data", {})
    selected = data.get("selected", "")
    bodega_id = data.get("bodega_id", "") or "test"

    logger.info(f"MINIMAL: action={action}, selected={selected}")

    if action == "ping":
        return {"version": "3.0", "data": {"status": "active"}}

    # For ANY data_exchange, return hardcoded products
    return {
        "version": "3.0",
        "data": {
            "items": [
                {"id": "item1", "main-content": {"title": "Leche Gloria 400g", "description": "S/3.50"}},
                {"id": "item2", "main-content": {"title": "Avena 3 Ositos", "description": "S/2.80"}},
                {"id": "BACK", "main-content": {"title": "Volver", "description": "Categorias"}}
            ],
            "bodega_id": bodega_id
        }
    }
