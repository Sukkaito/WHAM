from __future__ import annotations

import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import HTTPException, status

from app.core.logging import get_logger, log_event
from app.core.settings import settings
from app.db.models import Base, JobRecord, JobStatus as DbJobStatus, TransformType as DbTransformType, VideoRecord
from app.db.session import get_engine, session_scope
from app.models.lineage import VideoRecordDTO
from app.models.schemas import AuthPayload, JobListResponse, JobStatus as ApiJobStatus
from app.models.schemas import JobStatusResponse, TransformType
from .execution_strategy import get_execution_strategy
from .video_service import load_video_record, upsert_video_record

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



def _get_source_video_owner(source_video_id: str) -> str | None:
    source_record = load_video_record(source_video_id)
    if source_record is None:
        return None
    return source_record.uploaded_by


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
    if not database_ready:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database is required for job submission.",
        )

    now = _now()
    db_runtime_params = dict(runtime_params)
    db_runtime_params.setdefault("job_name", job_name)
    db_runtime_params.setdefault("result_filename", result_filename)
    db_runtime_params.setdefault("result_storage_path", result_storage_path)
    db_runtime_params.setdefault("tracking_results_path", tracking_results_path)
    db_runtime_params.setdefault("slam_results_path", slam_results_path)
    db_runtime_params.setdefault("execution_backend", runtime_params.get("execution_backend", settings.execution_backend))

    from .job_utils import create_job_record_kwargs

    with session_scope() as session:
        pod_id = runtime_params.get("pod_id")
        pod_name = runtime_params.get("pod_name")
        execution_backend = runtime_params.get("execution_backend") or settings.execution_backend
        kwargs = create_job_record_kwargs(
            job_id=job_id,
            job_name=job_name,
            transform_type=transform_type.value,
            source_video_id=source_video_id,
            result_video_id=result_video_id,
            container_name=runtime_params.get("container_name"),
            pod_id=pod_id,
            pod_name=pod_name,
            execution_backend=execution_backend,
            runtime_params=db_runtime_params,
            now=now,
        )
        session.add(JobRecord(**kwargs))

    upsert_video_record(
        video_id=result_video_id,
        source_filename=result_filename,
        stored_filename=result_filename,
        storage_path=result_storage_path,
        content_type="video/mp4",
        uploaded_by=runtime_params.get("auth_subject"),
        size_bytes=None,
        kind="derived",
        status=ApiJobStatus.queued.value,
        source_video_id=source_video_id,
        transform_type=transform_type.value,
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

    return


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
            if job.result_video_id:
                video = session.get(VideoRecord, job.result_video_id)
                if video is not None:
                    video.status = ApiJobStatus.running.value

    return


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

            if job.result_video_id:
                video = session.get(VideoRecord, job.result_video_id)
                if video is not None:
                    video.status = status_value.value

    return


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

    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="Database is required for job status lookup.",
    )


