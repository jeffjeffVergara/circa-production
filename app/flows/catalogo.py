"""TEST5: screen field + different data."""
import logging

logger = logging.getLogger("circa.flows.catalogo")

async def handle_catalogo(flow_data: dict) -> dict:
    action = flow_data.get("action", "")
    data = flow_data.get("data", {})
    selected = data.get("selected", "")
    bodega_id = data.get("bodega_id", "") or "b1b2c3d4-0001-4000-8000-000000000001"
    cart_state = data.get("cart_state", "{}")

    logger.info(f"TEST5: action={action}, selected={selected}")

    if action == "ping":
        return {"version": "3.0", "data": {"status": "active"}}

    # Return DIFFERENT items to prove screen updates
    return {
        "version": "3.0",
        "screen": "CATALOG",
        "data": {
            "items": [
                {"id": "prod1", "main-content": {"title": "Leche Gloria 400g", "description": "S/3.50 | Pack x24"}},
                {"id": "prod2", "main-content": {"title": "Avena 3 Ositos 500g", "description": "S/2.80 | Pack x12"}},
                {"id": "prod3", "main-content": {"title": "Fideos Don Vittorio", "description": "S/2.50 | Pack x20"}},
                {"id": "BACK", "main-content": {"title": "Volver a categorias", "description": ""}}
            ],
            "bodega_id": bodega_id,
            "cart_state": cart_state
        }
    }
