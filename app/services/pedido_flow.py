"""
Progreso visual del pedido para backoffice (pipeline tipo BPMN).

Dos flujos principales:
- venta: borrador → logística → cobranza (si hay financiamiento)
- preventa: preventa_* hasta entrega
"""
from __future__ import annotations

from app.services.order_status import normalize_estado

# Logística post-confirmación (venta)
VENTA_LOGISTICA: list[dict] = [
    {"id": "confirmado", "label": "Nuevo", "icon": "📋", "phase": "logistica"},
    {"id": "recibido", "label": "Recibido", "icon": "✅", "phase": "logistica"},
    {"id": "en_preparacion", "label": "Preparación", "icon": "📦", "phase": "logistica"},
    {"id": "despachado", "label": "Despachado", "icon": "🚚", "phase": "logistica"},
    {"id": "en_camino", "label": "En camino", "icon": "🛣️", "phase": "logistica"},
    {"id": "entregado", "label": "Entregado", "icon": "🎉", "phase": "logistica"},
]

VENTA_PRECONFIRMACION: list[dict] = [
    {"id": "borrador", "label": "Borrador", "icon": "🛒", "phase": "carrito"},
]

VENTA_COBRANZA: list[dict] = [
    {"id": "pago_reportado", "label": "Pago reportado", "icon": "📲", "phase": "cobranza"},
    {"id": "pagado", "label": "Pagado", "icon": "💚", "phase": "cobranza"},
]

PREVENTA_PIPELINE: list[dict] = [
    {"id": "preventa_borrador", "label": "Borrador", "icon": "🛒", "phase": "preventa"},
    {"id": "preventa_confirmada", "label": "Confirmada", "icon": "📋", "phase": "preventa"},
    {"id": "preventa_aceptada", "label": "Aceptada", "icon": "✅", "phase": "preventa"},
    {"id": "preventa_en_preparacion", "label": "Preparación", "icon": "📦", "phase": "preventa"},
    {"id": "preventa_despachada", "label": "Despachada", "icon": "🚚", "phase": "preventa"},
    {"id": "preventa_entregada", "label": "Entregada", "icon": "🎉", "phase": "preventa"},
]

TERMINAL_FAILURE = frozenset({
    "cancelado", "rechazado", "preventa_cancelada", "preventa_rechazada",
})

TERMINAL_SUCCESS = frozenset({"pagado", "completed", "preventa_entregada"})

# Estados fuera del pipeline lineal pero informativos
VENTA_ALIASES_INDEX: dict[str, int] = {
    "aprobado": 0,
    "preparando": 2,
}


def _step_status(idx: int, current_idx: int, *, terminal_failure: bool) -> str:
    if terminal_failure:
        return "skipped"
    if current_idx < 0:
        return "pending"
    if idx < current_idx:
        return "done"
    if idx == current_idx:
        return "current"
    return "pending"


def _annotate_steps(steps: list[dict], current_idx: int, *, terminal_failure: bool) -> list[dict]:
    out = []
    for i, s in enumerate(steps):
        st = _step_status(i, current_idx, terminal_failure=terminal_failure)
        out.append({**s, "status": st, "index": i})
    return out


def _resolve_venta_index(estado: str) -> int:
    e = normalize_estado(estado)
    if e in VENTA_ALIASES_INDEX:
        return VENTA_ALIASES_INDEX[e]
    ids = [s["id"] for s in VENTA_LOGISTICA]
    if e in ids:
        return ids.index(e)
    if e == "pago_reportado":
        return len(VENTA_LOGISTICA)  # first cobranza step (virtual index)
    if e == "pagado":
        return len(VENTA_LOGISTICA) + len(VENTA_COBRANZA) - 1
    if e == "borrador":
        return -1
    return -2  # desconocido / fuera de flujo


def _resolve_preventa_index(estado: str) -> int:
    e = (estado or "").strip()
    ids = [s["id"] for s in PREVENTA_PIPELINE]
    if e in ids:
        return ids.index(e)
    return -2


def flujo_resumen(progress: dict) -> dict:
    """Subconjunto ligero para listas (tabla pedidos)."""
    cur = progress.get("current_step") or {}
    return {
        "percent": progress.get("percent", 0),
        "completed_steps": progress.get("completed_steps", 0),
        "total_steps": progress.get("total_steps", 0),
        "remaining_steps": progress.get("remaining_steps", 0),
        "current_label": cur.get("label"),
        "is_terminal": progress.get("is_terminal"),
        "is_failure": progress.get("is_failure"),
    }


