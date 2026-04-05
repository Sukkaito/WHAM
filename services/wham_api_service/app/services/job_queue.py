from __future__ import annotations

import queue
import threading
from typing import Any

from app.core.settings import settings
from app.models.schemas import JobStatus as ApiJobStatus
from app.services.docker_executor import execute_docker_blocking, execute_docker_detached, inspect_container, wait_for_container
from app.services.job_service import mark_job_running, update_job_completion


_job_queue: queue.Queue[str] = queue.Queue()
_enqueued_job_ids: set[str] = set()
_queue_lock = threading.Lock()
_worker_threads: list[threading.Thread] = []
_worker_started = False


def _get_job_record_for_worker(job_id: str) -> dict[str, Any] | None:
    from app.db.models import JobRecord
    from app.db.session import session_scope
    from app.services.job_service import _database_ready
    from app.services.video_service import read_idx

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
        "runtime_params": runtime_params,
    }


def _complete_job_from_container_state(job_id: str, container_name: str) -> None:
    from app.services.job_service import _cleanup_container

    wait_result = wait_for_container(container_name)
    if not wait_result.success:
        update_job_completion(
            job_id=job_id,
            status_value=ApiJobStatus.failed,
            error_summary=(wait_result.stderr or wait_result.stdout or "Docker wait failed").strip(),
        )
        _cleanup_container(container_name)
        return

    try:
        exit_code = int(wait_result.stdout.strip().splitlines()[-1])
    except Exception:
        exit_code = None

    if exit_code == 0:
        update_job_completion(
            job_id=job_id,
            status_value=ApiJobStatus.succeeded,
            exit_code=exit_code,
        )
        _cleanup_container(container_name)
        return

    logs_result = execute_docker_blocking(["docker", "logs", "--tail", "200", container_name], cwd=settings.repo_dir)
    error_summary = (logs_result.stderr or logs_result.stdout or "Docker container failed").strip()
    update_job_completion(
        job_id=job_id,
        status_value=ApiJobStatus.failed,
        exit_code=exit_code,
        error_summary=error_summary,
    )
    _cleanup_container(container_name)


def _run_job_worker_cycle(job_id: str) -> None:
    from app.services.job_service import _cleanup_container

    row = _get_job_record_for_worker(job_id)
    if row is None:
        return

    status_value = row["status"]
    runtime_params = row["runtime_params"]
    container_name = row.get("container_name")

    if status_value in {ApiJobStatus.succeeded.value, ApiJobStatus.failed.value}:
        return

    if status_value == ApiJobStatus.running.value:
        if not container_name:
            update_job_completion(
                job_id=job_id,
                status_value=ApiJobStatus.failed,
                error_summary="Running job has no container name",
            )
            return

        inspect_result = inspect_container(container_name)
        if not inspect_result.success:
            update_job_completion(
                job_id=job_id,
                status_value=ApiJobStatus.failed,
                error_summary=(inspect_result.stderr or inspect_result.stdout or "Container not found").strip(),
            )
            _cleanup_container(container_name)
            return

        payload = inspect_result.stdout.strip().split()
        if len(payload) >= 2 and payload[0].lower() not in {"running", "created", "paused"}:
            try:
                exit_code = int(payload[1])
            except Exception:
                exit_code = None

            if exit_code == 0:
                update_job_completion(
                    job_id=job_id,
                    status_value=ApiJobStatus.succeeded,
                    exit_code=exit_code,
                )
            else:
                update_job_completion(
                    job_id=job_id,
                    status_value=ApiJobStatus.failed,
                    exit_code=exit_code,
                    error_summary=f"Docker container {container_name} exited with status {payload[0].lower()}",
                )
            _cleanup_container(container_name)
            return

        _complete_job_from_container_state(job_id, container_name)
        return

    docker_cmd = runtime_params.get("docker_cmd") if isinstance(runtime_params, dict) else None
    if not isinstance(docker_cmd, list) or not docker_cmd:
        update_job_completion(
            job_id=job_id,
            status_value=ApiJobStatus.failed,
            error_summary="Missing docker command for queued job",
        )
        return

    mark_job_running(job_id)
    launch_result = execute_docker_detached(docker_cmd, cwd=settings.repo_dir)
    if not launch_result.success:
        update_job_completion(
            job_id=job_id,
            status_value=ApiJobStatus.failed,
            error_summary=(launch_result.stderr or launch_result.stdout or "Docker launch failed").strip(),
            exit_code=launch_result.returncode,
        )
        return

    resolved = _get_job_record_for_worker(job_id)
    if resolved is None:
        return
    container_name = resolved.get("container_name") or runtime_params.get("container_name")
    if not container_name:
        update_job_completion(
            job_id=job_id,
            status_value=ApiJobStatus.failed,
            error_summary="Queued job launched without container name",
        )
        return

    _complete_job_from_container_state(job_id, container_name)


def enqueue_job(job_id: str) -> None:
    with _queue_lock:
        if job_id in _enqueued_job_ids:
            return
        _enqueued_job_ids.add(job_id)
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
