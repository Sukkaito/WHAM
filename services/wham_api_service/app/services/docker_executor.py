"""
Shared Docker execution utilities for WHAM pose extraction and inference.

Provides deterministic Docker command builders and executors for:
- 2D pose extraction (extract_2d_poses.py)
- 2D overlay rendering via extract_2d_poses.py --visualize
- 3D pose inference (extract_3d_poses.py)
"""

import subprocess
from pathlib import Path
from typing import NamedTuple

from app.core.settings import settings


class DockerExecResult(NamedTuple):
    """Result of a Docker execution."""
    returncode: int
    stdout: str
    stderr: str
    success: bool


def _get_docker_base_args(gpu_id: str, container_name: str = "") -> list[str]:
    """
    Build common Docker run arguments for WHAM jobs.
    
    Args:
        gpu_id: GPU device ID (e.g., "0", "1")
        container_name: Optional container name
    
    Returns:
        List of base docker run arguments before image/command
    """
    args = [
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
    ]
    
    if container_name:
        args.extend(["--name", container_name])
    
    return args


def build_extract_2d_cmd(
    source_name: str,
    output_dir: str,
    gpu_id: str,
) -> list[str]:
    """
    Build docker command to extract 2D preprocessing artifacts.
    
    Generates tracking_results.pth (2D pose data) and slam_results.pth (camera trajectory).
    
    Args:
        source_name: Video filename in /videos (e.g., "vid_abc123__input.mov")
        output_dir: Output directory path within container (e.g., "output/pose2d/job_123/input")
        gpu_id: GPU device ID
    
    Returns:
        List of docker run command args
    """
    cmd = _get_docker_base_args(gpu_id)
    cmd.extend([
        settings.docker_image,
        "bash",
        "-lc",
        f"python3 scripts/extract_2d_poses.py --video /videos/{source_name} --output_dir {output_dir} --device cuda:0",
    ])
    return cmd


def build_extract_3d_cmd(
    source_name: str,
    output_dir: str,
    gpu_id: str,
    visualize: bool = False,
    save_pkl: bool = True,
    run_smplify: bool = False,
) -> list[str]:
    """
    Build docker command to run WHAM 3D pose inference on preprocessing artifacts.
    
    Expects tracking_results.pth and slam_results.pth to exist in output_dir.
    
    Args:
        source_name: Video filename in /videos
        output_dir: Output directory path within container (must contain .pth artifacts)
        gpu_id: GPU device ID
        visualize: Whether to render 3D visualization
        save_pkl: Whether to save wham_output.pkl
        run_smplify: Whether to run post-optimization
    
    Returns:
        List of docker run command args
    """
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

    cmd = _get_docker_base_args(gpu_id)
    cmd.extend([
        settings.docker_image,
        "bash",
        "-lc",
        inner,
    ])
    return cmd


def execute_docker_blocking(
    cmd: list[str],
    cwd: Path | str = None,
) -> DockerExecResult:
    """
    Execute a docker command synchronously and wait for completion.
    
    Args:
        cmd: Docker command as list of args
        cwd: Working directory for subprocess
    
    Returns:
        DockerExecResult with exit code and captured output
    """
    if cwd is None:
        cwd = settings.repo_dir
    
    proc = subprocess.run(
        cmd,
        check=False,
        capture_output=True,
        text=True,
        cwd=str(cwd),
    )
    
    return DockerExecResult(
        returncode=proc.returncode,
        stdout=proc.stdout,
        stderr=proc.stderr,
        success=(proc.returncode == 0),
    )


def execute_docker_detached(
    cmd: list[str],
    cwd: Path | str = None,
) -> DockerExecResult:
    """
    Launch a docker command in detached mode (--name required in cmd).
    
    Captures only the launch attempt, not job output.
    
    Args:
        cmd: Docker command as list of args (must include --name)
        cwd: Working directory for subprocess
    
    Returns:
        DockerExecResult reflecting launch success only (exit 0 means container started)
    """
    if cwd is None:
        cwd = settings.repo_dir

    detached_cmd = list(cmd)
    if "--detach" not in detached_cmd:
        try:
            run_idx = detached_cmd.index("run")
            detached_cmd.insert(run_idx + 1, "--detach")
        except ValueError:
            # Fallback: keep original command shape if it is not a docker-run command.
            pass
    
    proc = subprocess.run(
        detached_cmd,
        check=False,
        capture_output=True,
        text=True,
        cwd=str(cwd),
    )
    
    return DockerExecResult(
        returncode=proc.returncode,
        stdout=proc.stdout,
        stderr=proc.stderr,
        success=(proc.returncode == 0),
    )


def build_pose2d_pipeline_cmd(
    source_name: str,
    job_id: str,
    result_name: str,
    gpu_id: str,
) -> list[str]:
    """
    Build docker command for complete pose2d pipeline (extract + optional overlay render).

    Uses extract_2d_poses.py to both generate artifacts and render overlay via --visualize.
    
    Args:
        source_name: Video filename in /videos
        job_id: Job ID for output directory structure
        result_name: Output video filename (e.g., "vid_xyz.mp4")
        gpu_id: GPU device ID
    
    Returns:
        List of docker run command args
    """
    stem = Path(source_name).stem
    out_base = f"output/pose2d/{job_id}"
    track_dir = f"{out_base}/{stem}"
    out_mp4 = f"{track_dir}/{result_name}"

    inner = (
        f"mkdir -p {track_dir} && "
        f"python3 scripts/extract_2d_poses.py --video /videos/{source_name} --output_dir {track_dir} --device cuda:0 --visualize --overlay_out {out_mp4}"
    )

    cmd = _get_docker_base_args(gpu_id, container_name=f"wham-pose2d-{job_id}")
    cmd.extend([
        settings.docker_image,
        "bash",
        "-lc",
        inner,
    ])
    return cmd


def build_pose3d_pipeline_cmd(
    source_name: str,
    job_id: str,
    output_dir: str,
    gpu_id: str,
    visualize: bool = True,
    save_pkl: bool = True,
    run_smplify: bool = False,
) -> list[str]:
    """
    Build detached pose3d pipeline command with ordered preprocessing then 3D inference.

    Order is guaranteed within one container run:
    1) Ensure output directory exists
    2) Generate preprocessing artifacts if missing (tracking_results/slam_results)
    3) Run 3D extraction and optional visualization
    """
    track_pth = f"{output_dir}/tracking_results.pth"
    slam_pth = f"{output_dir}/slam_results.pth"

    infer_parts = [
        "python3 scripts/extract_3d_poses.py",
        f"--video /videos/{source_name}",
        f"--output_dir {output_dir}",
        "--device cuda:0",
    ]
    if visualize:
        infer_parts.append("--visualize")
    if save_pkl:
        infer_parts.append("--save_pkl")
    if run_smplify:
        infer_parts.append("--run_smplify")

    infer_cmd = " ".join(infer_parts)
    inner = (
        f"mkdir -p {output_dir} && "
        f"if [ ! -f {track_pth} ] || [ ! -f {slam_pth} ]; then "
        f"python3 scripts/extract_2d_poses.py --video /videos/{source_name} --output_dir {output_dir} --device cuda:0; "
        f"fi && "
        f"{infer_cmd}"
    )

    cmd = _get_docker_base_args(gpu_id, container_name=f"wham-pose3d-{job_id}")
    cmd.extend([
        settings.docker_image,
        "bash",
        "-lc",
        inner,
    ])
    return cmd
