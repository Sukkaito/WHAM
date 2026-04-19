from __future__ import annotations

import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import HTTPException, status

from app.core.logging import get_logger, log_event
from app.core.settings import settings
from app.db.models import Base, JobRecord, JobStatus as DbJobStatus, TransformType as DbTransformType
from app.db.session import get_engine, session_scope
from app.models.schemas import AuthPayload, JobStatus as ApiJobStatus
from app.models.schemas import JobStatusResponse, TransformType
from .execution_strategy import get_execution_strategy
from .video_service import read_idx, write_idx

_logger = get_logger(__name__)


_ERROR_SUMMARY_MAX_LEN = 1024
_CANCELLED_ERROR_SUMMARY = "Job cancelled by user request"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _truncate_error_summary(error_summary: str | None) -> str | None:
    if error_summary is None:
        return None
    value = error_summary.strip()
    if len(value) <= _ERROR_SUMMARY_MAX_LEN:
        return value
    return value[: _ERROR_SUMMARY_MAX_LEN - 3] + "..."


def _database_ready() -> bool:
    if not settings.database_url:
        return False

    engine = get_engine()
    if engine is None:
        return False

    Base.metadata.create_all(bind=engine)
    return True


def _to_db_status(status_value: ApiJobStatus | str) -> DbJobStatus:
    return DbJobStatus(status_value.value if hasattr(status_value, "value") else str(status_value))


def _to_api_status(status_value: DbJobStatus) -> ApiJobStatus:
    return ApiJobStatus(status_value.value)



def _touch_json_index(
    *,
    job_id: str,
    source_video_id: str,
    result_video_id: str,
    transform_type: TransformType,
    status_value: str,
    result_storage_path: str,
    result_filename: str,
    source_filename: str,
    tracking_results_path: str | None,
    slam_results_path: str | None,
    runtime_params: dict[str, Any],
    pod_id: str | None = None,
    pod_name: str | None = None,
    execution_backend: str | None = None,
    error_summary: str | None = None,
    exit_code: int | None = None,
) -> None:
    idx = read_idx()
    videos = idx.setdefault("videos", {})
    jobs = idx.setdefault("jobs", {})
    assoc = idx.setdefault("associations", {})

    if result_video_id not in videos:
        videos[result_video_id] = {
            "video_id": result_video_id,
            "source_filename": result_filename,
            "stored_filename": result_filename,
            "storage_path": result_storage_path,
            "content_type": "video/mp4",
            "uploaded_by": runtime_params.get("auth_subject"),
            "uploaded_api_key": runtime_params.get("auth_api_key"),
            "created_at": _now().isoformat(),
            "kind": "derived",
            "status": status_value,
            "transform_type": transform_type.value,
            "source_video_id": source_video_id,
            "tracking_results_path": tracking_results_path,
            "slam_results_path": slam_results_path,
        }
    else:
        videos[result_video_id]["status"] = status_value
        videos[result_video_id]["storage_path"] = result_storage_path
        videos[result_video_id]["stored_filename"] = result_filename

    jobs[job_id] = {
        "job_id": job_id,
        "job_name": runtime_params["job_name"],
        "transform_type": transform_type.value,
        "source_video_id": source_video_id,
        "result_video_id": result_video_id,
        "status": status_value,
        "container_name": runtime_params.get("container_name"),
        "pod_id": pod_id or runtime_params.get("pod_id"),
        "pod_name": pod_name or runtime_params.get("pod_name"),
        "execution_backend": execution_backend or runtime_params.get("execution_backend"),
        "created_at": runtime_params.get("created_at") or _now().isoformat(),
        "updated_at": _now().isoformat(),
        "tracking_results_path": tracking_results_path,
        "slam_results_path": slam_results_path,
        "runtime_params": runtime_params,
        "error_summary": error_summary,
        "exit_code": exit_code,
    }

    rows = assoc.setdefault(source_video_id, [])
    for row in rows:
        if row.get("job_id") == job_id:
            row["status"] = status_value
            break
    else:
        rows.append(
            {
                "result_video_id": result_video_id,
                "transform_type": transform_type.value,
                "job_id": job_id,
                "status": status_value,
            }
        )

    write_idx(idx)


