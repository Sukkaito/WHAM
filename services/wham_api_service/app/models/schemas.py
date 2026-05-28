from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class TransformType(str, Enum):
    pose2d = "pose2d"
    pose3d = "pose3d"
    custom_v1 = "custom_v1"
    pose_grade = "pose_grade"


class JobStatus(str, Enum):
    queued = "queued"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"


class AuthPayload(BaseModel):
    subject: str = Field(..., min_length=1)
    api_key: str = Field(..., min_length=1)


class UploadVideoResponse(BaseModel):
    video_id: str
    filename: str
    status: str


class PoseJobSubmitRequest(BaseModel):
    source_video_id: str = Field(..., min_length=1)


class PoseGradeJobSubmitRequest(BaseModel):
    source_video_id_a: str = Field(..., min_length=1)
    source_video_id_b: str = Field(..., min_length=1)


class PoseJobAcceptedResponse(BaseModel):
    job_id: str
    job_name: str
    transform_type: TransformType
    source_video_id: str
    result_video_id: Optional[str] = None
    status: JobStatus


class PoseGradeJobAcceptedResponse(BaseModel):
    job_id: str
    job_name: str
    transform_type: TransformType
    source_video_id_a: str
    source_video_id_b: str
    status: JobStatus


class JobStatusResponse(BaseModel):
    job_id: str
    job_name: str
    transform_type: Optional[TransformType] = None
    source_video_id: Optional[str] = None
    result_video_id: Optional[str] = None
    status: JobStatus
    job_output: Optional[Dict[str, Any]] = None
    container_name: Optional[str] = None
    pod_id: Optional[str] = None
    pod_name: Optional[str] = None
    execution_backend: Optional[str] = None
    exit_code: Optional[int] = None
    error_summary: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class JobListResponse(BaseModel):
    jobs: List[JobStatusResponse]
    total: int
    limit: int
    offset: int


class DerivedVideoAssociation(BaseModel):
    result_video_id: str
    transform_type: TransformType
    job_id: str
    status: JobStatus


class VideoAssociationsResponse(BaseModel):
    source_video_id: str
    derived_videos: List[DerivedVideoAssociation]
