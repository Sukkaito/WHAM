from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.settings import settings
from app.db.models import Base, JobRecord, JobStatus as DbJobStatus, TransformType as DbTransformType, VideoRecord
from app.db.session import get_engine, session_scope
from app.models.schemas import JobStatus as ApiJobStatus
from app.services.job_service import _database_ready
from app.services.video_service import read_idx


def _now(value: Any | None = None) -> datetime:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
        except Exception:
            pass
    return datetime.now(timezone.utc)


def _normalize_job_status(value: str | None) -> DbJobStatus:
    if not value:
        return DbJobStatus.queued
    try:
        return DbJobStatus(value)
    except Exception:
        return DbJobStatus.failed


def _upsert_video(session, row: dict[str, Any]) -> None:
    video_id = row.get("video_id")
    if not video_id:
        return

    record = session.get(VideoRecord, video_id)
    if record is None:
        record = VideoRecord(
            video_id=video_id,
            filename=row.get("source_filename") or row.get("stored_filename") or video_id,
            stored_filename=row.get("stored_filename") or row.get("source_filename") or video_id,
            kind=row.get("kind") or "source",
            status=row.get("status") or "stored",
            storage_path=row.get("storage_path") or "",
            content_type=row.get("content_type"),
            uploaded_by=row.get("uploaded_by"),
            size_bytes=row.get("size_bytes"),
            source_video_id=row.get("source_video_id"),
            transform_type=row.get("transform_type"),
            created_at=_now(row.get("created_at")),
            updated_at=_now(row.get("updated_at") or row.get("created_at")),
        )
        session.add(record)
        return

    record.filename = row.get("source_filename") or row.get("stored_filename") or record.filename
    record.stored_filename = row.get("stored_filename") or row.get("source_filename") or record.stored_filename
    record.kind = row.get("kind") or record.kind
    record.status = row.get("status") or record.status
    record.storage_path = row.get("storage_path") or record.storage_path
    record.content_type = row.get("content_type")
    record.uploaded_by = row.get("uploaded_by") or record.uploaded_by
    record.size_bytes = row.get("size_bytes")
    record.source_video_id = row.get("source_video_id")
    record.transform_type = row.get("transform_type")
    record.updated_at = _now(row.get("updated_at") or row.get("created_at"))


def _upsert_job(session, row: dict[str, Any]) -> None:
    job_id = row.get("job_id")
    if not job_id:
        return

    transform_type = row.get("transform_type")
    source_video_id = row.get("source_video_id")
    if not transform_type or not source_video_id:
        return

    runtime_params = row.get("runtime_params") or {}
    if not isinstance(runtime_params, dict):
        runtime_params = {}

    record = session.get(JobRecord, job_id)
    created_at = _now(row.get("created_at"))
    updated_at = _now(row.get("updated_at") or row.get("created_at"))
    status = _normalize_job_status(row.get("status"))

    if record is None:
        record = JobRecord(
            job_id=job_id,
            job_name=row.get("job_name") or f"job-{job_id}",
            transform_type=DbTransformType(transform_type),
            source_video_id=source_video_id,
            result_video_id=row.get("result_video_id"),
            status=status,
            container_name=row.get("container_name"),
            pod_id=row.get("pod_id"),
            pod_name=row.get("pod_name"),
            execution_backend=row.get("execution_backend"),
            exit_code=row.get("exit_code"),
            error_summary=row.get("error_summary"),
            runtime_params=runtime_params,
            created_at=created_at,
            updated_at=updated_at,
        )
        session.add(record)
        return

    record.job_name = row.get("job_name") or record.job_name
    record.transform_type = DbTransformType(transform_type)
    record.source_video_id = source_video_id
    record.result_video_id = row.get("result_video_id")
    record.status = status
    record.container_name = row.get("container_name")
    record.pod_id = row.get("pod_id")
    record.pod_name = row.get("pod_name")
    record.execution_backend = row.get("execution_backend")
    record.exit_code = row.get("exit_code")
    record.error_summary = row.get("error_summary")
    record.runtime_params = runtime_params
    record.updated_at = updated_at


def migrate_index(dry_run: bool = False) -> None:
    if not settings.database_url:
        raise RuntimeError("DATABASE_URL is not configured")

    engine = get_engine()
    if engine is None:
        raise RuntimeError("Database engine is unavailable")

    Base.metadata.create_all(bind=engine)
    index_data = read_idx()

    videos = index_data.get("videos", {})
    jobs = index_data.get("jobs", {})
    associations = index_data.get("associations", {})

    if dry_run:
        print(f"Would migrate {len(videos)} videos, {len(jobs)} jobs, {len(associations)} association groups")
        return

    with session_scope() as session:
        for row in videos.values():
            if isinstance(row, dict):
                _upsert_video(session, row)

        for row in jobs.values():
            if isinstance(row, dict):
                _upsert_job(session, row)

        for source_video_id, rows in associations.items():
            if not isinstance(rows, list):
                continue
            for row in rows:
                if not isinstance(row, dict):
                    continue
                job_id = row.get("job_id")
                if not job_id:
                    continue
                job = session.get(JobRecord, job_id)
                if job is None:
                    continue
                if row.get("result_video_id"):
                    job.result_video_id = row.get("result_video_id")
                if row.get("status"):
                    try:
                        job.status = DbJobStatus(row.get("status"))
                    except Exception:
                        job.status = DbJobStatus.failed
                job.updated_at = _now(row.get("updated_at") or row.get("created_at"))


def main() -> int:
    parser = argparse.ArgumentParser(description="Migrate WHAM JSON index rows into the database")
    parser.add_argument("--dry-run", action="store_true", help="Print counts without writing to the database")
    args = parser.parse_args()

    migrate_index(dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())