def register_job_submission(
    *,
    job_id: str,
    job_name: str,
    transform_type: TransformType,
    source_video_id: str,
    result_video_id: str,
    result_filename: str,
    result_storage_path: str,
    tracking_results_path: str | None,
    slam_results_path: str | None,
    runtime_params: dict[str, Any],
) -> None:
    database_ready = _database_ready()

    now = _now()
    db_runtime_params = dict(runtime_params)
    db_runtime_params.setdefault("job_name", job_name)
    db_runtime_params.setdefault("result_filename", result_filename)
    db_runtime_params.setdefault("result_storage_path", result_storage_path)
    db_runtime_params.setdefault("tracking_results_path", tracking_results_path)
    db_runtime_params.setdefault("slam_results_path", slam_results_path)
    db_runtime_params.setdefault("execution_backend", runtime_params.get("execution_backend", settings.execution_backend))

    if database_ready:
        with session_scope() as session:
            pod_id = runtime_params.get("pod_id")
            pod_name = runtime_params.get("pod_name")
            execution_backend = runtime_params.get("execution_backend") or settings.execution_backend
            session.add(
                JobRecord(
                    job_id=job_id,
                    job_name=job_name,
                    transform_type=DbTransformType(transform_type.value),
                    source_video_id=source_video_id,
                    result_video_id=result_video_id,
                    status=DbJobStatus.queued,
                    container_name=runtime_params.get("container_name"),
                    pod_id=pod_id,
                    pod_name=pod_name,
                    execution_backend=execution_backend,
                    exit_code=None,
                    error_summary=None,
                    runtime_params=db_runtime_params,
                    created_at=now,
                    updated_at=now,
                )
            )

    _touch_json_index(
        job_id=job_id,
        source_video_id=source_video_id,
        result_video_id=result_video_id,
        transform_type=transform_type,
        status_value=ApiJobStatus.queued.value,
        result_storage_path=result_storage_path,
        result_filename=result_filename,
        source_filename=runtime_params.get("source_filename", result_filename),
        tracking_results_path=tracking_results_path,
        slam_results_path=slam_results_path,
        runtime_params=runtime_params,
        pod_id=runtime_params.get("pod_id"),
        pod_name=runtime_params.get("pod_name"),
        execution_backend=runtime_params.get("execution_backend"),
    )


def update_job_runtime_metadata(job_id: str, updates: dict[str, Any]) -> None:
    database_ready = _database_ready()
    normalized_updates = dict(updates)

    if database_ready:
        with session_scope() as session:
            job = session.get(JobRecord, job_id)
            if job is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Job not found for job_id={job_id}",
                )

            runtime_params = job.runtime_params or {}
            if not isinstance(runtime_params, dict):
                runtime_params = {}
            runtime_params.update(normalized_updates)
            job.runtime_params = runtime_params
            if "container_name" in normalized_updates:
                job.container_name = normalized_updates.get("container_name")
            if "pod_id" in normalized_updates:
                job.pod_id = normalized_updates.get("pod_id")
            if "pod_name" in normalized_updates:
                job.pod_name = normalized_updates.get("pod_name")
            if "execution_backend" in normalized_updates:
                job.execution_backend = normalized_updates.get("execution_backend")
            job.updated_at = _now()

    idx = read_idx()
    jobs = idx.setdefault("jobs", {})
    job_row = jobs.get(job_id)
    if job_row is not None:
        runtime_params = job_row.get("runtime_params") or {}
        if not isinstance(runtime_params, dict):
            runtime_params = {}
        runtime_params.update(normalized_updates)
        job_row["runtime_params"] = runtime_params
        if "container_name" in normalized_updates:
            job_row["container_name"] = normalized_updates.get("container_name")
        if "pod_id" in normalized_updates:
            job_row["pod_id"] = normalized_updates.get("pod_id")
        if "pod_name" in normalized_updates:
            job_row["pod_name"] = normalized_updates.get("pod_name")
        if "execution_backend" in normalized_updates:
            job_row["execution_backend"] = normalized_updates.get("execution_backend")
        job_row["updated_at"] = _now().isoformat()
        write_idx(idx)