def build_pedido_flow_progress(pedido: dict) -> dict:
    """
    Devuelve estructura para UI: pasos, índice actual, % y fases BPMN.
    """
    estado = (pedido.get("estado") or "").strip()
    tipo = (pedido.get("tipo_operacion") or "venta").strip().lower()
    monto_fin = float(pedido.get("monto_financiado") or 0)
    is_preventa = tipo == "preventa"

    if is_preventa:
        pipeline = list(PREVENTA_PIPELINE)
        current_idx = _resolve_preventa_index(estado)
        phases = [{"id": "preventa", "label": "Pre-venta", "steps": PREVENTA_PIPELINE}]
        pipeline_label = "Flujo de pre-venta"
    else:
        phases = []
        if estado == "borrador":
            phases = [{"id": "carrito", "label": "Carrito", "steps": VENTA_PRECONFIRMACION}]
        if estado == "borrador":
            steps_pre = _annotate_steps(VENTA_PRECONFIRMACION, 0, terminal_failure=False)
            steps_log = _annotate_steps(VENTA_LOGISTICA, -1, terminal_failure=False)
            cob_steps = VENTA_COBRANZA if monto_fin > 0 else []
            steps_cob = _annotate_steps(cob_steps, -1, terminal_failure=False) if cob_steps else []
            all_steps = steps_pre + steps_log + steps_cob
            return _pack_result(
                pedido, all_steps, current_idx=0, current_estado=estado,
                pipeline_label="Flujo de venta",
                phases=phases + [
                    {"id": "logistica", "label": "Logística", "steps": VENTA_LOGISTICA},
                ] + ([{"id": "cobranza", "label": "Cobranza Circa", "steps": VENTA_COBRANZA}] if monto_fin > 0 else []),
                include_cobranza=monto_fin > 0,
            )

        pipeline = list(VENTA_LOGISTICA)
        phases.append({"id": "logistica", "label": "Logística distribuidor", "steps": VENTA_LOGISTICA})
        include_cobranza = monto_fin > 0
        if include_cobranza:
            pipeline.extend(VENTA_COBRANZA)
            phases.append({"id": "cobranza", "label": "Cobranza Circa", "steps": VENTA_COBRANZA})
        current_idx = _resolve_venta_index(estado)
        if current_idx >= len(VENTA_LOGISTICA) and include_cobranza:
            cob_offset = len(VENTA_LOGISTICA)
            e = normalize_estado(estado)
            if e == "pago_reportado":
                current_idx = cob_offset
            elif e == "pagado":
                current_idx = cob_offset + 1
        elif current_idx >= 0 and current_idx < len(VENTA_LOGISTICA):
            pass
        pipeline_label = "Flujo de venta"

    terminal_failure = estado in TERMINAL_FAILURE
    terminal_success = estado in TERMINAL_SUCCESS
    if not is_preventa and estado == "entregado" and monto_fin <= 0:
        terminal_success = True

    if current_idx == -2:
        # Estado atípico: mostrar logística sin paso actual claro
        annotated = _annotate_steps(pipeline, -1, terminal_failure=terminal_failure)
    else:
        annotated = _annotate_steps(pipeline, current_idx, terminal_failure=terminal_failure)

    if terminal_success and current_idx >= 0:
        annotated = [{**s, "status": "done", "index": i} for i, s in enumerate(annotated)]

    return _pack_result(
        pedido,
        annotated,
        current_idx=current_idx,
        current_estado=estado,
        pipeline_label=pipeline_label,
        phases=phases,
        include_cobranza=not is_preventa and monto_fin > 0,
        terminal_failure=terminal_failure,
        terminal_success=terminal_success,
    )


def _pack_result(
    pedido: dict,
    steps: list[dict],
    *,
    current_idx: int,
    current_estado: str,
    pipeline_label: str,
    phases: list[dict],
    include_cobranza: bool = False,
    terminal_failure: bool = False,
    terminal_success: bool = False,
) -> dict:
    total = len(steps)
    if terminal_success:
        completed = total
        remaining = 0
        percent = 100
    elif terminal_failure:
        completed = sum(1 for s in steps if s.get("status") == "done")
        remaining = max(0, total - completed - 1)
        percent = int(round(100 * completed / total)) if total else 0
    elif current_idx < 0:
        completed = 0
        remaining = total
        percent = 0
    else:
        completed = current_idx
        remaining = max(0, total - current_idx - 1)
        percent = int(round(100 * completed / (total - 1))) if total > 1 else (100 if terminal_success else 0)

    current_step = None
    if 0 <= current_idx < total:
        current_step = steps[current_idx]
    elif terminal_success and steps:
        current_step = steps[-1]

    next_step = None
    if not terminal_failure and not terminal_success and current_idx >= 0:
        for s in steps:
            if s.get("status") == "pending":
                next_step = s
                break

    return {
        "pedido_id": pedido.get("id"),
        "numero": pedido.get("numero"),
        "tipo_operacion": pedido.get("tipo_operacion") or "venta",
        "estado_actual": current_estado,
        "estado_normalizado": normalize_estado(current_estado)
        if not (current_estado or "").startswith("preventa_")
        else current_estado,
        "pipeline_label": pipeline_label,
        "include_cobranza": include_cobranza,
        "monto_financiado": float(pedido.get("monto_financiado") or 0),
        "step_index": current_idx,
        "total_steps": total,
        "completed_steps": completed,
        "remaining_steps": remaining,
        "percent": min(100, max(0, percent)),
        "is_terminal": terminal_failure or terminal_success,
        "is_success": terminal_success,
        "is_failure": terminal_failure,
        "current_step": current_step,
        "next_step": next_step,
        "steps": steps,
        "phases": [
            {
                **ph,
                "steps": _annotate_steps(
                    ph["steps"],
                    _phase_current_index(ph["steps"], current_estado, current_idx, steps),
                    terminal_failure=terminal_failure,
                ),
            }
            for ph in phases
        ],
    }


def _phase_current_index(phase_steps: list[dict], estado: str, global_idx: int, all_steps: list[dict]) -> int:
    ids = [s["id"] for s in phase_steps]
    e = normalize_estado(estado) if not (estado or "").startswith("preventa_") else estado
    if e in ids:
        return ids.index(e)
    all_ids = [s["id"] for s in all_steps]
    if e in all_ids and ids:
        try:
            first_phase_pos = all_ids.index(ids[0])
        except ValueError:
            first_phase_pos = -1
        estado_pos = all_ids.index(e)
        if first_phase_pos >= 0 and estado_pos > first_phase_pos:
            return len(ids)
    if global_idx < 0:
        return -1
    return -1
