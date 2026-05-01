import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import HTTPException, UploadFile, status

from app.core.settings import settings
from app.db.models import Base, JobRecord, VideoRecord
from app.db.session import get_engine, session_scope
from app.models.lineage import DerivedVideoAssociationDTO, VideoFileDTO, VideoRecordDTO
from app.models.schemas import (
    AuthPayload,
    DerivedVideoAssociation,
    JobStatus,
    TransformType,
    UploadVideoResponse,
    VideoAssociationsResponse,
)

_CHUNK_SIZE = 1024 * 1024
_SAFE_FILENAME_PATTERN = re.compile(r"[^A-Za-z0-9._-]+")


def _database_ready() -> bool:
    if not settings.database_url:
        return False

    engine = get_engine()
    if engine is None:
        return False

    Base.metadata.create_all(bind=engine)
    return True


def _sanitize_filename(filename: str) -> str:
    base = Path(filename).name.strip()
    if not base:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file must include a valid filename.",
        )
    return _SAFE_FILENAME_PATTERN.sub("_", base)


def _video_record_to_dto(record: VideoRecord) -> VideoRecordDTO:
    return VideoRecordDTO(
        video_id=record.video_id,
        source_filename=record.filename,
        stored_filename=record.stored_filename,
        storage_path=record.storage_path,
        content_type=record.content_type,
        size_bytes=record.size_bytes,
        uploaded_by=record.uploaded_by,
        created_at=record.created_at,
        kind=record.kind,
        status=record.status,
        source_video_id=record.source_video_id,
        transform_type=record.transform_type,
    )


def upsert_video_record(
    *,
    video_id: str,
    source_filename: str,
    stored_filename: str,
    storage_path: str,
    content_type: str | None,
    uploaded_by: str | None,
    size_bytes: int | None,
    kind: str,
    status: str,
    source_video_id: str | None = None,
    transform_type: str | None = None,
) -> None:
    if not _database_ready():
        return

    now = datetime.now(timezone.utc)
    with session_scope() as session:
        record = session.get(VideoRecord, video_id)
        if record is None:
            record = VideoRecord(
                video_id=video_id,
                filename=source_filename,
                stored_filename=stored_filename,
                kind=kind,
                status=status,
                storage_path=storage_path,
                content_type=content_type,
                uploaded_by=uploaded_by,
                size_bytes=size_bytes,
                source_video_id=source_video_id,
                transform_type=transform_type,
                created_at=now,
            )
            session.add(record)
            return

        record.filename = source_filename
        record.stored_filename = stored_filename
        record.kind = kind
        record.status = status
        record.storage_path = storage_path
        record.content_type = content_type
        record.uploaded_by = uploaded_by
        record.size_bytes = size_bytes
        record.source_video_id = source_video_id
        record.transform_type = transform_type


def load_video_record(video_id: str) -> VideoRecordDTO | None:
    if _database_ready():
        with session_scope() as session:
            record = session.get(VideoRecord, video_id)
            if record is None:
                return None
            return _video_record_to_dto(record)

    return None


def _validate_video_upload(file: UploadFile, safe_filename: str) -> None:
    ext = Path(safe_filename).suffix.lower()
    if ext not in settings.allowed_video_extensions:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported video extension: {ext}",
        )

    if file.content_type and not file.content_type.startswith("video/"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file content type must be a video mime type.",
        )


def _authorize_download(record: VideoRecordDTO, auth: AuthPayload) -> None:
    owner_subject = record.uploaded_by

    # Temporary auth policy until external auth integration is added.
    if auth.subject != owner_subject:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Download not authorized for this video.",
        )


async def store_video(file: UploadFile, auth: AuthPayload) -> UploadVideoResponse:
    safe_filename = _sanitize_filename(file.filename or "")
    _validate_video_upload(file, safe_filename)

    video_id = f"vid_{uuid.uuid4().hex[:16]}"
    stored_filename = f"{video_id}__{safe_filename}"

    settings.videos_dir.mkdir(parents=True, exist_ok=True)
    target_path = settings.videos_dir / stored_filename

    bytes_written = 0
    with target_path.open("wb") as out_f:
        while True:
            chunk = await file.read(_CHUNK_SIZE)
            if not chunk:
                break
            out_f.write(chunk)
            bytes_written += len(chunk)

    await file.close()

    if bytes_written == 0:
        target_path.unlink(missing_ok=True)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded video is empty.",
        )

    upsert_video_record(
        video_id=video_id,
        source_filename=safe_filename,
        stored_filename=stored_filename,
        storage_path=str(target_path),
        content_type=file.content_type,
        uploaded_by=auth.subject,
        size_bytes=bytes_written,
        kind="source",
        status="stored",
    )
    if not _database_ready():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database is required for video storage.",
        )

    return UploadVideoResponse(video_id=video_id, filename=safe_filename, status="stored")


def get_video(video_id: str, auth: AuthPayload) -> VideoFileDTO:
    record = load_video_record(video_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Video not found for video_id={video_id}",
        )

    _authorize_download(record, auth)

    storage_path = Path(record.storage_path)
    if not storage_path.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Stored file missing for video_id={video_id}",
        )

    return VideoFileDTO(
        video_id=video_id,
        storage_path=str(storage_path),
        stored_filename=record.stored_filename or storage_path.name,
        source_filename=record.source_filename or storage_path.name,
        content_type=record.content_type or "application/octet-stream",
    )


def list_assoc(source_video_id: str, auth: AuthPayload) -> VideoAssociationsResponse:
    source_record = load_video_record(source_video_id)
    if source_record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Video not found for video_id={source_video_id}",
        )

    if auth.subject != source_record.uploaded_by:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Download not authorized for this video.",
        )

    rows: list[DerivedVideoAssociationDTO] = []
    if _database_ready():
        with session_scope() as session:
            jobs = (
                session.query(JobRecord)
                .filter(JobRecord.source_video_id == source_video_id)
                .order_by(JobRecord.created_at.desc())
                .all()
            )
            for job in jobs:
                if job.result_video_id and job.transform_type and job.status:
                    rows.append(
                        DerivedVideoAssociationDTO(
                            result_video_id=job.result_video_id,
                            transform_type=job.transform_type.value,
                            job_id=job.job_id,
                            status=job.status.value,
                        )
                    )
    else:
        return VideoAssociationsResponse(source_video_id=source_video_id, derived_videos=[])

    items = []
    for row in rows:
        items.append(
            DerivedVideoAssociation(
                result_video_id=row.result_video_id,
                transform_type=TransformType(row.transform_type),
                job_id=row.job_id,
                status=JobStatus(row.status),
            )
        )

    return VideoAssociationsResponse(source_video_id=source_video_id, derived_videos=items)
