from datetime import datetime
from enum import Enum

from sqlalchemy import DateTime, Enum as SAEnum, Integer, JSON, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class TransformType(str, Enum):
    pose2d = "pose2d"
    pose3d = "pose3d"


class JobStatus(str, Enum):
    queued = "queued"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"


class VideoRecord(Base):
    __tablename__ = "videos"

    video_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    storage_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class JobRecord(Base):
    __tablename__ = "jobs"

    job_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    job_name: Mapped[str] = mapped_column(String(255), nullable=False)
    transform_type: Mapped[TransformType] = mapped_column(SAEnum(TransformType), nullable=False)
    source_video_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    result_video_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    status: Mapped[JobStatus] = mapped_column(SAEnum(JobStatus), nullable=False)
    container_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    exit_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_summary: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    runtime_params: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
