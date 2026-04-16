from __future__ import annotations

"""
Docker execution helpers for WHAM jobs.

This module intentionally stays small and Docker-specific. Higher-level pose
command construction lives in `pose_command_builder.py`.
"""

import subprocess
from pathlib import Path
from typing import NamedTuple

from app.core.settings import settings


class DockerExecResult(NamedTuple):
    returncode: int
    stdout: str
    stderr: str
    success: bool


def _get_docker_base_args(
    gpu_id: str,
    container_name: str = "",
    remove_on_exit: bool = True,
) -> list[str]:
    args = [
        "docker",
        "run",
        "--platform",
        "linux/amd64",
        "--gpus",
        f"device={gpu_id}",
        "-e",
        f"CUDA_VISIBLE_DEVICES={gpu_id}",
        "-e",
        "PYTHONUNBUFFERED=1",
        "-e",
        "CUDA_LAUNCH_BLOCKING=1",
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

    if remove_on_exit:
        args.insert(2, "--rm")

    if container_name:
        args.extend(["--name", container_name])

    return args


def wait_for_container(container_name: str) -> DockerExecResult:
    return execute_docker_blocking(["docker", "wait", container_name], cwd=settings.repo_dir)


def inspect_container(container_name: str) -> DockerExecResult:
    return execute_docker_blocking(
        ["docker", "inspect", "--format", "{{.State.Status}} {{.State.ExitCode}}", container_name],
        cwd=settings.repo_dir,
    )


def remove_container(container_name: str) -> DockerExecResult:
    return execute_docker_blocking(["docker", "rm", "-f", container_name], cwd=settings.repo_dir)


def execute_docker_blocking(
    cmd: list[str],
    cwd: Path | str = None,
) -> DockerExecResult:
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
    if cwd is None:
        cwd = settings.repo_dir

    detached_cmd = list(cmd)
    if "--detach" not in detached_cmd:
        try:
            run_idx = detached_cmd.index("run")
            detached_cmd.insert(run_idx + 1, "--detach")
        except ValueError:
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