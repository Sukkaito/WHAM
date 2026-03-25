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
