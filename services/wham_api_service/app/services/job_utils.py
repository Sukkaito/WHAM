from datetime import datetime, timezone
from typing import Any

from app.db.models import JobRecord, JobStatus as DbJobStatus, TransformType as DbTransformType


def create_job_record_kwargs(
    *,
    job_id: str,
    job_name: str,
    transform_type: str,
    source_video_id: str,
    result_video_id: str | None,
    container_name: str | None,
    pod_id: str | None,
    pod_name: str | None,
    execution_backend: str | None,
    runtime_params: dict[str, Any],
    now: datetime | None = None,
) -> dict:
    now = now or datetime.now(timezone.utc)
    return {
        "job_id": job_id,
        "job_name": job_name,
        "transform_type": DbTransformType(transform_type),
        "source_video_id": source_video_id,
        "result_video_id": result_video_id,
        "status": DbJobStatus.queued,
        "container_name": container_name,
        "pod_id": pod_id,
        "pod_name": pod_name,
        "execution_backend": execution_backend,
        "exit_code": None,
        "error_summary": None,
        "runtime_params": runtime_params,
        "created_at": now,
        "updated_at": now,
    }