def mark_job_running(job_id: str) -> None:
    database_ready = _database_ready()

    if database_ready:
        with session_scope() as session:
            job = session.get(JobRecord, job_id)
            if job is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Job not found for job_id={job_id}",
                )

            if job.status == DbJobStatus.succeeded or job.status == DbJobStatus.failed:
                return

            job.status = DbJobStatus.running
            job.updated_at = _now()

    _sync_json_status(job_id, ApiJobStatus.running.value)


def update_job_completion(
    *,
    job_id: str,
    status_value: ApiJobStatus,
    exit_code: int | None = None,
    error_summary: str | None = None,
) -> None:
    database_ready = _database_ready()
    normalized_error_summary = _truncate_error_summary(error_summary)

    if database_ready:
        with session_scope() as session:
            job = session.get(JobRecord, job_id)
            if job is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Job not found for job_id={job_id}",
                )

            job.status = _to_db_status(status_value)
            job.exit_code = exit_code
            job.error_summary = normalized_error_summary
            job.updated_at = _now()

            runtime_params = job.runtime_params or {}
            if isinstance(runtime_params, dict):
                runtime_params = dict(runtime_params)
            runtime_params["exit_code"] = exit_code
            runtime_params["error_summary"] = normalized_error_summary
            job.runtime_params = runtime_params

    _sync_json_status(job_id, status_value.value, exit_code=exit_code, error_summary=normalized_error_summary)


def _sync_json_status(
    job_id: str,
    status_value: str,
    *,
    exit_code: int | None = None,
    error_summary: str | None = None,
) -> None:
    error_summary = _truncate_error_summary(error_summary)
    idx = read_idx()
    jobs = idx.setdefault("jobs", {})
    assoc = idx.setdefault("associations", {})
    videos = idx.setdefault("videos", {})

    job_row = jobs.get(job_id)
    if job_row is None:
        write_idx(idx)
        return

    job_row["status"] = status_value
    job_row["updated_at"] = _now().isoformat()
    job_row["exit_code"] = exit_code
    job_row["error_summary"] = error_summary

    result_video_id = job_row.get("result_video_id")
    if result_video_id and result_video_id in videos:
        videos[result_video_id]["status"] = status_value
        if error_summary is not None:
            videos[result_video_id]["error_summary"] = error_summary

    source_video_id = job_row.get("source_video_id")
    if source_video_id in assoc:
        for row in assoc[source_video_id]:
            if row.get("job_id") == job_id:
                row["status"] = status_value
                break

    write_idx(idx)


def _job_to_response(job: JobRecord) -> JobStatusResponse:
    runtime_params = job.runtime_params or {}
    if not isinstance(runtime_params, dict):
        runtime_params = {}
    return JobStatusResponse(
        job_id=job.job_id,
        job_name=job.job_name,
        transform_type=TransformType(job.transform_type.value),
        source_video_id=job.source_video_id,
        result_video_id=job.result_video_id,
        status=_to_api_status(job.status),
        container_name=job.container_name or runtime_params.get("container_name"),
        pod_id=job.pod_id or runtime_params.get("pod_id"),
        pod_name=job.pod_name or runtime_params.get("pod_name"),
        execution_backend=job.execution_backend or runtime_params.get("execution_backend"),
        exit_code=job.exit_code,
        error_summary=job.error_summary,
        created_at=job.created_at,
        updated_at=job.updated_at,
    )


