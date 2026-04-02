import uuid
from datetime import datetime, timezone
from pathlib import Path

from app.core.settings import settings
from app.models.schemas import JobStatus, PoseJobAcceptedResponse, PoseJobSubmitRequest, TransformType
from app.services.docker_executor import (
    build_pose3d_pipeline_cmd,
    execute_docker_detached,
)
from app.services.video_service import get_video, read_idx, write_idx


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _save_job(
    payload: PoseJobSubmitRequest,
    job_id: str,
    job_name: str,
    result_id: str,
    source_name: str,
    video_arg: str,
    output_pth: str,
    output_dir: str,
    gpu_id: str,
    estimate_local_only: bool,
    visualize: bool,
    save_pkl: bool,
    run_smplify: bool,
    calib: str | None,
) -> None:
    """Persist pose3d job and result metadata."""
    idx = read_idx()
    videos = idx.setdefault("videos", {})
    jobs = idx.setdefault("jobs", {})
    assoc = idx.setdefault("associations", {})

    out_dir = settings.wham_data_dir / output_dir
    tracking_results_path = out_dir / "tracking_results.pth"
    slam_results_path = out_dir / "slam_results.pth"

    videos[result_id] = {
        "video_id": result_id,
        "source_filename": f"{result_id}_wham_output.pkl",
        "stored_filename": f"{result_id}_wham_output.pkl",
        "storage_path": str(out_dir / "wham_output.pkl"),
        "content_type": "application/octet-stream",
        "uploaded_by": payload.auth.subject,
        "uploaded_token": payload.auth.token,
        "created_at": _now(),
        "kind": "derived",
        "status": "pending",
        "transform_type": "pose3d",
        "source_video_id": payload.source_video_id,
        "tracking_results_path": str(tracking_results_path),
        "slam_results_path": str(slam_results_path),
    }

    jobs[job_id] = {
        "job_id": job_id,
        "job_name": job_name,
        "transform_type": "pose3d",
        "source_video_id": payload.source_video_id,
        "result_video_id": result_id,
        "status": "running",
        "video": video_arg,
        "output_pth": output_pth,
        "output_dir": output_dir,
        "gpu_id": gpu_id,
        "container_name": f"wham-pose3d-{job_id}",
        "tracking_results_path": str(tracking_results_path),
        "slam_results_path": str(slam_results_path),
        "estimate_local_only": estimate_local_only,
        "visualize": visualize,
        "save_pkl": save_pkl,
        "run_smplify": run_smplify,
        "calib": calib,
        "created_at": _now(),
        "updated_at": _now(),
    }

    assoc.setdefault(payload.source_video_id, []).append(
        {
            "result_video_id": result_id,
            "transform_type": "pose3d",
            "job_id": job_id,
            "status": "running",
        }
    )

    write_idx(idx)


def submit_pose3d(payload: PoseJobSubmitRequest) -> PoseJobAcceptedResponse:
    """
    Submit a pose3d job via detached cascading 2D→3D extraction pipeline.

    Flow inside container command (ordered):
    1. Ensure output directory exists.
    2. If preprocessing artifacts are missing, run extract_2d_poses.py first.
    3. Run extract_3d_poses.py (with visualize profile flag).

    API request path remains async: it returns after detached container launch.
    """
    src = get_video(video_id=payload.source_video_id, auth=payload.auth)

    job_id = f"job_{uuid.uuid4().hex[:12]}"
    job_name = f"pose3d-{job_id}"
    result_id = f"vid_{uuid.uuid4().hex[:16]}"
    gpu_id = settings.default_gpu_id
    estimate_local_only = False
    visualize = True
    save_pkl = True
    run_smplify = False
    calib = None

    stem = Path(src["stored_filename"]).stem
    video_arg = f"/videos/{src['stored_filename']}"
    output_pth = f"output/pose3d/{job_id}"
    output_dir = f"{output_pth}/{stem}"
    cmd = build_pose3d_pipeline_cmd(
        source_name=src["stored_filename"],
        job_id=job_id,
        output_dir=output_dir,
        gpu_id=gpu_id,
        visualize=visualize,
        save_pkl=save_pkl,
        run_smplify=run_smplify,
    )

    result = execute_docker_detached(cmd, cwd=settings.repo_dir)
    if not result.success:
        msg = (result.stderr or result.stdout or "pose3d docker launch failed").strip()
        raise RuntimeError(msg)

    _save_job(
        payload=payload,
        job_id=job_id,
        job_name=job_name,
        result_id=result_id,
        source_name=src["stored_filename"],
        video_arg=video_arg,
        output_pth=output_pth,
        output_dir=output_dir,
        gpu_id=gpu_id,
        estimate_local_only=estimate_local_only,
        visualize=visualize,
        save_pkl=save_pkl,
        run_smplify=run_smplify,
        calib=calib,
    )

    return PoseJobAcceptedResponse(
        job_id=job_id,
        job_name=job_name,
        transform_type=TransformType.pose3d,
        source_video_id=payload.source_video_id,
        result_video_id=result_id,
        status=JobStatus.running,
    )