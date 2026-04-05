from __future__ import annotations

from app.db.models import JobRecord, JobStatus as DbJobStatus
from app.db.session import session_scope
from app.models.schemas import JobStatus as ApiJobStatus
from app.services.job_queue import enqueue_job
from app.services.job_service import _database_ready
from app.services.video_service import read_idx


def _next_unfinished_job_ids() -> list[str]:
    database_ready = _database_ready()
    if database_ready:
        with session_scope() as session:
            rows = (
                session.query(JobRecord.job_id)
                .filter(JobRecord.status.in_([DbJobStatus.queued, DbJobStatus.running]))
                .all()
            )
            return [row[0] for row in rows]

    idx = read_idx()
    out: list[str] = []
    for job_id, row in idx.get("jobs", {}).items():
        status_value = (row or {}).get("status")
        if status_value in {ApiJobStatus.queued.value, ApiJobStatus.running.value}:
            out.append(job_id)
    return out


def requeue_unfinished_jobs() -> None:
    for job_id in _next_unfinished_job_ids():
        enqueue_job(job_id)
