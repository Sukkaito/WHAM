import logging

from fastapi import APIRouter, File, UploadFile, Request, status
from fastapi.responses import FileResponse

from app.core.auth import get_request_auth
from app.models.schemas import UploadVideoResponse, VideoAssociationsResponse
from app.services.video_service import (
    get_video,
    list_assoc,
    store_video,
)

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post(
    "/videos/upload",
    response_model=UploadVideoResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_video(
    request: Request,
    file: UploadFile = File(...),
) -> UploadVideoResponse:
    """Phase 2 step 1: store uploaded source video and persist metadata."""
    auth = get_request_auth(request)
    logger.info("upload_video request subject=%s filename=%s", auth.subject, file.filename)
    try:
        return await store_video(file=file, auth=auth)
    except Exception:
        logger.exception("upload_video failed subject=%s filename=%s", auth.subject, file.filename)
        raise


@router.get("/videos/{video_id}/download")
def download_video(
    request: Request,
    video_id: str,
):
    """Phase 2 step 2: authorize and stream stored video by video_id."""
    auth = get_request_auth(request)
    logger.info("download_video request subject=%s video_id=%s", auth.subject, video_id)
    try:
        video_record = get_video(video_id=video_id, auth=auth)
        return FileResponse(
            path=video_record["storage_path"],
            media_type=video_record["content_type"],
            filename=video_record["source_filename"],
        )
    except Exception:
        logger.exception("download_video failed subject=%s video_id=%s", auth.subject, video_id)
        raise


@router.get(
    "/videos/{video_id}/associations",
    response_model=VideoAssociationsResponse,
)
def get_video_associations(video_id: str) -> VideoAssociationsResponse:
    """Return persisted lineage rows for a source video."""
    return list_assoc(source_video_id=video_id)
