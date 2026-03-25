import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import HTTPException, UploadFile, status

from app.core.settings import settings
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


def _sanitize_filename(filename: str) -> str:
    base = Path(filename).name.strip()
    if not base:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file must include a valid filename.",
        )
    return _SAFE_FILENAME_PATTERN.sub("_", base)


def _load_index(index_file: Path) -> dict[str, Any]:
    if not index_file.exists():
        return {"videos": {}}
    with index_file.open("r", encoding="utf-8") as f:
        return json.load(f)


def _persist_index(index_file: Path, data: dict[str, Any]) -> None:
    index_file.parent.mkdir(parents=True, exist_ok=True)
    tmp_file = index_file.with_suffix(index_file.suffix + ".tmp")
    with tmp_file.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, sort_keys=True)
    tmp_file.replace(index_file)


def read_idx() -> dict[str, Any]:
    return _load_index(settings.video_index_file)


def write_idx(data: dict[str, Any]) -> None:
    _persist_index(settings.video_index_file, data)


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


def _authorize_download(record: dict[str, Any], auth: AuthPayload) -> None:
    owner_subject = record.get("uploaded_by")
    owner_token = record.get("uploaded_token")

    # Temporary auth policy until external auth integration is added.
    if auth.subject != owner_subject:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Download not authorized for this video.",
        )

    if owner_token is not None and auth.token != owner_token:
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

    index_data = read_idx()
    index_data.setdefault("videos", {})[video_id] = {
        "video_id": video_id,
        "source_filename": safe_filename,
        "stored_filename": stored_filename,
        "storage_path": str(target_path),
        "content_type": file.content_type,
        "size_bytes": bytes_written,
        "uploaded_by": auth.subject,
        "uploaded_token": auth.token,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "kind": "source",
        "status": "stored",
    }
    write_idx(index_data)

    return UploadVideoResponse(video_id=video_id, filename=safe_filename, status="stored")


def get_video(video_id: str, auth: AuthPayload) -> dict[str, Any]:
    index_data = read_idx()
    record = index_data.get("videos", {}).get(video_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Video not found for video_id={video_id}",
        )

    _authorize_download(record, auth)

    storage_path = Path(record.get("storage_path", ""))
    if not storage_path.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Stored file missing for video_id={video_id}",
        )

    return {
        "video_id": video_id,
        "storage_path": storage_path,
        "stored_filename": record.get("stored_filename") or storage_path.name,
        "source_filename": record.get("source_filename") or storage_path.name,
        "content_type": record.get("content_type") or "application/octet-stream",
    }


def list_assoc(source_video_id: str) -> VideoAssociationsResponse:
    index_data = read_idx()
    rows = index_data.get("associations", {}).get(source_video_id, [])
    items = []
    for row in rows:
        try:
            items.append(
                DerivedVideoAssociation(
                    result_video_id=row["result_video_id"],
                    transform_type=TransformType(row["transform_type"]),
                    job_id=row["job_id"],
                    status=JobStatus(row["status"]),
                )
            )
        except Exception:
            # Skip malformed rows until strict schema persistence is added.
            continue

    return VideoAssociationsResponse(source_video_id=source_video_id, derived_videos=items)
