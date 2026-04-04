import logging

from fastapi import APIRouter, HTTPException, Request, status

from app.core.auth import get_request_auth
from app.models.schemas import (
    JobStatusResponse,
    PoseJobAcceptedResponse,
    PoseJobSubmitRequest,
)
from app.services.job_service import get_job_status as load_job_status
from app.services.pose2d_service import submit_pose2d
from app.services.pose3d_service import submit_pose3d

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/pose2d/jobs", response_model=PoseJobAcceptedResponse)
def submit_pose2d_job(request: Request, payload: PoseJobSubmitRequest) -> PoseJobAcceptedResponse:
    """Phase 2 step 3: launch pose2d GPU Docker job and persist lineage."""
    auth = get_request_auth(request)
    logger.info("submit_pose2d_job source_video_id=%s subject=%s", payload.source_video_id, auth.subject)
    try:
        return submit_pose2d(payload, auth)
    except HTTPException:
        raise
    except Exception:
        logger.exception("submit_pose2d_job failed source_video_id=%s subject=%s", payload.source_video_id, auth.subject)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="pose2d submission failed",
        )


@router.post("/pose3d/jobs", response_model=PoseJobAcceptedResponse)
def submit_pose3d_job(request: Request, payload: PoseJobSubmitRequest) -> PoseJobAcceptedResponse:
    """Phase 2 step 4: launch pose3d GPU Docker job with preprocessing reuse when available."""
    auth = get_request_auth(request)
    logger.info("submit_pose3d_job source_video_id=%s subject=%s", payload.source_video_id, auth.subject)
    try:
        return submit_pose3d(payload, auth)
    except HTTPException:
        raise
    except Exception:
        logger.exception("submit_pose3d_job failed source_video_id=%s subject=%s", payload.source_video_id, auth.subject)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="pose3d submission failed",
        )


@router.get("/jobs/{job_id}", response_model=JobStatusResponse)
def get_job_status(job_id: str) -> JobStatusResponse:
    """Return durable job lifecycle state from PostgreSQL."""
    logger.info("get_job_status job_id=%s", job_id)
    try:
        return load_job_status(job_id)
    except HTTPException:
        raise
    except Exception:
        logger.exception("get_job_status failed job_id=%s", job_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="job lookup failed",
        )
