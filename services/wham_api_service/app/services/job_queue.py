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


def _schedule_requeue(job_id: str, delay_seconds: int) -> None:
    """Schedule a safe requeue that tolerates dedupe races with active workers."""

    def _attempt_enqueue() -> None:
        if _is_job_terminal(job_id):
            return

        with _queue_lock:
            if job_id in _enqueued_job_ids:
                retry_timer = threading.Timer(1, _attempt_enqueue)
                retry_timer.daemon = True
                retry_timer.start()
                return

        enqueue_job(job_id)

    timer = threading.Timer(delay_seconds, _attempt_enqueue)
    timer.daemon = True
    timer.start()


def _is_job_terminal(job_id: str) -> bool:
    row = _get_job_record_for_worker(job_id)
    if row is None:
        return True
    return row["status"] in {ApiJobStatus.succeeded.value, ApiJobStatus.failed.value}


def _get_job_record_for_worker(job_id: str) -> dict[str, Any] | None:
    from app.db.models import JobRecord
    from app.db.session import session_scope
    from .job_service import _database_ready

    database_ready = _database_ready()

    if not database_ready:
        return None

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

    if _is_job_terminal(job_id):
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
            if _is_job_terminal(job_id):
                return
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
            if _is_job_terminal(job_id):
                return
            update_job_completion(
                job_id=job_id,
                status_value=ApiJobStatus.succeeded,
                exit_code=inspection.exit_code,
            )
        else:
            if _is_job_terminal(job_id):
                return
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
    if not settings.is_job_launch_time_allowed_utc():
        wait_seconds = settings.seconds_until_next_job_launch_window_utc()
        retry_delay_seconds = max(1, min(wait_seconds, 300))
        log_event(
            _logger,
            "job_launch_deferred_outside_utc_window",
            job_id=job_id,
            backend=backend,
            configured_window=f"{settings.job_launch_utc_start}-{settings.job_launch_utc_end}",
            seconds_until_window=wait_seconds,
            retry_delay_seconds=retry_delay_seconds,
        )
        _schedule_requeue(job_id, retry_delay_seconds)
        return

    if _is_job_terminal(job_id):
        return
    launch_result = strategy.launch(job_id, runtime_params)
    if not launch_result.success:
        if _is_job_terminal(job_id):
            return
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
    if _is_job_terminal(job_id):
        return
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
                try:
                    from .job_requeue import notify_startup_requeue_slot_available

                    notify_startup_requeue_slot_available()
                except Exception:
                    pass

    for idx in range(count):
        thread = threading.Thread(target=_worker, name=f"wham-job-worker-{idx}", daemon=True)
        thread.start()
        _worker_threads.append(thread)
