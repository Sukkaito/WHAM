from datetime import datetime
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


class TransformType(str, Enum):
    pose2d = "pose2d"
    pose3d = "pose3d"


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


class PoseJobAcceptedResponse(BaseModel):
    job_id: str
    job_name: str
    transform_type: TransformType
    source_video_id: str
    result_video_id: Optional[str] = None
    status: JobStatus


class JobStatusResponse(BaseModel):
    job_id: str
    job_name: str
    transform_type: Optional[TransformType] = None
    source_video_id: Optional[str] = None
    result_video_id: Optional[str] = None
    status: JobStatus
    container_name: Optional[str] = None
    exit_code: Optional[int] = None
    error_summary: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class DerivedVideoAssociation(BaseModel):
    result_video_id: str
    transform_type: TransformType
    job_id: str
    status: JobStatus


class VideoAssociationsResponse(BaseModel):
    source_video_id: str
    derived_videos: List[DerivedVideoAssociation]
