from fastapi import APIRouter, HTTPException, status

from app.models.schemas import (
    JobStatusResponse,
    PoseJobAcceptedResponse,
    PoseJobSubmitRequest,
)
from app.services.job_service import get_job_status as load_job_status
from app.services.pose2d_service import submit_pose2d
from app.services.pose3d_service import submit_pose3d

router = APIRouter()


@router.post("/pose2d/jobs", response_model=PoseJobAcceptedResponse)
def submit_pose2d_job(payload: PoseJobSubmitRequest) -> PoseJobAcceptedResponse:
    """Phase 2 step 3: launch pose2d GPU Docker job and persist lineage."""
    try:
        return submit_pose2d(payload)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"pose2d submission failed: {exc}",
        ) from exc


@router.post("/pose3d/jobs", response_model=PoseJobAcceptedResponse)
def submit_pose3d_job(payload: PoseJobSubmitRequest) -> PoseJobAcceptedResponse:
    """Phase 2 step 4: launch pose3d GPU Docker job with preprocessing reuse when available."""
    try:
        return submit_pose3d(payload)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"pose3d submission failed: {exc}",
        ) from exc


@router.get("/jobs/{job_id}", response_model=JobStatusResponse)
def get_job_status(job_id: str) -> JobStatusResponse:
    """Return durable job lifecycle state from PostgreSQL."""
    try:
        return load_job_status(job_id)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"job lookup failed: {exc}",
        ) from exc
