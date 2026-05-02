from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from sqlalchemy import Boolean, DateTime, Enum as SAEnum, Integer, JSON, String, ForeignKey, Index
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class TransformType(str, Enum):
    pose2d = "pose2d"
    pose3d = "pose3d"
    custom_v1 = "custom_v1"


class JobStatus(str, Enum):
    queued = "queued"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"


class VideoRecord(Base):
    __tablename__ = "videos"

    video_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    stored_filename: Mapped[str] = mapped_column(String(512), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    storage_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    content_type: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    uploaded_by: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    size_bytes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    source_video_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    transform_type: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.now(timezone.utc))
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), default=datetime.now(timezone.utc), nullable=True)


class JobRecord(Base):
    __tablename__ = "jobs"

    job_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    job_name: Mapped[str] = mapped_column(String(255), nullable=False)
    transform_type: Mapped[TransformType] = mapped_column(SAEnum(TransformType), nullable=False)
    source_video_id: Mapped[str] = mapped_column(String(64), ForeignKey("videos.video_id"), index=True, nullable=False)
    result_video_id: Mapped[Optional[str]] = mapped_column(String(64), ForeignKey("videos.video_id"), index=True, nullable=True)
    status: Mapped[JobStatus] = mapped_column(SAEnum(JobStatus), nullable=False)
    container_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    pod_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    pod_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    execution_backend: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    exit_code: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    error_summary: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    runtime_params: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.now(timezone.utc))

    __table_args__ = (
        Index("ix_jobs_status_created_at", "status", "created_at"),
        Index("ix_jobs_transform_created_at", "transform_type", "created_at"),
        Index("ix_jobs_execution_created_at", "execution_backend", "created_at"),
    )


class ApiKeyRecord(Base):
    __tablename__ = "api_keys"

    key_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    subject: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    key_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    key_prefix: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.now(timezone.utc))
    last_used_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
