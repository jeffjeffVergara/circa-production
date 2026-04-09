"""Test: return same categories back via data_exchange."""
import logging
import json

logger = logging.getLogger("circa.flows.catalogo")

async def handle_catalogo(flow_data: dict) -> dict:
    action = flow_data.get("action", "")
    data = flow_data.get("data", {})
    selected = data.get("selected", "")
    bodega_id = data.get("bodega_id", "") or "b1b2c3d4-0001-4000-8000-000000000001"

    logger.info(f"TEST2: action={action}, selected={selected}")

    if action == "ping":
        return {"version": "3.0", "data": {"status": "active"}}

    # Return EXACT same format as initial payload
    return {
        "version": "3.0",
        "data": {
            "items": [
                {"id": "Abarrotes", "main-content": {"title": "Abarrotes", "description": "Ver productos"}},
                {"id": "Bebidas", "main-content": {"title": "Bebidas", "description": "Ver productos"}},
                {"id": "Golosinas", "main-content": {"title": "Golosinas", "description": "Ver productos"}},
                {"id": "Lacteos", "main-content": {"title": "Lacteos", "description": "Ver productos"}}
            ],
            "bodega_id": bodega_id
        }
    }
