import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request, status
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

from app.core.auth import get_request_auth
from app.models.schemas import (
    JobListResponse,
    JobStatus,
    JobStatusResponse,
    PoseJobAcceptedResponse,
    PoseJobSubmitRequest,
    TransformType,
)
from app.services.job_service import (
    build_job_artifacts_archive,
    cancel_job as cancel_job_service,
    list_jobs as load_jobs,
    get_job_status as load_job_status,
)
from app.services.custom_v1_service import submit_custom_v1
from app.services.pose2d_service import submit_pose2d
from app.services.pose3d_service import submit_pose3d

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/pose2d/jobs", response_model=PoseJobAcceptedResponse)
def submit_pose2d_job(request: Request, payload: PoseJobSubmitRequest) -> PoseJobAcceptedResponse:
    """Phase 2 step 3: launch pose2d GPU Docker job and persist lineage."""
    auth = get_request_auth(request)
    logger.info("submit_pose2d_job source_video_id=%s subject=%s", payload.source_video_id, auth.subject)
    return submit_pose2d(payload, auth)


@router.post("/pose3d/jobs", response_model=PoseJobAcceptedResponse)
def submit_pose3d_job(request: Request, payload: PoseJobSubmitRequest) -> PoseJobAcceptedResponse:
    """Phase 2 step 4: launch pose3d GPU Docker job with preprocessing reuse when available."""
    auth = get_request_auth(request)
    logger.info("submit_pose3d_job source_video_id=%s subject=%s", payload.source_video_id, auth.subject)
    return submit_pose3d(payload, auth)


@router.post("/custom_v1/jobs", response_model=PoseJobAcceptedResponse)
def submit_custom_v1_job(request: Request, payload: PoseJobSubmitRequest) -> PoseJobAcceptedResponse:
    """Submit a custom_v1 WHAM demo job."""
    auth = get_request_auth(request)
    logger.info("submit_custom_v1_job source_video_id=%s subject=%s", payload.source_video_id, auth.subject)
    return submit_custom_v1(payload, auth)


@router.get("/jobs/{job_id}", response_model=JobStatusResponse)
def get_job_status(job_id: str) -> JobStatusResponse:
    """Return durable job lifecycle state from PostgreSQL."""
    logger.info("get_job_status job_id=%s", job_id)
    return load_job_status(job_id)


@router.get("/jobs", response_model=JobListResponse)
def list_jobs(
    request: Request,
    status_filter: Optional[JobStatus] = Query(default=None, alias="status"),
    job_type_filter: Optional[TransformType] = Query(default=None, alias="job_type"),
    source_video_id: Optional[str] = Query(default=None),
    result_video_id: Optional[str] = Query(default=None),
    execution_backend: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> JobListResponse:
    """List jobs for the authenticated subject with optional filters."""
    auth = get_request_auth(request)
    logger.info(
        "list_jobs subject=%s status=%s job_type=%s source_video_id=%s result_video_id=%s execution_backend=%s limit=%s offset=%s",
        auth.subject,
        status_filter.value if status_filter else None,
        job_type_filter.value if job_type_filter else None,
        source_video_id,
        result_video_id,
        execution_backend,
        limit,
        offset,
    )
    return load_jobs(
        auth=auth,
        status_filter=status_filter,
        job_type_filter=job_type_filter,
        source_video_id=source_video_id,
        result_video_id=result_video_id,
        execution_backend=execution_backend,
        limit=limit,
        offset=offset,
    )


@router.post("/jobs/{job_id}/cancel", response_model=JobStatusResponse)
def cancel_job(request: Request, job_id: str) -> JobStatusResponse:
    """Cancel a queued or running job and persist terminal state."""
    auth = get_request_auth(request)
    logger.info("cancel_job job_id=%s subject=%s", job_id, auth.subject)
    return cancel_job_service(job_id=job_id, auth=auth)


@router.get("/jobs/{job_id}/artifacts/download")
def download_job_artifacts(request: Request, job_id: str):
    """Download a zip archive of the source video and derived artifacts for a job."""
    auth = get_request_auth(request)
    logger.info("download_job_artifacts job_id=%s subject=%s", job_id, auth.subject)
    archive_path = build_job_artifacts_archive(job_id=job_id, auth=auth)
    return FileResponse(
        path=archive_path,
        media_type="application/zip",
        filename=f"{job_id}__associated_artifacts.zip",
        background=BackgroundTask(lambda: archive_path.unlink(missing_ok=True)),
    )
