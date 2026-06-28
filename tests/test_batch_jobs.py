import asyncio
import os

os.environ.setdefault("SUPABASE_URL", "http://localhost")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "test-key")

from unittest.mock import MagicMock, patch

from app.services.batch_jobs.registry import JOBS_BY_ID
from app.services.batch_jobs.runner import list_jobs_with_status, run_batch_job


def test_registry_has_score_job():
    assert "score_bodegas_diario" in JOBS_BY_ID
    job = JOBS_BY_ID["score_bodegas_diario"]
    assert job.permite_dry_run is True


def test_list_jobs_with_status_empty_runs():
    with patch("app.services.batch_jobs.runner.db") as mock_db:
        mock_db.sb.table.return_value.select.return_value.order.return_value.limit.return_value.execute.return_value = MagicMock(data=[])
        jobs = list_jobs_with_status()
    assert len(jobs) >= 1
    assert jobs[0]["id"] == "score_bodegas_diario"


def test_run_score_job_dry_run():
    with patch("app.services.batch_jobs.score_diario.run_bodega_scoring_batch") as mock_score:
        mock_score.return_value = {"total": 2, "bodegas": [], "actualizadas": 0, "resumen_grados": {}}
        with patch("app.services.batch_jobs.runner._create_run", return_value="run-1"):
            with patch("app.services.batch_jobs.runner._finish_run"):
                result = asyncio.run(run_batch_job(
                    "score_bodegas_diario",
                    dry_run=True,
                    user_email="test@circa.pe",
                ))
    assert result["dry_run"] is True
    assert result["processed"] == 2
    mock_score.assert_called_once_with(test="real", persist=False)
