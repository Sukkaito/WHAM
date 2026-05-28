import uuid
from pathlib import Path

from app.core.settings import settings
from app.db.models import Base, JobRecord, JobStatus as DbJobStatus, TransformType as DbTransformType
from app.db.session import get_engine, session_scope
from app.models.schemas import (
    AuthPayload,
    JobStatus,
    PoseGradeJobAcceptedResponse,
    PoseGradeJobSubmitRequest,
    TransformType,
)
from app.services.job_queue import enqueue_job
from app.services.job_service import register_job_submission
from app.services.pose_command_builder import build_pose_grade_pipeline_spec
from app.services.video_service import get_video


def _to_container_output_path(host_path: Path) -> str:
    output_root = settings.wham_data_dir / "output"
    try:
        rel = host_path.relative_to(output_root)
    except ValueError:
        return str(host_path)
    return f"/code/output/{rel.as_posix()}"


def _database_ready() -> bool:
    if not settings.database_url:
        return False

    engine = get_engine()
    if engine is None:
        return False

    Base.metadata.create_all(bind=engine)
    return True


def _find_pose2d_artifacts(source_video_id: str) -> tuple[str | None, str | None]:
    if not _database_ready():
        return None, None

    with session_scope() as session:
        jobs = (
            session.query(JobRecord)
            .filter(JobRecord.transform_type == DbTransformType.pose2d)
            .filter(JobRecord.source_video_id == source_video_id)
            .filter(JobRecord.status == DbJobStatus.succeeded)
            .order_by(JobRecord.updated_at.desc(), JobRecord.created_at.desc())
            .all()
        )

        for job in jobs:
            runtime_params = job.runtime_params or {}
            if not isinstance(runtime_params, dict):
                runtime_params = {}
            tracking_path = runtime_params.get("tracking_results_path")
            slam_path = runtime_params.get("slam_results_path")

            if tracking_path and not Path(tracking_path).is_file():
                tracking_path = None
            if slam_path and not Path(slam_path).is_file():
                slam_path = None

            if tracking_path:
                return tracking_path, slam_path

    return None, None


def submit_pose_grade(payload: PoseGradeJobSubmitRequest, auth: AuthPayload) -> PoseGradeJobAcceptedResponse:
    src_a = get_video(video_id=payload.source_video_id_a, auth=auth)
    src_b = get_video(video_id=payload.source_video_id_b, auth=auth)

    job_id = f"job_{uuid.uuid4().hex[:12]}"
    job_name = f"pose-grade-{job_id}"
    pod_name = f"wham-pose-grade-{job_id}"

    if settings.execution_backend == "runpod":
        gpu_id = settings.runpod_gpu_id or settings.default_gpu_id
    else:
        gpu_id = settings.docker_gpu_id or settings.default_gpu_id

    stem_a = Path(src_a.stored_filename).stem
    stem_b = Path(src_b.stored_filename).stem
    output_pth = f"output/pose_grade/{job_id}"
    output_dir_a = f"{output_pth}/{stem_a}"
    output_dir_b = f"{output_pth}/{stem_b}"

    default_tracking_a = settings.wham_data_dir / output_dir_a / "tracking_results.pth"
    default_slam_a = settings.wham_data_dir / output_dir_a / "slam_results.pth"
    default_tracking_b = settings.wham_data_dir / output_dir_b / "tracking_results.pth"
    default_slam_b = settings.wham_data_dir / output_dir_b / "slam_results.pth"

    tracking_a, slam_a = _find_pose2d_artifacts(payload.source_video_id_a)
    tracking_b, slam_b = _find_pose2d_artifacts(payload.source_video_id_b)

    tracking_a = tracking_a or str(default_tracking_a)
    slam_a = slam_a or str(default_slam_a)
    tracking_b = tracking_b or str(default_tracking_b)
    slam_b = slam_b or str(default_slam_b)

    score_path = settings.wham_data_dir / output_pth / "score.json"

    runtime_params = {
        "job_name": job_name,
        "container_name": pod_name,
        "pod_name": pod_name,
        "execution_backend": settings.execution_backend,
        "gpu_id": gpu_id,
        "video_a": f"/videos/{src_a.stored_filename}",
        "video_b": f"/videos/{src_b.stored_filename}",
        "source_filename": src_a.stored_filename,
        "source_filename_a": src_a.stored_filename,
        "source_filename_b": src_b.stored_filename,
        "source_video_id_a": payload.source_video_id_a,
        "source_video_id_b": payload.source_video_id_b,
        "source_video_path_a": str(src_a.storage_path),
        "source_video_path_b": str(src_b.storage_path),
        "output_dir_a": output_dir_a,
        "output_dir_b": output_dir_b,
        "tracking_results_path_a": tracking_a,
        "tracking_results_path_b": tracking_b,
        "slam_results_path_a": slam_a,
        "slam_results_path_b": slam_b,
        "score_path": str(score_path),
        "comparison_method": "dtw",
        "input_video_ids": [payload.source_video_id_a, payload.source_video_id_b],
        "auth_subject": auth.subject,
        "auth_api_key": auth.api_key,
    }

    cmd_spec = build_pose_grade_pipeline_spec(
        job_id=job_id,
        gpu_id=gpu_id,
        source_name_a=src_a.stored_filename,
        source_name_b=src_b.stored_filename,
        output_dir_a=_to_container_output_path(settings.wham_data_dir / output_dir_a),
        output_dir_b=_to_container_output_path(settings.wham_data_dir / output_dir_b),
        tracking_results_path_a=_to_container_output_path(Path(tracking_a)),
        tracking_results_path_b=_to_container_output_path(Path(tracking_b)),
        source_video_id_a=payload.source_video_id_a,
        source_video_id_b=payload.source_video_id_b,
        slam_results_path_a=_to_container_output_path(Path(slam_a)),
        slam_results_path_b=_to_container_output_path(Path(slam_b)),
        score_path=_to_container_output_path(score_path),
    )
    runtime_params["docker_cmd"] = cmd_spec["docker_cmd"]
    runtime_params["runpod_entrypoint"] = cmd_spec["runpod_entrypoint"]

    register_job_submission(
        job_id=job_id,
        job_name=job_name,
        transform_type=TransformType.pose_grade,
        source_video_id=payload.source_video_id_a,
        result_video_id=None,
        result_filename=None,
        result_storage_path=None,
        tracking_results_path=None,
        slam_results_path=None,
        runtime_params=runtime_params,
    )

    enqueue_job(job_id)

    return PoseGradeJobAcceptedResponse(
        job_id=job_id,
        job_name=job_name,
        transform_type=TransformType.pose_grade,
        source_video_id_a=payload.source_video_id_a,
        source_video_id_b=payload.source_video_id_b,
        status=JobStatus.queued,
    )
