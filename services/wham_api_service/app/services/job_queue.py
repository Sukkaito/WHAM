from __future__ import annotations

import queue
import threading
from typing import Any

from app.core.logging import get_logger, log_event
from app.core.settings import settings
from app.models.schemas import JobStatus as ApiJobStatus
from .execution_strategy import get_execution_strategy
from .job_service import mark_job_running, update_job_completion, update_job_runtime_metadata


_job_queue: queue.Queue[str] = queue.Queue()
_enqueued_job_ids: set[str] = set()
_queue_lock = threading.Lock()
_worker_threads: list[threading.Thread] = []
_worker_started = False
_logger = get_logger(__name__)


def _get_job_record_for_worker(job_id: str) -> dict[str, Any] | None:
    from app.db.models import JobRecord
    from app.db.session import session_scope
    from .job_service import _database_ready
    from .video_service import read_idx

    database_ready = _database_ready()

    if database_ready:
        with session_scope() as session:
            job = session.get(JobRecord, job_id)
            if job is None:
                return None

            runtime_params = job.runtime_params or {}
            if not isinstance(runtime_params, dict):
                runtime_params = {}

            return {
                "job_id": job.job_id,
                "status": job.status.value,
                "container_name": job.container_name or runtime_params.get("container_name"),
                "pod_id": getattr(job, "pod_id", None) or runtime_params.get("pod_id"),
                "pod_name": getattr(job, "pod_name", None) or runtime_params.get("pod_name"),
                "execution_backend": getattr(job, "execution_backend", None) or runtime_params.get("execution_backend"),
                "runtime_params": runtime_params,
            }

    idx = read_idx()
    row = idx.get("jobs", {}).get(job_id)
    if row is None:
        return None
    runtime_params = row.get("runtime_params") or {}
    if not isinstance(runtime_params, dict):
        runtime_params = {}
    return {
        "job_id": row.get("job_id", job_id),
        "status": row.get("status", ApiJobStatus.queued.value),
        "container_name": row.get("container_name") or runtime_params.get("container_name"),
        "pod_id": row.get("pod_id") or runtime_params.get("pod_id"),
        "pod_name": row.get("pod_name") or runtime_params.get("pod_name"),
        "execution_backend": row.get("execution_backend") or runtime_params.get("execution_backend"),
        "runtime_params": runtime_params,
    }


def _run_job_worker_cycle(job_id: str) -> None:
    row = _get_job_record_for_worker(job_id)
    if row is None:
        return

    status_value = row["status"]
    runtime_params = row["runtime_params"]
    backend = (row.get("execution_backend") or runtime_params.get("execution_backend") or settings.execution_backend).strip().lower()
    strategy = get_execution_strategy(backend)
    log_event(
        _logger,
        "job_worker_cycle_start",
        job_id=job_id,
        backend=backend,
        status=status_value,
    )

    if status_value in {ApiJobStatus.succeeded.value, ApiJobStatus.failed.value}:
        return

    if status_value == ApiJobStatus.running.value:
        identifier = row.get("pod_id") if backend == "runpod" else row.get("container_name")
        if not identifier:
            log_event(
                _logger,
                "job_running_missing_identifier",
                job_id=job_id,
                backend=backend,
            )
            update_job_completion(
                job_id=job_id,
                status_value=ApiJobStatus.failed,
                error_summary=f"Running job has no {'pod_id' if backend == 'runpod' else 'container name'}",
            )
            return

        log_event(
            _logger,
            "job_inspect_start",
            job_id=job_id,
            backend=backend,
            identifier=identifier,
        )
        inspection = strategy.inspect(identifier, runtime_params)
        log_event(
            _logger,
            "job_inspect_result",
            job_id=job_id,
            backend=backend,
            identifier=identifier,
            state=inspection.state,
            exit_code=inspection.exit_code,
        )
        if inspection.state == "running":
            completion = strategy.wait_for_completion(job_id, identifier, runtime_params)
            log_event(
                _logger,
                "job_wait_completion",
                job_id=job_id,
                backend=backend,
                identifier=identifier,
                status=completion.status_value.value,
                exit_code=completion.exit_code,
            )
            update_job_completion(
                job_id=job_id,
                status_value=completion.status_value,
                exit_code=completion.exit_code,
                error_summary=completion.error_summary,
            )
        elif inspection.state == "succeeded":
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
        return

    log_event(
        _logger,
        "job_launch_start",
        job_id=job_id,
        backend=backend,
    )
    launch_result = strategy.launch(job_id, runtime_params)
    if not launch_result.success:
        failure_message = (launch_result.stderr or launch_result.stdout or f"{strategy.backend_name} launch failed").strip()
        log_event(
            _logger,
            "job_launch_failed",
            job_id=job_id,
            backend=backend,
            returncode=launch_result.returncode,
        )
        update_job_completion(
            job_id=job_id,
            status_value=ApiJobStatus.failed,
            error_summary=failure_message,
            exit_code=launch_result.returncode,
        )
        return

    if launch_result.metadata_updates:
        update_job_runtime_metadata(job_id, launch_result.metadata_updates)

    log_event(
        _logger,
        "job_launch_succeeded",
        job_id=job_id,
        backend=backend,
        identifier=launch_result.identifier,
    )
    mark_job_running(job_id)
    identifier = launch_result.identifier or row.get("pod_id") or row.get("container_name")
    if not identifier:
        log_event(
            _logger,
            "job_launch_missing_identifier",
            job_id=job_id,
            backend=backend,
        )
        update_job_completion(
            job_id=job_id,
            status_value=ApiJobStatus.failed,
            error_summary=f"{strategy.backend_name} launch completed without identifier",
        )
        return

    completion = strategy.wait_for_completion(job_id, identifier, runtime_params)
    log_event(
        _logger,
        "job_completed",
        job_id=job_id,
        backend=backend,
        identifier=identifier,
        status=completion.status_value.value,
        exit_code=completion.exit_code,
    )
    update_job_completion(
        job_id=job_id,
        status_value=completion.status_value,
        exit_code=completion.exit_code,
        error_summary=completion.error_summary,
    )
    strategy.cleanup(identifier)


def enqueue_job(job_id: str) -> None:
    with _queue_lock:
        if job_id in _enqueued_job_ids:
            return
        _enqueued_job_ids.add(job_id)
    log_event(_logger, "job_enqueued", job_id=job_id)
    _job_queue.put(job_id)


def start_job_worker(worker_count: int = 1) -> None:
    global _worker_started
    with _queue_lock:
        if _worker_started:
            return
        _worker_started = True

    count = max(worker_count, 1)

    def _worker() -> None:
        while True:
            job_id = _job_queue.get()
            try:
                _run_job_worker_cycle(job_id)
            except Exception as exc:  # pragma: no cover - defensive worker handling
                try:
                    update_job_completion(
                        job_id=job_id,
                        status_value=ApiJobStatus.failed,
                        error_summary=str(exc),
                    )
                except Exception:
                    pass
            finally:
                with _queue_lock:
                    _enqueued_job_ids.discard(job_id)
                _job_queue.task_done()

    for idx in range(count):
        thread = threading.Thread(target=_worker, name=f"wham-job-worker-{idx}", daemon=True)
        thread.start()
        _worker_threads.append(thread)
