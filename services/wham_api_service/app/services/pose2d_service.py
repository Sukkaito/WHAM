import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path

from app.core.settings import settings
from app.models.schemas import JobStatus, PoseJobAcceptedResponse, PoseJobSubmitRequest, TransformType
from app.services.video_service import get_video, read_idx, write_idx


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _build_cmd(source_name: str, job_id: str, result_name: str, gpu_id: str) -> list[str]:
    """
    Build docker run command for 2D pose extraction and rendering.
    
     Pipeline:
     1. Extract preprocessing artifacts: tracking_results.pth and slam_results.pth
         (global mode by default, local-only fallback if DPVO/SLAM unavailable)
     2. Render overlay video using tracking_results.pth
    
    Output structure:
    - output/pose2d/{job_id}/{stem}/tracking_results.pth   (2D pose data)
    - output/pose2d/{job_id}/{stem}/slam_results.pth       (camera trajectory data)
    - output/pose2d/{job_id}/{stem}/{result_name}          (rendered overlay video)
    """
    stem = Path(source_name).stem
    out_base = f"output/pose2d/{job_id}"
    track_dir = f"{out_base}/{stem}"
    track_pth = f"{track_dir}/tracking_results.pth"
    out_mp4 = f"{track_dir}/{result_name}"

    inner = (
        f"mkdir -p {track_dir} && "
        f"python3 scripts/extract_2d_poses.py --video /videos/{source_name} --output_dir {track_dir} --device cuda:0 && "
        f"python3 scripts/render_2d_overlay.py --video /videos/{source_name} --tracking_pth {track_pth} --out_mp4 {out_mp4}"
    )

    return [
        "docker",
        "run",
        "--rm",
        "--detach",
        "--platform",
        "linux/amd64",
        "--name",
        f"wham-pose2d-{job_id}",
        "--gpus",
        f"device={gpu_id}",
        "-e",
        f"CUDA_VISIBLE_DEVICES={gpu_id}",
        "-e",
        "PYTHONUNBUFFERED=1",
        "-v",
        f"{settings.wham_data_dir / 'dataset'}:/code/dataset",
        "-v",
        f"{settings.wham_data_dir / 'checkpoints'}:/code/checkpoints",
        "-v",
        f"{settings.wham_data_dir / 'output'}:/code/output",
        "-v",
        f"{settings.wham_data_dir / 'videos'}:/videos",
        "-w",
        "/code",
        settings.docker_image,
        "bash",
        "-lc",
        inner,
    ]


def _save_job(
    payload: PoseJobSubmitRequest,
    job_id: str,
    job_name: str,
    result_id: str,
    result_name: str,
    source_name: str,
    container_name: str,
    gpu_id: str,
) -> None:
    """Save job/result metadata, including preprocessing artifact locations for downstream use."""
    idx = read_idx()
    videos = idx.setdefault("videos", {})
    jobs = idx.setdefault("jobs", {})
    assoc = idx.setdefault("associations", {})

    stem = Path(source_name).stem
    result_path = settings.wham_data_dir / "output" / "pose2d" / job_id / stem / result_name
    tracking_results_path = settings.wham_data_dir / "output" / "pose2d" / job_id / stem / "tracking_results.pth"
    slam_results_path = settings.wham_data_dir / "output" / "pose2d" / job_id / stem / "slam_results.pth"
    
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
        "gpu_id": gpu_id,
        "container_name": container_name,
        "created_at": _now(),
        "updated_at": _now(),
        "tracking_results_path": str(tracking_results_path),  # 2D pose data location
        "slam_results_path": str(slam_results_path),  # camera trajectory data location
        "run_global": True,
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
    
    Runs in GPU-enabled Docker container via extract_2d_poses.py and render_2d_overlay.py.
    """
    src = get_video(video_id=payload.source_video_id, auth=payload.auth)

    job_id = f"job_{uuid.uuid4().hex[:12]}"
    job_name = f"pose2d-{job_id}"
    result_id = f"vid_{uuid.uuid4().hex[:16]}"
    result_name = f"{result_id}.mp4"
    gpu_id = settings.default_gpu_id
    container_name = f"wham-pose2d-{job_id}"

    cmd = _build_cmd(
        source_name=src["stored_filename"],
        job_id=job_id,
        result_name=result_name,
        gpu_id=gpu_id,
    )

    proc = subprocess.run(
        cmd,
        check=False,
        capture_output=True,
        text=True,
        cwd=str(settings.repo_dir),
    )
    if proc.returncode != 0:
        msg = (proc.stderr or proc.stdout or "pose2d docker launch failed").strip()
        raise RuntimeError(msg)

    _save_job(
        payload=payload,
        job_id=job_id,
        job_name=job_name,
        result_id=result_id,
        result_name=result_name,
        source_name=src["stored_filename"],
        container_name=container_name,
        gpu_id=gpu_id,
    )

    return PoseJobAcceptedResponse(
        job_id=job_id,
        job_name=job_name,
        transform_type=TransformType.pose2d,
        source_video_id=payload.source_video_id,
        result_video_id=result_id,
        status=JobStatus.running,
    )