def _job_response_from_json(job_row: dict[str, Any]) -> JobStatusResponse:
    runtime_params = job_row.get("runtime_params") or {}
    if not isinstance(runtime_params, dict):
        runtime_params = {}
    transform_value = job_row.get("transform_type")
    status_value = job_row.get("status") or ApiJobStatus.queued.value
    return JobStatusResponse(
        job_id=job_row["job_id"],
        job_name=job_row.get("job_name", f"job-{job_row['job_id']}"),
        transform_type=TransformType(transform_value) if transform_value else None,
        source_video_id=job_row.get("source_video_id"),
        result_video_id=job_row.get("result_video_id"),
        status=ApiJobStatus(status_value),
        container_name=job_row.get("container_name") or runtime_params.get("container_name"),
        pod_id=job_row.get("pod_id") or runtime_params.get("pod_id"),
        pod_name=job_row.get("pod_name") or runtime_params.get("pod_name"),
        execution_backend=job_row.get("execution_backend") or runtime_params.get("execution_backend"),
        exit_code=job_row.get("exit_code"),
        error_summary=job_row.get("error_summary"),
        created_at=None,
        updated_at=None,
    )


def _refresh_job_from_execution(job: JobRecord) -> JobRecord:
    runtime_params = job.runtime_params or {}
    if not isinstance(runtime_params, dict):
        runtime_params = {}

    execution_backend = (job.execution_backend or runtime_params.get("execution_backend") or settings.execution_backend).strip().lower()
    strategy = get_execution_strategy(execution_backend)
    identifier = job.pod_id or runtime_params.get("pod_id") or job.container_name or runtime_params.get("container_name")
    if not identifier:
        return job

    inspection = strategy.inspect(identifier, runtime_params)
    if inspection.state == "running":
        return job

    if inspection.state == "succeeded":
        update_job_completion(job_id=job.job_id, status_value=ApiJobStatus.succeeded, exit_code=inspection.exit_code)
    else:
        update_job_completion(
            job_id=job.job_id,
            status_value=ApiJobStatus.failed,
            exit_code=inspection.exit_code,
            error_summary=inspection.error_summary,
        )
    strategy.cleanup(identifier)

    database_ready = _database_ready()
    if not database_ready:
        return job

    with session_scope() as session:
        refreshed = session.get(JobRecord, job.job_id)
        if refreshed is None:
            return job
        return refreshed


def get_job_status(job_id: str) -> JobStatusResponse:
    database_ready = _database_ready()

    if database_ready:
        with session_scope() as session:
            job = session.get(JobRecord, job_id)
            if job is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Job not found for job_id={job_id}",
                )

            if job.status == DbJobStatus.running:
                refreshed = _refresh_job_from_execution(job)
                if refreshed is not job:
                    job = refreshed

            return _job_to_response(job)

    idx = read_idx()
    job_row = idx.get("jobs", {}).get(job_id)
    if job_row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job not found for job_id={job_id}",
        )

    if job_row.get("status") == ApiJobStatus.running.value:
        runtime_params = job_row.get("runtime_params") or {}
        if not isinstance(runtime_params, dict):
            runtime_params = {}
        strategy = get_execution_strategy(job_row.get("execution_backend") or runtime_params.get("execution_backend") or settings.execution_backend)
        identifier = job_row.get("pod_id") or runtime_params.get("pod_id") or job_row.get("container_name") or runtime_params.get("container_name")
        if identifier:
            inspection = strategy.inspect(identifier, runtime_params)
            if inspection.state != "running":
                update_job_completion(
                    job_id=job_id,
                    status_value=ApiJobStatus.succeeded if inspection.state == "succeeded" else ApiJobStatus.failed,
                    exit_code=inspection.exit_code,
                    error_summary=inspection.error_summary,
                )
                strategy.cleanup(identifier)
                idx = read_idx()
                job_row = idx.get("jobs", {}).get(job_id)
                if job_row is None:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail=f"Job not found for job_id={job_id}",
                    )

    return _job_response_from_json(job_row)


