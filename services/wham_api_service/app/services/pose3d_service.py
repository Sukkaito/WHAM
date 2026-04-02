import uuid
from pathlib import Path

from fastapi import HTTPException, status

from app.core.settings import settings
from app.models.schemas import JobStatus, PoseJobAcceptedResponse, PoseJobSubmitRequest, TransformType
from app.services.docker_executor import build_pose3d_pipeline_cmd, execute_docker_detached
from app.services.job_service import register_job_submission, start_job_monitor, update_job_completion
from app.services.video_service import get_video


def submit_pose3d(payload: PoseJobSubmitRequest) -> PoseJobAcceptedResponse:
    """Submit a pose3d job via detached cascading 2D->3D extraction pipeline."""
    src = get_video(video_id=payload.source_video_id, auth=payload.auth)

    job_id = f"job_{uuid.uuid4().hex[:12]}"
    job_name = f"pose3d-{job_id}"
    result_id = f"vid_{uuid.uuid4().hex[:16]}"
    result_name = f"{result_id}.mp4"
    gpu_id = settings.default_gpu_id
    estimate_local_only = settings.pose3d_estimate_local_only
    visualize = settings.pose3d_visualize
    save_pkl = settings.pose3d_save_pkl
    run_smplify = settings.pose3d_run_smplify
    calib = None
    container_name = f"wham-pose3d-{job_id}"

    stem = Path(src["stored_filename"]).stem
    output_pth = f"output/pose3d/{job_id}"
    output_dir = f"{output_pth}/{stem}"
    result_storage_path = settings.wham_data_dir / output_dir / result_name
    tracking_results_path = settings.wham_data_dir / output_dir / "tracking_results.pth"
    slam_results_path = settings.wham_data_dir / output_dir / "slam_results.pth"

    runtime_params = {
        "job_name": job_name,
        "container_name": container_name,
        "gpu_id": gpu_id,
        "video": f"/videos/{src['stored_filename']}",
        "source_filename": src["stored_filename"],
        "source_video_path": src["storage_path"],
        "output_pth": output_pth,
        "output_dir": output_dir,
        "result_filename": result_name,
        "result_storage_path": str(result_storage_path),
        "tracking_results_path": str(tracking_results_path),
        "slam_results_path": str(slam_results_path),
        "estimate_local_only": estimate_local_only,
        "visualize": visualize,
        "save_pkl": save_pkl,
        "run_smplify": run_smplify,
        "calib": calib,
        "auth_subject": payload.auth.subject,
        "auth_token": payload.auth.token,
    }

    register_job_submission(
        job_id=job_id,
        job_name=job_name,
        transform_type=TransformType.pose3d,
        source_video_id=payload.source_video_id,
        result_video_id=result_id,
        result_filename=result_name,
        result_storage_path=str(result_storage_path),
        tracking_results_path=str(tracking_results_path),
        slam_results_path=str(slam_results_path),
        runtime_params=runtime_params,
    )

    cmd = build_pose3d_pipeline_cmd(
        source_name=src["stored_filename"],
        job_id=job_id,
        output_dir=output_dir,
        gpu_id=gpu_id,
        result_name=result_name,
        estimate_local_only=estimate_local_only,
        visualize=visualize,
        save_pkl=save_pkl,
        run_smplify=run_smplify,
        calib=calib,
    )

    result = execute_docker_detached(cmd, cwd=settings.repo_dir)
    if not result.success:
        msg = (result.stderr or result.stdout or "pose3d docker launch failed").strip()
        update_job_completion(
            job_id=job_id,
            status_value=JobStatus.failed,
            error_summary=msg,
        )
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=msg)

    start_job_monitor(job_id)

    return PoseJobAcceptedResponse(
        job_id=job_id,
        job_name=job_name,
        transform_type=TransformType.pose3d,
        source_video_id=payload.source_video_id,
        result_video_id=result_id,
        status=JobStatus.running,
    )