from fastapi import APIRouter, File, Form, UploadFile, status
from fastapi.responses import FileResponse

from app.models.schemas import (
    AuthPayload,
    UploadVideoResponse,
    VideoAssociationsResponse,
)
from app.services.video_service import (
    get_video,
    list_assoc,
    store_video,
)

router = APIRouter()


@router.post(
    "/videos/upload",
    response_model=UploadVideoResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_video(
    file: UploadFile = File(...),
    auth_subject: str = Form(...),
    auth_token: str = Form(...),
) -> UploadVideoResponse:
    """Phase 2 step 1: store uploaded source video and persist metadata."""
    auth = AuthPayload(subject=auth_subject, token=auth_token)
    return await store_video(file=file, auth=auth)


@router.get("/videos/{video_id}/download")
def download_video(
    video_id: str,
    auth_subject: str,
    auth_token: str,
):
    """Phase 2 step 2: authorize and stream stored video by video_id."""
    auth = AuthPayload(subject=auth_subject, token=auth_token)
    video_record = get_video(video_id=video_id, auth=auth)
    return FileResponse(
        path=video_record["storage_path"],
        media_type=video_record["content_type"],
        filename=video_record["source_filename"],
    )


@router.get(
    "/videos/{video_id}/associations",
    response_model=VideoAssociationsResponse,
)
def get_video_associations(video_id: str) -> VideoAssociationsResponse:
    """Return persisted lineage rows for a source video."""
    return list_assoc(source_video_id=video_id)
