"""Interpretación UI del botón Circa según respuesta SVC-01 (§6.4).

BsSoft (o cualquier socio) debe usar el campo `situacion` de cada bodega
(o el `situacion` del listado) tras `GET /bodegas?q=...` / `GET /bodegas/{id}`.
"""

from __future__ import annotations

from typing import Any, Literal, Optional

SituacionBodega = Literal[
    "no_registrada",
    "en_evaluacion",
    "no_disponible",
    "con_linea",
]

# Alias histórico: franja UI = situacion (+ sin_conexion en errores de red)
FranjaUI = Literal[
    "sin_conexion",
    "no_registrada",
    "en_evaluacion",
    "no_disponible",
    "con_linea",
]

FRANJA_ACCION = {
    "sin_conexion": "No mostrar franja Circa; pedido sigue al contado",
    "no_registrada": "Caso A — ofrecer Precargar bodega (SVC-02)",
    "en_evaluacion": "Data ya enviada; no reenviar SVC-02; reconsultar luego",
    "no_disponible": "Mostrar No disponible; no precargar ni financiar",
    "con_linea": "Caso B — ofrecer Enviar solicitud (SVC-04)",
}

# Compat: código/docs antiguos usaban sin_linea
_SIN_LINEA_ALIASES = frozenset({"sin_linea"})


def calcular_situacion(bodega: dict[str, Any]) -> SituacionBodega:
    """Situación de una bodega ya existente en Circa."""
    estado = (bodega.get("estado") or "").strip().lower()
    try:
        disponible = float(bodega.get("linea_disponible") or 0)
    except (TypeError, ValueError):
        disponible = 0.0

    if estado != "activo":
        return "en_evaluacion"
    if disponible <= 0:
        return "no_disponible"
    return "con_linea"


def interpretar_franja_svc01(
    *,
    http_status: Optional[int] = None,
    timed_out: bool = False,
    total: Optional[int] = None,
    items: Optional[list[dict[str, Any]]] = None,
    bodega: Optional[dict[str, Any]] = None,
    situacion: Optional[str] = None,
) -> FranjaUI:
    """Clasifica la situación UI del botón Circa.

    Usar con listado SVC-01 (`total` + `items` + `situacion`) o con un
    item/bodega ya elegido (SVC-01b). Ante timeout o 5xx → sin_conexion.
    """
    if timed_out:
        return "sin_conexion"
    if http_status is not None and http_status >= 500:
        return "sin_conexion"
    if http_status is not None and http_status == 401:
        return "sin_conexion"
    if http_status is not None and http_status == 404:
        # Solo aplica a SVC-01b (bodega por id)
        return "no_registrada"

    if bodega is None:
        items = items or []
        if total is not None and total == 0:
            return "no_registrada"
        if not items:
            return "no_registrada"
        if situacion in ("no_registrada", "en_evaluacion", "no_disponible", "con_linea"):
            return situacion  # type: ignore[return-value]
        s = items[0].get("situacion")
        if s in FRANJA_ACCION and s != "sin_conexion":
            return s  # type: ignore[return-value]
        bodega = items[0]
    elif situacion in ("no_registrada", "en_evaluacion", "no_disponible", "con_linea"):
        return situacion  # type: ignore[return-value]

    if bodega.get("situacion") in ("en_evaluacion", "no_disponible", "con_linea", "no_registrada"):
        return bodega["situacion"]  # type: ignore[return-value]

    return calcular_situacion(bodega)


def describir_franja(franja: FranjaUI | str) -> str:
    if franja in _SIN_LINEA_ALIASES:
        franja = "no_registrada"
    return FRANJA_ACCION.get(franja, FRANJA_ACCION["no_registrada"])  # type: ignore[arg-type]
