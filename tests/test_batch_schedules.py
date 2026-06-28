import os
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

os.environ.setdefault("SUPABASE_URL", "http://localhost")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "test-key")

from app.services.batch_jobs.schedules import (
    compute_next_run,
    describe_schedule,
    validate_schedule_payload,
)


def test_validate_schedule_weekly_requires_weekdays():
    try:
        validate_schedule_payload({
            "job_id": "score_bodegas_diario",
            "frecuencia": "weekly",
            "weekdays": [],
        })
        assert False
    except ValueError as e:
        assert "día" in str(e).lower()


def test_compute_next_run_daily():
    sched = {
        "frecuencia": "daily",
        "hour": 6,
        "minute": 0,
        "timezone": "America/Lima",
    }
    after = datetime(2026, 6, 3, 10, 0, tzinfo=ZoneInfo("America/Lima"))
    nxt = compute_next_run(sched, after=after)
    local = nxt.astimezone(ZoneInfo("America/Lima"))
    assert local.hour == 6
    assert local.minute == 0
    assert local.day == 4


def test_describe_schedule_hourly():
    text = describe_schedule({"frecuencia": "hourly", "minute": 15})
    assert "hora" in text.lower()
    assert ":15" in text