def cancel_job(job_id: str, auth: AuthPayload) -> JobStatusResponse:
    database_ready = _database_ready()

    if database_ready:
        with session_scope() as session:
            job = session.get(JobRecord, job_id)
            if job is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Job not found for job_id={job_id}",
                )

            idx = read_idx()
            source_record = idx.get("videos", {}).get(job.source_video_id)
            if source_record is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Source video not found for job_id={job_id}",
                )
            if auth.subject != source_record.get("uploaded_by"):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Cancel not authorized for this job.",
                )

            if job.status in {DbJobStatus.succeeded, DbJobStatus.failed}:
                log_event(_logger, "cancel_job_already_terminal", job_id=job_id, status=job.status.value)
                return _job_to_response(job)

            status_value = job.status
            execution_backend = job.execution_backend
            pod_id = job.pod_id
            container_name = job.container_name
            runtime_params = job.runtime_params or {}

        if not isinstance(runtime_params, dict):
            runtime_params = {}

        exit_code = 130
        error_summary = _CANCELLED_ERROR_SUMMARY

        if status_value == DbJobStatus.queued:
            log_event(_logger, "cancel_job_queued", job_id=job_id, subject=auth.subject)
        elif status_value == DbJobStatus.running:
            log_event(_logger, "cancel_job_running", job_id=job_id, subject=auth.subject)
            backend = (execution_backend or runtime_params.get("execution_backend") or settings.execution_backend).strip().lower()
            strategy = get_execution_strategy(backend)
            identifier = pod_id or runtime_params.get("pod_id") or container_name or runtime_params.get("container_name")
            if identifier:
                termination = strategy.terminate(identifier, runtime_params)
                if termination.exit_code is not None:
                    exit_code = termination.exit_code
                if termination.state == "running" and termination.error_summary:
                    error_summary = f"{_CANCELLED_ERROR_SUMMARY}. Termination warning: {termination.error_summary}"

        update_job_completion(
            job_id=job_id,
            status_value=ApiJobStatus.failed,
            exit_code=exit_code,
            error_summary=error_summary,
        )
        log_event(_logger, "cancel_job_completed", job_id=job_id, subject=auth.subject, exit_code=exit_code)

        return get_job_status(job_id)

    idx = read_idx()
    job_row = idx.get("jobs", {}).get(job_id)
    if job_row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job not found for job_id={job_id}",
        )

    source_video_id = job_row.get("source_video_id")
    source_record = idx.get("videos", {}).get(source_video_id)
    if source_record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Source video not found for job_id={job_id}",
        )
    if auth.subject != source_record.get("uploaded_by"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cancel not authorized for this job.",
        )

    status_value = job_row.get("status") or ApiJobStatus.queued.value
    if status_value in {ApiJobStatus.succeeded.value, ApiJobStatus.failed.value}:
        log_event(_logger, "cancel_job_already_terminal", job_id=job_id, status=status_value)
        return _job_response_from_json(job_row)

    runtime_params = job_row.get("runtime_params") or {}
    if not isinstance(runtime_params, dict):
        runtime_params = {}

    exit_code = 130
    error_summary = _CANCELLED_ERROR_SUMMARY

    if status_value == ApiJobStatus.queued.value:
        log_event(_logger, "cancel_job_queued", job_id=job_id, subject=auth.subject)
    elif status_value == ApiJobStatus.running.value:
        log_event(_logger, "cancel_job_running", job_id=job_id, subject=auth.subject)
        execution_backend = (job_row.get("execution_backend") or runtime_params.get("execution_backend") or settings.execution_backend).strip().lower()
        strategy = get_execution_strategy(execution_backend)
        identifier = job_row.get("pod_id") or runtime_params.get("pod_id") or job_row.get("container_name") or runtime_params.get("container_name")
        if identifier:
            termination = strategy.terminate(identifier, runtime_params)
            if termination.exit_code is not None:
                exit_code = termination.exit_code
            if termination.state == "running" and termination.error_summary:
                error_summary = f"{_CANCELLED_ERROR_SUMMARY}. Termination warning: {termination.error_summary}"

    update_job_completion(
        job_id=job_id,
        status_value=ApiJobStatus.failed,
        exit_code=exit_code,
        error_summary=error_summary,
    )
    log_event(_logger, "cancel_job_completed", job_id=job_id, subject=auth.subject, exit_code=exit_code)

    return get_job_status(job_id)


