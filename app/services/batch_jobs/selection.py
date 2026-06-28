"""Metadatos y utilidades de selección parcial en jobs batch."""

from __future__ import annotations

from typing import Any, Optional

SELECTION_META: dict[str, dict[str, str]] = {
    "score_bodegas_diario": {
        "entity_label": "bodegas",
        "hint": "Elige las bodegas que entrarán al cálculo de score.",
        "search_bodega": "Filtrar bodega…",
        "search_telefono": "Filtrar teléfono WA…",
        "search_vendedor": "Filtrar vendedor…",
    },
    "recordatorios_cobranza": {
        "entity_label": "recordatorios",
        "hint": "Elige bodegas o números WA que recibirán el recordatorio.",
        "search_bodega": "Filtrar bodega…",
        "search_telefono": "Filtrar teléfono WA…",
        "search_vendedor": "",
    },
    "marcar_vencidos": {
        "entity_label": "financiamientos",
        "hint": "Elige qué créditos vencidos marcar (por bodega o pedido).",
        "search_bodega": "Filtrar bodega…",
        "search_telefono": "Filtrar teléfono WA…",
        "search_vendedor": "",
    },
    "onboarding_abandonado": {
        "entity_label": "bodegas",
        "hint": "Selección parcial disponible cuando el job esté implementado.",
        "search_bodega": "Filtrar bodega…",
        "search_telefono": "Filtrar teléfono…",
        "search_vendedor": "Filtrar vendedor…",
    },
    "reactivacion_inactivos": {
        "entity_label": "bodegas",
        "hint": "Selección parcial disponible cuando el job esté implementado.",
        "search_bodega": "Filtrar bodega…",
        "search_telefono": "Filtrar teléfono…",
        "search_vendedor": "Filtrar vendedor…",
    },
}


def get_selection_meta(job_id: str) -> dict[str, str]:
    return SELECTION_META.get(job_id, {
        "entity_label": "destinatarios",
        "hint": "Marca los destinatarios a incluir en la ejecución.",
        "search_bodega": "Filtrar bodega…",
        "search_telefono": "Filtrar teléfono…",
        "search_vendedor": "",
    })


def filter_preview_items(
    preview: dict[str, Any],
    selected_ids: Optional[list[str]],
) -> dict[str, Any]:
    if not selected_ids:
        return preview
    allowed = {str(x) for x in selected_ids}
    items = [i for i in (preview.get("items") or []) if str(i.get("item_id")) in allowed]
    out = dict(preview)
    out["items"] = items
    out["total"] = len(items)
    out["mostrando"] = len(items)
    out["truncated"] = False
    out["con_telefono"] = sum(1 for i in items if i.get("telefono"))
    out["note"] = (out.get("note") or "") + f" Selección manual: {len(items)} destinatario(s)."
    return out
