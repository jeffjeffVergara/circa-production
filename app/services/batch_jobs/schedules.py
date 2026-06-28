"""Programación de jobs batch (horaria, diaria, semanal)."""

from __future__ import annotations

import logging
from datetime import datetime, time, timedelta, timezone
from typing import Any, Optional
from zoneinfo import ZoneInfo

from app.services import db
from app.services.batch_jobs.registry import JOBS_BY_ID

logger = logging.getLogger("circa.batch_schedules")

DEFAULT_TZ = "America/Lima"
FREQ_HOURLY = "hourly"
FREQ_EVERY_N = "every_n_hours"
FREQ_DAILY = "daily"
FREQ_WEEKLY = "weekly"

FREQ_LABELS = {
    FREQ_HOURLY: "Cada hora",
    FREQ_EVERY_N: "Cada N horas",
    FREQ_DAILY: "Diario",
    FREQ_WEEKLY: "Semanal",
}


def _tz(name: Optional[str]) -> ZoneInfo:
    try:
        return ZoneInfo(name or DEFAULT_TZ)
    except Exception:
        return ZoneInfo(DEFAULT_TZ)


def _parse_ts(val: Any) -> Optional[datetime]:
    if not val:
        return None
    if isinstance(val, datetime):
        dt = val
    else:
        dt = datetime.fromisoformat(str(val).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def validate_schedule_payload(data: dict[str, Any]) -> dict[str, Any]:
    job_id = (data.get("job_id") or "").strip()
    if job_id not in JOBS_BY_ID:
        raise ValueError(f"Job desconocido: {job_id}")

    freq = data.get("frecuencia") or FREQ_DAILY
    if freq not in FREQ_LABELS:
        raise ValueError("Frecuencia inválida")

    hour = int(data.get("hour") if data.get("hour") is not None else 6)
    minute = int(data.get("minute") if data.get("minute") is not None else 0)
    if not 0 <= hour <= 23:
        raise ValueError("Hora inválida (0–23)")
    if not 0 <= minute <= 59:
        raise ValueError("Minuto inválido (0–59)")

    interval_hours = data.get("interval_hours")
    if freq == FREQ_EVERY_N:
        interval_hours = max(1, min(24, int(interval_hours or 1)))
    else:
        interval_hours = None

    weekdays: list[int] = []
    if freq == FREQ_WEEKLY:
        raw = data.get("weekdays")
        if raw is None:
            raw = [0]
        weekdays = sorted({int(d) for d in raw if 0 <= int(d) <= 6})
        if not weekdays:
            raise ValueError("Selecciona al menos un día de la semana")

    test_filter = data.get("test_filter") or "real"
    if test_filter not in ("real", "test"):
        raise ValueError("test_filter debe ser real o test")

    return {
        "job_id": job_id,
        "label": (data.get("label") or "").strip() or None,
        "activo": bool(data.get("activo", True)),
        "frecuencia": freq,
        "hour": hour,
        "minute": minute,
        "interval_hours": interval_hours,
        "weekdays": weekdays,
        "test_filter": test_filter,
        "timezone": data.get("timezone") or DEFAULT_TZ,
    }


def compute_next_run(schedule: dict[str, Any], *, after: Optional[datetime] = None) -> datetime:
    """Calcula la próxima ejecución en UTC (almacenable en timestamptz)."""
    tz = _tz(schedule.get("timezone"))
    now_local = (after or datetime.now(timezone.utc)).astimezone(tz)
    minute = int(schedule.get("minute") or 0)
    hour = int(schedule.get("hour") or 6)
    freq = schedule.get("frecuencia") or FREQ_DAILY

    if freq == FREQ_HOURLY:
        candidate = now_local.replace(minute=minute, second=0, microsecond=0)
        if candidate <= now_local:
            candidate += timedelta(hours=1)
        return candidate.astimezone(timezone.utc)

    if freq == FREQ_EVERY_N:
        n = max(1, min(24, int(schedule.get("interval_hours") or 1)))
        last = _parse_ts(schedule.get("last_run_at"))
        if last:
            candidate = last.astimezone(tz) + timedelta(hours=n)
            while candidate <= now_local:
                candidate += timedelta(hours=n)
            return candidate.astimezone(timezone.utc)
        anchor = now_local.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if anchor > now_local:
            return anchor.astimezone(timezone.utc)
        elapsed_h = (now_local - anchor).total_seconds() / 3600
        k = int(elapsed_h // n) + 1
        candidate = anchor + timedelta(hours=k * n)
        return candidate.astimezone(timezone.utc)

    if freq == FREQ_DAILY:
        candidate = now_local.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if candidate <= now_local:
            candidate += timedelta(days=1)
        return candidate.astimezone(timezone.utc)

    weekdays = schedule.get("weekdays") or [0]
    weekdays = sorted({int(d) for d in weekdays if 0 <= int(d) <= 6})
    if not weekdays:
        weekdays = [0]
    for offset in range(8):
        day = now_local.date() + timedelta(days=offset)
        if day.weekday() not in weekdays:
            continue
        candidate = datetime.combine(day, time(hour, minute), tzinfo=tz)
        if candidate > now_local:
            return candidate.astimezone(timezone.utc)
    fallback = now_local + timedelta(days=7)
    return fallback.astimezone(timezone.utc)


def describe_schedule(schedule: dict[str, Any]) -> str:
    freq = schedule.get("frecuencia")
    h = int(schedule.get("hour") or 0)
    m = int(schedule.get("minute") or 0)
    hm = f"{h:02d}:{m:02d}"
    if freq == FREQ_HOURLY:
        return f"Cada hora al minuto :{m:02d}"
    if freq == FREQ_EVERY_N:
        n = int(schedule.get("interval_hours") or 1)
        return f"Cada {n}h desde {hm}"
    if freq == FREQ_DAILY:
        return f"Diario a las {hm}"
    days = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"]
    wd = schedule.get("weekdays") or []
    names = ", ".join(days[int(d)] for d in sorted(wd) if 0 <= int(d) <= 6)
    return f"Semanal {names or '—'} a las {hm}"


def list_schedules() -> list[dict[str, Any]]:
    try:
        rows = (
            db.sb.table("batch_schedules")
            .select("*")
            .order("created_at", desc=True)
            .execute()
            .data
            or []
        )
    except Exception as exc:
        logger.warning("batch_schedules no disponible: %s", exc)
        return []

    out = []
    for row in rows:
        job = JOBS_BY_ID.get(row.get("job_id") or "")
        item = dict(row)
        item["job_nombre"] = job.nombre if job else row.get("job_id")
        item["frecuencia_label"] = FREQ_LABELS.get(row.get("frecuencia"), row.get("frecuencia"))
        item["descripcion_cron"] = describe_schedule(row)
        out.append(item)
    return out


def create_schedule(data: dict[str, Any], *, user_email: str = "") -> dict[str, Any]:
    payload = validate_schedule_payload(data)
    payload["created_by"] = user_email
    payload["updated_at"] = datetime.now(timezone.utc).isoformat()
    payload["next_run_at"] = compute_next_run(payload).isoformat()
    ins = db.sb.table("batch_schedules").insert(payload).execute()
    row = ins.data[0]
    row["descripcion_cron"] = describe_schedule(row)
    return row


def update_schedule(schedule_id: str, data: dict[str, Any]) -> dict[str, Any]:
    existing = (
        db.sb.table("batch_schedules")
        .select("*")
        .eq("id", schedule_id)
        .limit(1)
        .execute()
        .data
    )
    if not existing:
        raise ValueError("Programación no encontrada")

    merged = {**existing[0], **data}
    payload = validate_schedule_payload(merged)
    if "activo" in data:
        payload["activo"] = bool(data["activo"])
    payload["updated_at"] = datetime.now(timezone.utc).isoformat()
    payload["next_run_at"] = compute_next_run(payload).isoformat()

    upd = (
        db.sb.table("batch_schedules")
        .update(payload)
        .eq("id", schedule_id)
        .execute()
    )
    row = upd.data[0]
    row["descripcion_cron"] = describe_schedule(row)
    return row


def delete_schedule(schedule_id: str) -> None:
    db.sb.table("batch_schedules").delete().eq("id", schedule_id).execute()


async def run_due_schedules(*, limit: int = 10) -> dict[str, Any]:
    """Ejecuta programaciones vencidas. Llamar desde cron (tick)."""
    from app.services.batch_jobs.runner import run_batch_job

    now = datetime.now(timezone.utc).isoformat()
    try:
        due = (
            db.sb.table("batch_schedules")
            .select("*")
            .eq("activo", True)
            .lte("next_run_at", now)
            .order("next_run_at")
            .limit(limit)
            .execute()
            .data
            or []
        )
    except Exception as exc:
        logger.warning("No se pudo leer batch_schedules: %s", exc)
        return {"due": 0, "executed": [], "errors": [str(exc)]}

    executed = []
    errors = []
    for sched in due:
        sid = sched["id"]
        job_id = sched["job_id"]
        try:
            result = await run_batch_job(
                job_id,
                test=sched.get("test_filter") or "real",
                dry_run=False,
                trigger="scheduled",
                user_email=sched.get("created_by") or "scheduler@circa",
                comment=f"Programación automática {describe_schedule(sched)}",
            )
            status = result.get("status") or "ok"
            next_at = compute_next_run(sched).isoformat()
            db.sb.table("batch_schedules").update({
                "last_run_at": datetime.now(timezone.utc).isoformat(),
                "last_run_status": status,
                "next_run_at": next_at,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }).eq("id", sid).execute()
            executed.append({
                "schedule_id": sid,
                "job_id": job_id,
                "status": status,
                "processed": result.get("processed"),
            })
        except Exception as exc:
            logger.exception("Error ejecutando schedule %s", sid)
            errors.append({"schedule_id": sid, "job_id": job_id, "error": str(exc)})
            try:
                db.sb.table("batch_schedules").update({
                    "last_run_at": datetime.now(timezone.utc).isoformat(),
                    "last_run_status": "failed",
                    "next_run_at": compute_next_run(sched).isoformat(),
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }).eq("id", sid).execute()
            except Exception:
                pass

    return {"due": len(due), "executed": executed, "errors": errors}
