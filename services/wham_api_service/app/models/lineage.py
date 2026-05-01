from datetime import datetime
from enum import Enum

from pydantic import BaseModel


class VideoKind(str, Enum):
    source = "source"
    derived = "derived"


class LineageRecord(BaseModel):
    """Shared lineage model for linking source and rendered outputs."""

    source_video_id: str
    result_video_id: str
    transform_type: str
    job_id: str
    created_at: datetime


class VideoRecordDTO(BaseModel):
    video_id: str
    source_filename: str
    stored_filename: str
    storage_path: str
    content_type: str | None = None
    size_bytes: int | None = None
    uploaded_by: str | None = None
    created_at: datetime | None = None
    kind: str
    status: str
    source_video_id: str | None = None
    transform_type: str | None = None


class VideoFileDTO(BaseModel):
    video_id: str
    storage_path: str
    stored_filename: str
    source_filename: str
    content_type: str


class DerivedVideoAssociationDTO(BaseModel):
    result_video_id: str
    transform_type: str
    job_id: str
    status: str
