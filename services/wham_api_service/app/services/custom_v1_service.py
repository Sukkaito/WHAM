import uuid
from pathlib import Path

from app.models.schemas import AuthPayload, PoseJobAcceptedResponse, PoseJobSubmitRequest
from app.models.schemas import JobStatus, TransformType
from app.core.settings import settings
from app.services.job_queue import enqueue_job
from app.services.job_service import register_job_submission
from app.services.pose_command_builder import build_custom_v1_pipeline_spec
from app.services.video_service import get_video


def submit_custom_v1(payload: PoseJobSubmitRequest, auth: AuthPayload) -> PoseJobAcceptedResponse:
    """Submit a custom_v1 WHAM demo job with fixed runtime flags."""
    src = get_video(video_id=payload.source_video_id, auth=auth)

    job_id = f"job_{uuid.uuid4().hex[:12]}"
    job_name = f"custom_v1-{job_id}"

    if settings.execution_backend == "runpod":
        gpu_id = settings.runpod_gpu_id or settings.default_gpu_id
    else:
        gpu_id = settings.docker_gpu_id or settings.default_gpu_id

    stem = Path(src.stored_filename).stem
    output_pth = f"output/custom_v1/{job_id}"
    output_dir = f"{output_pth}/{stem}"

    runtime_params = {
        "job_name": job_name,
        "container_name": f"wham-custom-v1-{job_id}",
        "pod_name": f"wham-custom-v1-{job_id}",
        "execution_backend": settings.execution_backend,
        "gpu_id": gpu_id,
        "video": f"/videos/{src.stored_filename}",
        "source_filename": src.stored_filename,
        "source_video_path": str(src.storage_path),
        "output_pth": output_pth,
        "output_dir": output_dir,
        "estimate_local_only": True,
        "save_pkl": True,
        "auth_subject": auth.subject,
        "auth_api_key": auth.api_key,
    }

    cmd_spec = build_custom_v1_pipeline_spec(
        source_name=src.stored_filename,
        job_id=job_id,
        output_pth=output_pth,
        gpu_id=gpu_id,
    )
    runtime_params["docker_cmd"] = cmd_spec["docker_cmd"]
    runtime_params["runpod_entrypoint"] = cmd_spec["runpod_entrypoint"]

    register_job_submission(
        job_id=job_id,
        job_name=job_name,
        transform_type=TransformType.custom_v1,
        source_video_id=payload.source_video_id,
        result_video_id=None,
        result_filename=None,
        result_storage_path=None,
        tracking_results_path=None,
        slam_results_path=None,
        runtime_params=runtime_params,
    )

    enqueue_job(job_id)

    return PoseJobAcceptedResponse(
        job_id=job_id,
        job_name=job_name,
        transform_type=TransformType.custom_v1,
        source_video_id=payload.source_video_id,
        result_video_id=None,
        status=JobStatus.queued,
    )
