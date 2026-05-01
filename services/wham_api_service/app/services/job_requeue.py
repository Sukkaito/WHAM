from __future__ import annotations

from collections import deque
import threading
from typing import Any

from app.core.logging import get_logger, log_event
from app.core.settings import settings
from app.db.models import JobRecord, JobStatus as DbJobStatus
from app.db.session import session_scope
from app.models.schemas import JobStatus as ApiJobStatus
from app.services.execution_strategy import get_execution_strategy
from app.services.job_queue import enqueue_job
from app.services.job_service import _database_ready, update_job_completion
from app.services.video_service import read_idx


_logger = get_logger(__name__)
_startup_requeue_backlog: deque[dict[str, Any]] = deque()
_startup_requeue_lock = threading.Lock()


def _next_unfinished_jobs() -> list[dict[str, Any]]:
    database_ready = _database_ready()
    if database_ready:
        with session_scope() as session:
            rows = (
                session.query(JobRecord)
                .filter(JobRecord.status.in_([DbJobStatus.queued, DbJobStatus.running]))
                .all()
            )
            out: list[dict[str, Any]] = []
            for job in rows:
                runtime_params = job.runtime_params or {}
                if not isinstance(runtime_params, dict):
                    runtime_params = {}
                out.append(
                    {
                        "job_id": job.job_id,
                        "status": job.status.value,
                        "runtime_params": runtime_params,
                        "execution_backend": job.execution_backend or runtime_params.get("execution_backend"),
                        "identifier": job.pod_id
                        or runtime_params.get("pod_id")
                        or job.container_name
                        or runtime_params.get("container_name"),
                    }
                )
            return out

    idx = read_idx()
    out: list[dict[str, Any]] = []
    for job_id, row in idx.get("jobs", {}).items():
        row = row or {}
        status_value = (row or {}).get("status")
        if status_value in {ApiJobStatus.queued.value, ApiJobStatus.running.value}:
            runtime_params = row.get("runtime_params") or {}
            if not isinstance(runtime_params, dict):
                runtime_params = {}
            out.append(
                {
                    "job_id": job_id,
                    "status": status_value,
                    "runtime_params": runtime_params,
                    "execution_backend": row.get("execution_backend") or runtime_params.get("execution_backend"),
                    "identifier": row.get("pod_id")
                    or runtime_params.get("pod_id")
                    or row.get("container_name")
                    or runtime_params.get("container_name"),
                }
            )
    return out


def _reconcile_running_job(job: dict[str, Any]) -> bool:
    job_id = job["job_id"]
    runtime_params = job.get("runtime_params") or {}
    if not isinstance(runtime_params, dict):
        runtime_params = {}

    backend = (job.get("execution_backend") or runtime_params.get("execution_backend") or "docker").strip().lower()
    identifier = job.get("identifier")
    log_event(
        _logger,
        "startup_reconcile_running_start",
        job_id=job_id,
        backend=backend,
        identifier=identifier,
    )
    if not identifier:
        log_event(
            _logger,
            "startup_reconcile_missing_identifier",
            job_id=job_id,
            backend=backend,
        )
        update_job_completion(
            job_id=job_id,
            status_value=ApiJobStatus.failed,
            error_summary="Running job has no execution identifier during startup reconciliation",
        )
        return False

    strategy = get_execution_strategy(backend)
    inspection = strategy.inspect(identifier, runtime_params)
    log_event(
        _logger,
        "startup_reconcile_inspect_result",
        job_id=job_id,
        backend=backend,
        identifier=identifier,
        state=inspection.state,
        exit_code=inspection.exit_code,
    )
    if inspection.state == "running":
        return True

    if inspection.state == "succeeded":
        update_job_completion(
            job_id=job_id,
            status_value=ApiJobStatus.succeeded,
            exit_code=inspection.exit_code,
        )
    else:
        update_job_completion(
            job_id=job_id,
            status_value=ApiJobStatus.failed,
            exit_code=inspection.exit_code,
            error_summary=inspection.error_summary,
        )
    strategy.cleanup(identifier)
    log_event(
        _logger,
        "startup_reconcile_finalize",
        job_id=job_id,
        backend=backend,
        identifier=identifier,
        final_status="succeeded" if inspection.state == "succeeded" else "failed",
    )
    return False


def _enqueue_startup_job(job: dict[str, Any]) -> bool:
    job_id = job["job_id"]
    status_value = job.get("status")

    if status_value == ApiJobStatus.running.value:
        if _reconcile_running_job(job):
            enqueue_job(job_id)
            log_event(_logger, "startup_requeue_running_job", job_id=job_id)
            return True
        return False

    enqueue_job(job_id)
    log_event(_logger, "startup_requeue_queued_job", job_id=job_id)
    return True


def _drain_startup_requeue_backlog(target_count: int) -> int:
    requeued = 0

    while requeued < target_count:
        with _startup_requeue_lock:
            if not _startup_requeue_backlog:
                break
            job = _startup_requeue_backlog.popleft()

        if _enqueue_startup_job(job):
            requeued += 1

    return requeued


def notify_startup_requeue_slot_available() -> None:
    _drain_startup_requeue_backlog(1)


def requeue_unfinished_jobs() -> None:
    jobs = _next_unfinished_jobs()
    worker_count = max(settings.job_worker_count, 1)
    
    log_event(
        _logger,
        "startup_requeue_scan",
        unfinished_count=len(jobs),
        requeue_enabled=settings.requeue_jobs_on_startup,
        worker_count=worker_count,
    )
    
    if not settings.requeue_jobs_on_startup:
        # Cancel all unfinished jobs if requeue is disabled
        for job in jobs:
            job_id = job["job_id"]
            status_value = job.get("status")
            update_job_completion(
                job_id=job_id,
                status_value=ApiJobStatus.failed,
                error_summary="Job cancelled due to requeue being disabled on startup",
            )
            log_event(_logger, "startup_cancel_unfinished_job", job_id=job_id, status=status_value)
        return

    # Requeue only as many jobs as there are workers, then refill one-for-one as workers free up.
    running_jobs = [job for job in jobs if job.get("status") == ApiJobStatus.running.value]
    queued_jobs = [job for job in jobs if job.get("status") == ApiJobStatus.queued.value]

    with _startup_requeue_lock:
        _startup_requeue_backlog.clear()
        _startup_requeue_backlog.extend(running_jobs)
        _startup_requeue_backlog.extend(queued_jobs)

    initial_requeued = _drain_startup_requeue_backlog(worker_count)
    log_event(
        _logger,
        "startup_requeue_initial_batch",
        requeued_count=initial_requeued,
        backlog_remaining=len(_startup_requeue_backlog),
        worker_count=worker_count,
    )
