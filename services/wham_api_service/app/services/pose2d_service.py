import uuid
from pathlib import Path

from app.core.settings import settings
from app.models.schemas import AuthPayload, JobStatus, PoseJobAcceptedResponse, PoseJobSubmitRequest, TransformType
from app.services.pose_command_builder import build_pose2d_pipeline_spec
from app.services.job_queue import enqueue_job
from app.services.job_service import register_job_submission
from app.services.video_service import get_video


def submit_pose2d(payload: PoseJobSubmitRequest, auth: AuthPayload) -> PoseJobAcceptedResponse:
    """Submit a 2D pose extraction and rendering job."""
    src = get_video(video_id=payload.source_video_id, auth=auth)

    job_id = f"job_{uuid.uuid4().hex[:12]}"
    job_name = f"pose2d-{job_id}"
    result_id = f"vid_{uuid.uuid4().hex[:16]}"
    result_name = f"{result_id}.mp4"
    # Use backend-specific GPU ID based on execution backend
    if settings.execution_backend == "runpod":
        gpu_id = settings.runpod_gpu_id or settings.default_gpu_id
    else:
        gpu_id = settings.docker_gpu_id or settings.default_gpu_id
    estimate_local_only = settings.pose2d_estimate_local_only
    visualize = settings.pose2d_visualize
    calib = None
    pod_name = f"wham-pose2d-{job_id}"

    stem = Path(src["stored_filename"]).stem
    output_pth = f"output/pose2d/{job_id}"
    output_dir = f"{output_pth}/{stem}"
    result_storage_path = settings.wham_data_dir / output_dir / result_name
    tracking_results_path = settings.wham_data_dir / output_dir / "tracking_results.pth"
    slam_results_path = settings.wham_data_dir / output_dir / "slam_results.pth"

    runtime_params = {
        "job_name": job_name,
        "container_name": pod_name,
        "pod_name": pod_name,
        "execution_backend": settings.execution_backend,
        "gpu_id": gpu_id,
        "video": f"/videos/{src['stored_filename']}",
        "source_filename": src["stored_filename"],
        "source_video_path": str(src["storage_path"]),
        "output_pth": output_pth,
        "output_dir": output_dir,
        "result_filename": result_name,
        "result_storage_path": str(result_storage_path),
        "tracking_results_path": str(tracking_results_path),
        "slam_results_path": str(slam_results_path),
        "estimate_local_only": estimate_local_only,
        "visualize": visualize,
        "calib": calib,
        "auth_subject": auth.subject,
        "auth_api_key": auth.api_key,
    }

    cmd_spec = build_pose2d_pipeline_spec(
        source_name=src["stored_filename"],
        job_id=job_id,
        result_name=result_name,
        gpu_id=gpu_id,
        estimate_local_only=estimate_local_only,
        calib=calib,
    )
    runtime_params["docker_cmd"] = cmd_spec["docker_cmd"]
    runtime_params["runpod_entrypoint"] = cmd_spec["runpod_entrypoint"]

    register_job_submission(
        job_id=job_id,
        job_name=job_name,
        transform_type=TransformType.pose2d,
        source_video_id=payload.source_video_id,
        result_video_id=result_id,
        result_filename=result_name,
        result_storage_path=str(result_storage_path),
        tracking_results_path=str(tracking_results_path),
        slam_results_path=str(slam_results_path),
        runtime_params=runtime_params,
    )

    enqueue_job(job_id)

    return PoseJobAcceptedResponse(
        job_id=job_id,
        job_name=job_name,
        transform_type=TransformType.pose2d,
        source_video_id=payload.source_video_id,
        result_video_id=result_id,
        status=JobStatus.queued,
    )
