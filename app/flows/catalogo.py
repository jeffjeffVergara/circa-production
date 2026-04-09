"""Test: include cart_state in response."""
import logging

logger = logging.getLogger("circa.flows.catalogo")

async def handle_catalogo(flow_data: dict) -> dict:
    action = flow_data.get("action", "")
    data = flow_data.get("data", {})
    selected = data.get("selected", "")
    bodega_id = data.get("bodega_id", "") or "b1b2c3d4-0001-4000-8000-000000000001"

    logger.info(f"TEST4: action={action}, selected={selected}")

    if action == "ping":
        return {"version": "3.0", "data": {"status": "active"}}

    return {
        "version": "3.0",
        "data": {
            "items": [
                {"id": "item1", "main-content": {"title": "Leche Gloria 400g", "description": "S/3.50"}},
                {"id": "item2", "main-content": {"title": "Avena 3 Ositos", "description": "S/2.80"}},
                {"id": "BACK", "main-content": {"title": "Volver", "description": "Categorias"}}
            ],
            "bodega_id": bodega_id,
            "cart_state": "{}"
        }
    }