def list_jobs(
    *,
    auth: AuthPayload,
    status_filter: ApiJobStatus | None = None,
    job_type_filter: TransformType | None = None,
    source_video_id: str | None = None,
    result_video_id: str | None = None,
    execution_backend: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> JobListResponse:
    limit = max(1, min(limit, 200))
    offset = max(0, offset)

    def _authorized_source(video_id: str | None) -> bool:
        if not video_id:
            return False
        owner_subject = _get_source_video_owner(video_id)
        return owner_subject == auth.subject

    def _matches_filters(row: dict[str, Any]) -> bool:
        row_status = row.get("status")
        row_job_type = row.get("transform_type")
        row_source_video_id = row.get("source_video_id")
        row_result_video_id = row.get("result_video_id")
        row_execution_backend = (row.get("execution_backend") or "").strip().lower()

        if status_filter and row_status != status_filter.value:
            return False
        if job_type_filter and row_job_type != job_type_filter.value:
            return False
        if source_video_id and row_source_video_id != source_video_id:
            return False
        if result_video_id and row_result_video_id != result_video_id:
            return False
        if execution_backend and row_execution_backend != execution_backend.strip().lower():
            return False
        if not _authorized_source(row_source_video_id):
            return False
        return True

    database_ready = _database_ready()
    rows: list[dict[str, Any]] = []

    if database_ready:
        from app.db.models import JobRecord

        with session_scope() as session:
            query = session.query(JobRecord)
            if status_filter:
                query = query.filter(JobRecord.status == _to_db_status(status_filter))
            if job_type_filter:
                query = query.filter(JobRecord.transform_type == DbTransformType(job_type_filter.value))
            if source_video_id:
                query = query.filter(JobRecord.source_video_id == source_video_id)
            if result_video_id:
                query = query.filter(JobRecord.result_video_id == result_video_id)
            if execution_backend:
                query = query.filter(JobRecord.execution_backend == execution_backend.strip().lower())

            for job in query.order_by(JobRecord.created_at.desc()).all():
                runtime_params = job.runtime_params or {}
                if not isinstance(runtime_params, dict):
                    runtime_params = {}
                row = {
                    "job_id": job.job_id,
                    "job_name": job.job_name,
                    "transform_type": job.transform_type.value if job.transform_type else None,
                    "source_video_id": job.source_video_id,
                    "result_video_id": job.result_video_id,
                    "status": job.status.value,
                    "container_name": job.container_name,
                    "pod_id": job.pod_id,
                    "pod_name": job.pod_name,
                    "execution_backend": job.execution_backend,
                    "exit_code": job.exit_code,
                    "error_summary": job.error_summary,
                    "runtime_params": runtime_params,
                    "created_at": job.created_at,
                    "updated_at": job.updated_at,
                }
                if _matches_filters(row):
                    rows.append(row)
    else:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database is required for job listing.",
        )

    total = len(rows)
    page_rows = rows[offset : offset + limit]

    jobs: list[JobStatusResponse] = []
    for row in page_rows:
        if database_ready:
            runtime_params = row.get("runtime_params") or {}
            if not isinstance(runtime_params, dict):
                runtime_params = {}
            jobs.append(
                JobStatusResponse(
                    job_id=row["job_id"],
                    job_name=row.get("job_name", f"job-{row['job_id']}"),
                    transform_type=TransformType(row["transform_type"]) if row.get("transform_type") else None,
                    source_video_id=row.get("source_video_id"),
                    result_video_id=row.get("result_video_id"),
                    status=ApiJobStatus(row["status"]),
                    container_name=row.get("container_name") or runtime_params.get("container_name"),
                    pod_id=row.get("pod_id") or runtime_params.get("pod_id"),
                    pod_name=row.get("pod_name") or runtime_params.get("pod_name"),
                    execution_backend=row.get("execution_backend") or runtime_params.get("execution_backend"),
                    exit_code=row.get("exit_code"),
                    error_summary=row.get("error_summary"),
                    created_at=row.get("created_at"),
                    updated_at=row.get("updated_at"),
                )
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Database is required for job listing.",
            )

    return JobListResponse(jobs=jobs, total=total, limit=limit, offset=offset)


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

            owner_subject = _get_source_video_owner(job.source_video_id)
            if owner_subject is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Source video not found for job_id={job_id}",
                )
            if auth.subject != owner_subject:
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

    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="Database is required for job cancellation.",
    )


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
    source_record = load_video_record(source_video_id)
    if source_record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Video not found for video_id={source_video_id}",
        )

    owner_subject = source_record.uploaded_by
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
    source_storage_path = Path(source_record.storage_path)

    with zipfile.ZipFile(archive_path, mode="w", compression=zipfile.ZIP_DEFLATED) as zip_file:
        if source_storage_path.is_file():
            written_files += _write_tree_to_zip(zip_file, source_storage_path)
            seen_paths.add(source_storage_path.resolve())

        with session_scope() as session:
            jobs = (
                session.query(JobRecord)
                .filter(JobRecord.source_video_id == source_video_id)
                .order_by(JobRecord.created_at.desc())
                .all()
            )
            rows = [job.result_video_id for job in jobs if job.result_video_id]

        for row in rows:
            result_record = load_video_record(row)
            if result_record is None:
                continue

            storage_path = Path(result_record.storage_path)
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

    source_record = load_video_record(source_video_id)
    if source_record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Source video not found for job_id={job_id}",
        )

    owner_subject = source_record.uploaded_by
    if auth.subject != owner_subject:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Download not authorized for this video.",
        )

    result_record = load_video_record(result_video_id)
    if result_record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Derived video not found for job_id={job_id}",
        )

    archive_file = tempfile.NamedTemporaryFile(prefix=f"{job_id}__artifacts_", suffix=".zip", delete=False)
    archive_path = Path(archive_file.name)
    archive_file.close()

    written_files = 0
    source_storage_path = Path(source_record.storage_path)
    result_storage_path = Path(result_record.storage_path)

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