def _relpath_under_data_root(path: Path) -> Path:
    resolved_root = settings.wham_data_dir.resolve()
    resolved_path = path.resolve()
    try:
        return resolved_path.relative_to(resolved_root)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Path is outside WHAM data root: {path}",
        ) from exc


def _write_tree_to_zip(zip_file: zipfile.ZipFile, source_path: Path) -> int:
    if source_path.is_file():
        zip_file.write(source_path, arcname=_relpath_under_data_root(source_path).as_posix())
        return 1

    if not source_path.is_dir():
        return 0

    written = 0
    for file_path in sorted(source_path.rglob("*")):
        if not file_path.is_file():
            continue
        zip_file.write(file_path, arcname=_relpath_under_data_root(file_path).as_posix())
        written += 1
    return written


def build_associated_artifacts_archive(source_video_id: str, auth: AuthPayload) -> Path:
    index_data = read_idx()
    videos = index_data.get("videos", {})

    source_record = videos.get(source_video_id)
    if source_record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Video not found for video_id={source_video_id}",
        )

    owner_subject = source_record.get("uploaded_by")
    if auth.subject != owner_subject:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Download not authorized for this video.",
        )

    archive_file = tempfile.NamedTemporaryFile(prefix=f"{source_video_id}__artifacts_", suffix=".zip", delete=False)
    archive_path = Path(archive_file.name)
    archive_file.close()

    written_files = 0
    seen_paths: set[Path] = set()
    source_storage_path = Path(source_record.get("storage_path", ""))

    with zipfile.ZipFile(archive_path, mode="w", compression=zipfile.ZIP_DEFLATED) as zip_file:
        if source_storage_path.is_file():
            written_files += _write_tree_to_zip(zip_file, source_storage_path)
            seen_paths.add(source_storage_path.resolve())

        for row in index_data.get("associations", {}).get(source_video_id, []):
            result_video_id = row.get("result_video_id")
            if not result_video_id:
                continue

            result_record = videos.get(result_video_id)
            if result_record is None:
                continue

            storage_path = Path(result_record.get("storage_path", ""))
            if not storage_path.exists():
                continue

            resolved_storage_path = storage_path.resolve()
            if resolved_storage_path in seen_paths:
                continue

            written_files += _write_tree_to_zip(zip_file, storage_path.parent if storage_path.is_file() else storage_path)
            seen_paths.add(resolved_storage_path)

    if written_files == 0:
        archive_path.unlink(missing_ok=True)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No associated artifacts found for video_id={source_video_id}",
        )

    return archive_path


def build_job_artifacts_archive(job_id: str, auth: AuthPayload) -> Path:
    job = get_job_status(job_id)
    source_video_id = job.source_video_id
    result_video_id = job.result_video_id

    if source_video_id is None or result_video_id is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job artifacts not available for job_id={job_id}",
        )

    index_data = read_idx()
    videos = index_data.get("videos", {})

    source_record = videos.get(source_video_id)
    if source_record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Source video not found for job_id={job_id}",
        )

    owner_subject = source_record.get("uploaded_by")
    if auth.subject != owner_subject:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Download not authorized for this video.",
        )

    result_record = videos.get(result_video_id)
    if result_record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Derived video not found for job_id={job_id}",
        )

    archive_file = tempfile.NamedTemporaryFile(prefix=f"{job_id}__artifacts_", suffix=".zip", delete=False)
    archive_path = Path(archive_file.name)
    archive_file.close()

    written_files = 0
    source_storage_path = Path(source_record.get("storage_path", ""))
    result_storage_path = Path(result_record.get("storage_path", ""))

    with zipfile.ZipFile(archive_path, mode="w", compression=zipfile.ZIP_DEFLATED) as zip_file:
        if source_storage_path.is_file():
            written_files += _write_tree_to_zip(zip_file, source_storage_path)

        if result_storage_path.exists():
            written_files += _write_tree_to_zip(
                zip_file,
                result_storage_path.parent if result_storage_path.is_file() else result_storage_path,
            )

    if written_files == 0:
        archive_path.unlink(missing_ok=True)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No associated artifacts found for job_id={job_id}",
        )

    return archive_path


