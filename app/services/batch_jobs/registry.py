"""Catálogo de jobs batch disponibles en backoffice."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Awaitable

BatchHandler = Callable[..., Awaitable[dict[str, Any]]]


@dataclass(frozen=True)
class BatchJobDef:
    id: str
    nombre: str
    descripcion: str
    frecuencia_sugerida: str
    afecta_whatsapp: bool
    permite_dry_run: bool
    soporta_test_filter: bool
    handler: BatchHandler


def _placeholder_not_implemented(job_id: str) -> BatchHandler:
    async def _run(**_kwargs):
        return {
            "processed": 0,
            "ok": 0,
            "failed": 0,
            "errors": [],
            "note": f"Job {job_id} registrado; implementación pendiente.",
        }

    return _run


def _load_handlers() -> dict[str, BatchHandler]:
    from app.services.batch_jobs import score_diario
    from app.services.batch_jobs import cobranza_jobs

    return {
        "score_bodegas_diario": score_diario.run,
        "recordatorios_cobranza": cobranza_jobs.run_recordatorios,
        "marcar_vencidos": cobranza_jobs.run_marcar_vencidos,
        "onboarding_abandonado": _placeholder_not_implemented("onboarding_abandonado"),
        "reactivacion_inactivos": _placeholder_not_implemented("reactivacion_inactivos"),
    }


_HANDLERS = _load_handlers()

JOB_DEFINITIONS: list[BatchJobDef] = [
    BatchJobDef(
        id="score_bodegas_diario",
        nombre="Score bodegas (diario)",
        descripcion="Calcula score operativo, guarda en bodegas.scoring y snapshot en bodega_scoring_diario.",
        frecuencia_sugerida="Diario 06:00",
        afecta_whatsapp=False,
        permite_dry_run=True,
        soporta_test_filter=True,
        handler=_HANDLERS["score_bodegas_diario"],
    ),
    BatchJobDef(
        id="recordatorios_cobranza",
        nombre="Recordatorios de cobranza",
        descripcion="Envía recordatorios de pago WhatsApp pendientes (tabla recordatorios).",
        frecuencia_sugerida="Diario / cada hora",
        afecta_whatsapp=True,
        permite_dry_run=True,
        soporta_test_filter=False,
        handler=_HANDLERS["recordatorios_cobranza"],
    ),
    BatchJobDef(
        id="marcar_vencidos",
        nombre="Marcar créditos vencidos",
        descripcion="Pasa financiamientos activos con fecha vencida a estado vencido.",
        frecuencia_sugerida="Diario 07:00",
        afecta_whatsapp=False,
        permite_dry_run=True,
        soporta_test_filter=False,
        handler=_HANDLERS["marcar_vencidos"],
    ),
    BatchJobDef(
        id="onboarding_abandonado",
        nombre="Nudge onboarding abandonado",
        descripcion="Bodegas inactivas o sesión atascada en fase de onboarding (> N días).",
        frecuencia_sugerida="Diario",
        afecta_whatsapp=True,
        permite_dry_run=True,
        soporta_test_filter=True,
        handler=_HANDLERS["onboarding_abandonado"],
    ),
    BatchJobDef(
        id="reactivacion_inactivos",
        nombre="Reactivación comercial",
        descripcion="Bodegas activas sin compra reciente en Circa.",
        frecuencia_sugerida="Semanal",
        afecta_whatsapp=True,
        permite_dry_run=True,
        soporta_test_filter=True,
        handler=_HANDLERS["reactivacion_inactivos"],
    ),
]

JOBS_BY_ID: dict[str, BatchJobDef] = {j.id: j for j in JOB_DEFINITIONS}
