import uuid
from datetime import datetime, timezone
from pathlib import Path

from app.core.settings import settings
from app.models.schemas import JobStatus, PoseJobAcceptedResponse, PoseJobSubmitRequest, TransformType
from app.services.docker_executor import build_pose2d_pipeline_cmd, execute_docker_detached
from app.services.video_service import get_video, read_idx, write_idx


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()





def _save_job(
    payload: PoseJobSubmitRequest,
    job_id: str,
    job_name: str,
    result_id: str,
    result_name: str,
    source_name: str,
    video_arg: str,
    output_pth: str,
    output_dir: str,
    container_name: str,
    gpu_id: str,
    estimate_local_only: bool,
    visualize: bool,
    calib: str | None,
) -> None:
    """Save job/result metadata, including preprocessing artifact locations for downstream use."""
    idx = read_idx()
    videos = idx.setdefault("videos", {})
    jobs = idx.setdefault("jobs", {})
    assoc = idx.setdefault("associations", {})

    out_dir = settings.wham_data_dir / output_dir
    result_path = out_dir / result_name
    tracking_results_path = out_dir / "tracking_results.pth"
    slam_results_path = out_dir / "slam_results.pth"
    
    videos[result_id] = {
        "video_id": result_id,
        "source_filename": result_name,
        "stored_filename": result_name,
        "storage_path": str(result_path),
        "content_type": "video/mp4",
        "uploaded_by": payload.auth.subject,
        "uploaded_token": payload.auth.token,
        "created_at": _now(),
        "kind": "derived",
        "status": "pending",
        "transform_type": "pose2d",
        "source_video_id": payload.source_video_id,
        "tracking_results_path": str(tracking_results_path),  # 2D pose data for downstream use
        "slam_results_path": str(slam_results_path),  # camera trajectory data for global mode
    }

    jobs[job_id] = {
        "job_id": job_id,
        "job_name": job_name,
        "transform_type": "pose2d",
        "source_video_id": payload.source_video_id,
        "result_video_id": result_id,
        "status": "running",
        "video": video_arg,
        "output_pth": output_pth,
        "output_dir": output_dir,
        "gpu_id": gpu_id,
        "container_name": container_name,
        "created_at": _now(),
        "updated_at": _now(),
        "tracking_results_path": str(tracking_results_path),
        "slam_results_path": str(slam_results_path),
        "estimate_local_only": estimate_local_only,
        "visualize": visualize,
        "calib": calib,
        "run_global": not estimate_local_only,
    }

    assoc.setdefault(payload.source_video_id, []).append(
        {
            "result_video_id": result_id,
            "transform_type": "pose2d",
            "job_id": job_id,
            "status": "running",
        }
    )

    write_idx(idx)


def submit_pose2d(payload: PoseJobSubmitRequest) -> PoseJobAcceptedResponse:
    """
    Submit a 2D pose extraction and rendering job.
    
    Pipeline:
    1. Extract 2D keypoints from source video -> tracking_results.pth
    2. Render 2D overlay video from those keypoints
    3. Return result_video_id pointing to overlay, with tracking data available for downstream
    
    Runs in GPU-enabled Docker container via extract_2d_poses.py with --visualize.
    """
    src = get_video(video_id=payload.source_video_id, auth=payload.auth)

    job_id = f"job_{uuid.uuid4().hex[:12]}"
    job_name = f"pose2d-{job_id}"
    result_id = f"vid_{uuid.uuid4().hex[:16]}"
    result_name = f"{result_id}.mp4"
    gpu_id = settings.default_gpu_id
    estimate_local_only = False
    visualize = True
    calib = None
    container_name = f"wham-pose2d-{job_id}"

    stem = Path(src["stored_filename"]).stem
    video_arg = f"/videos/{src['stored_filename']}"
    output_pth = f"output/pose2d/{job_id}"
    output_dir = f"{output_pth}/{stem}"

    cmd = build_pose2d_pipeline_cmd(
        source_name=src["stored_filename"],
        job_id=job_id,
        result_name=result_name,
        gpu_id=gpu_id,
    )

    result = execute_docker_detached(cmd, cwd=settings.repo_dir)
    if not result.success:
        msg = (result.stderr or result.stdout or "pose2d docker launch failed").strip()
        raise RuntimeError(msg)

    _save_job(
        payload=payload,
        job_id=job_id,
        job_name=job_name,
        result_id=result_id,
        result_name=result_name,
        source_name=src["stored_filename"],
        video_arg=video_arg,
        output_pth=output_pth,
        output_dir=output_dir,
        container_name=container_name,
        gpu_id=gpu_id,
        estimate_local_only=estimate_local_only,
        visualize=visualize,
        calib=calib,
    )

    return PoseJobAcceptedResponse(
        job_id=job_id,
        job_name=job_name,
        transform_type=TransformType.pose2d,
        source_video_id=payload.source_video_id,
        result_video_id=result_id,
        status=JobStatus.running,
    )
