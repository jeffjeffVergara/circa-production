"""Interpretación UI del botón Circa según respuesta SVC-01 (§6.4).

BsSoft (o cualquier socio) debe aplicar estas reglas al pintar la franja
tras `GET /bodegas?q=...` o al evaluar un item de `GET /bodegas/{id}`.
"""

from __future__ import annotations

from typing import Any, Literal, Optional

FranjaUI = Literal[
    "sin_conexion",
    "sin_linea",
    "no_disponible",
    "con_linea",
]

FRANJA_ACCION = {
    "sin_conexion": "No mostrar franja Circa; pedido sigue al contado",
    "sin_linea": "Caso A — ofrecer Precargar bodega (SVC-02)",
    "no_disponible": "Mostrar No disponible; no precargar ni financiar",
    "con_linea": "Caso B — ofrecer Enviar solicitud (SVC-04)",
}


def interpretar_franja_svc01(
    *,
    http_status: Optional[int] = None,
    timed_out: bool = False,
    total: Optional[int] = None,
    items: Optional[list[dict[str, Any]]] = None,
    bodega: Optional[dict[str, Any]] = None,
) -> FranjaUI:
    """Clasifica el estado UI del botón Circa.

    Usar con listado SVC-01 (`total` + `items`) o con un item/bodega
    ya elegido (SVC-01b). Ante timeout o 5xx → sin_conexion.
    """
    if timed_out:
        return "sin_conexion"
    if http_status is not None and http_status >= 500:
        return "sin_conexion"
    if http_status is not None and http_status == 401:
        return "sin_conexion"
    if http_status is not None and http_status == 404:
        # Solo aplica a SVC-01b (bodega por id)
        return "sin_linea"

    if bodega is None:
        items = items or []
        if total is not None and total == 0:
            return "sin_linea"
        if not items:
            return "sin_linea"
        bodega = items[0]

    estado = (bodega.get("estado") or "").strip().lower()
    try:
        disponible = float(bodega.get("linea_disponible") or 0)
    except (TypeError, ValueError):
        disponible = 0.0

    if estado != "activo":
        return "sin_linea"
    if disponible <= 0:
        return "no_disponible"
    return "con_linea"


def describir_franja(franja: FranjaUI) -> str:
    return FRANJA_ACCION[franja]
