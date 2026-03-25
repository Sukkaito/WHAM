import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path

from app.core.settings import settings
from app.models.schemas import JobStatus, PoseJobAcceptedResponse, PoseJobSubmitRequest, TransformType
from app.services.video_service import get_video, read_idx, write_idx


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _has_preprocessing_artifacts(output_dir: str) -> bool:
    """Check if both tracking_results.pth and slam_results.pth exist."""
    output_path = Path(output_dir)
    tracking = output_path / "tracking_results.pth"
    slam = output_path / "slam_results.pth"
    return tracking.is_file() and slam.is_file()


def _build_extract_2d_cmd(source_name: str, output_dir: str, gpu_id: str) -> list[str]:
    """Build docker command to extract 2D preprocessing artifacts."""
    return [
        "docker",
        "run",
        "--rm",
        "--platform",
        "linux/amd64",
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
        f"python3 scripts/extract_2d_poses.py --video /videos/{source_name} --output_dir {output_dir} --device cuda:0",
    ]


def _build_extract_3d_cmd(
    source_name: str,
    output_dir: str,
    gpu_id: str,
    visualize: bool,
    save_pkl: bool,
    run_smplify: bool,
) -> list[str]:
    """Build docker command to run WHAM 3D pose inference on preprocessing artifacts."""
    cmd_parts = [
        "python3 scripts/extract_3d_poses.py",
        f"--video /videos/{source_name}",
        f"--output_dir {output_dir}",
        "--device cuda:0",
    ]

    if visualize:
        cmd_parts.append("--visualize")
    if save_pkl:
        cmd_parts.append("--save_pkl")
    if run_smplify:
        cmd_parts.append("--run_smplify")

    inner = " ".join(cmd_parts)

    return [
        "docker",
        "run",
        "--rm",
        "--platform",
        "linux/amd64",
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
    source_name: str,
    gpu_id: str,
    visualize: bool,
    save_pkl: bool,
    run_smplify: bool,
) -> None:
    """Persist pose3d job and result metadata."""
    idx = read_idx()
    videos = idx.setdefault("videos", {})
    jobs = idx.setdefault("jobs", {})
    assoc = idx.setdefault("associations", {})

    stem = Path(source_name).stem
    out_dir = settings.wham_data_dir / "output" / "pose3d" / job_id / stem

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
        "tracking_results_path": str(out_dir / "tracking_results.pth"),
        "slam_results_path": str(out_dir / "slam_results.pth"),
    }

    jobs[job_id] = {
        "job_id": job_id,
        "job_name": job_name,
        "transform_type": "pose3d",
        "source_video_id": payload.source_video_id,
        "result_video_id": result_id,
        "status": "running",
        "gpu_id": gpu_id,
        "container_name": f"wham-pose3d-{job_id}",
        "estimate_local_only": False,
        "visualize": visualize,
        "save_pkl": save_pkl,
        "run_smplify": run_smplify,
        "calib": None,
        "output_dir": str(out_dir),
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
    Submit a pose3d job via cascading 2D→3D extraction pipeline.

    Flow:
    1. If preprocessing artifacts (tracking_results.pth, slam_results.pth) don't exist,
       run extract_2d_poses.py to generate them
    2. Run extract_3d_poses.py to perform WHAM 3D pose inference on those artifacts
    3. Persist metadata and lineage

    Separates 2D extraction/SLAM from 3D inference for independent monitoring and reuse.
    Does NOT use demo.py; extraction scripts are standalone.
    """
    src = get_video(video_id=payload.source_video_id, auth=payload.auth)

    job_id = f"job_{uuid.uuid4().hex[:12]}"
    job_name = f"pose3d-{job_id}"
    result_id = f"vid_{uuid.uuid4().hex[:16]}"
    gpu_id = settings.default_gpu_id

    stem = Path(src["stored_filename"]).stem
    out_dir = f"output/pose3d/{job_id}/{stem}"
    host_out_dir = settings.wham_data_dir / "output" / "pose3d" / job_id / stem

    # Create output directory
    host_out_dir.mkdir(parents=True, exist_ok=True)

    # Check if preprocessing artifacts exist; if not, extract them first
    if not _has_preprocessing_artifacts(str(host_out_dir)):
        print(f"[pose3d] Preprocessing artifacts missing, extracting 2D data first...")
        extract_2d_cmd = _build_extract_2d_cmd(
            source_name=src["stored_filename"],
            output_dir=out_dir,
            gpu_id=gpu_id,
        )

        proc = subprocess.run(
            extract_2d_cmd,
            check=False,
            capture_output=True,
            text=True,
            cwd=str(settings.repo_dir),
        )
        if proc.returncode != 0:
            msg = (proc.stderr or proc.stdout or "2D extraction failed").strip()
            raise RuntimeError(f"Failed to extract 2D preprocessing artifacts: {msg}")

        print(f"[pose3d] 2D preprocessing artifacts extracted successfully")

    # Run 3D pose inference
    print(f"[pose3d] Running 3D pose inference...")
    extract_3d_cmd = _build_extract_3d_cmd(
        source_name=src["stored_filename"],
        output_dir=out_dir,
        gpu_id=gpu_id,
        visualize=False,
        save_pkl=True,
        run_smplify=False,
    )

    proc = subprocess.run(
        extract_3d_cmd,
        check=False,
        capture_output=True,
        text=True,
        cwd=str(settings.repo_dir),
    )
    if proc.returncode != 0:
        msg = (proc.stderr or proc.stdout or "3D pose inference failed").strip()
        raise RuntimeError(f"pose3d inference failed: {msg}")

    print(f"[pose3d] 3D pose inference completed successfully")

    _save_job(
        payload=payload,
        job_id=job_id,
        job_name=job_name,
        result_id=result_id,
        source_name=src["stored_filename"],
        gpu_id=gpu_id,
        visualize=False,
        save_pkl=True,
        run_smplify=False,
    )

    return PoseJobAcceptedResponse(
        job_id=job_id,
        job_name=job_name,
        transform_type=TransformType.pose3d,
        source_video_id=payload.source_video_id,
        result_video_id=result_id,
        status=JobStatus.running,
    )