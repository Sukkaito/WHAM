from __future__ import annotations

import logging
import json
import re
import shlex
import subprocess
from pathlib import Path
from typing import NamedTuple, Sequence

from app.core.settings import settings


class RunpodExecResult(NamedTuple):
    returncode: int
    stdout: str
    stderr: str
    success: bool
    pod_id: str | None = None


def _extract_pod_id(text: str) -> str | None:
    stripped = text.strip()
    if not stripped:
        return None

    try:
        payload = json.loads(stripped)
    except Exception:
        payload = None
    if isinstance(payload, dict):
        for key in ("pod_id", "podId", "id"):
            value = payload.get(key)
            if value:
                return str(value)

    for pattern in (
        r"pod[_-]?id[:=]\s*([A-Za-z0-9_-]+)",
        r"\b(pod_[A-Za-z0-9_-]+)\b",
    ):
        match = re.search(pattern, stripped, flags=re.IGNORECASE)
        if match:
            return match.group(1)

    for token in re.split(r"[\s,]+", stripped):
        if token.startswith("pod_") or token.startswith("pod-"):
            return token.strip()

    return None


def _run_runpodctl(args: Sequence[str], cwd: Path | str | None = None) -> RunpodExecResult:
    if cwd is None:
        cwd = settings.repo_dir

    proc = subprocess.run(
        ["runpodctl", *args],
        check=False,
        capture_output=True,
        text=True,
        cwd=str(cwd),
    )
    logging.debug(proc.stderr)
    combined = "\n".join(part for part in (proc.stdout, proc.stderr) if part)
    return RunpodExecResult(
        returncode=proc.returncode,
        stdout=proc.stdout,
        stderr=proc.stderr,
        success=(proc.returncode == 0),
        pod_id=_extract_pod_id(combined),
    )


def build_runpod_pod_create_cmd(
    *,
    pod_name: str,
    image: str,
    gpu_id: str,
    entrypoint_cmd: Sequence[str],
    template_id: str | None = None,
    network_volume_id: str | None = None,
    volume_mount_path: str | None = None,
    env: dict[str, str] | None = None,
) -> list[str]:
    if not pod_name:
        raise ValueError("pod_name is required")
    if not entrypoint_cmd:
        raise ValueError("entrypoint_cmd is required")

    cmd = ["runpodctl", "pod", "create", "--name", pod_name]
    if template_id:
        cmd.extend(["--template-id", template_id])
    else:
        cmd.extend(["--image", image])

    if gpu_id:
        cmd.extend(["--gpu-id", gpu_id])

    if network_volume_id:
        cmd.extend(["--network-volume-id", network_volume_id])
    # if volume_mount_path:
    #     cmd.extend(["--volume-mount-path", volume_mount_path])

    # Build runtime environment for Runpod pod.
    # Note: GPU allocation is handled by runpodctl --gpu-id flag, not by CUDA_VISIBLE_DEVICES.
    # Only include custom env vars passed via the env parameter.
    if len(entrypoint_cmd) == 1:
        run_command = str(entrypoint_cmd[0])
    elif len(entrypoint_cmd) >= 3 and entrypoint_cmd[0] == "bash" and entrypoint_cmd[1] == "-lc":
        run_command = str(entrypoint_cmd[2])
    else:
        run_command = shlex.join(list(entrypoint_cmd))

    runtime_env = {
        "WHAM_RUN_COMMAND": run_command,
    }
    if env:
        runtime_env.update(env)

    # for key, value in runtime_env.items():
    #     cmd.extend(["--env", f"{key}={value}"])
        
    env_payload = json.dumps(runtime_env)
    cmd.extend(["--env", env_payload])

    return cmd


def create_runpod_pod(
    *,
    pod_name: str,
    image: str,
    gpu_id: str,
    entrypoint_cmd: Sequence[str],
    template_id: str | None = None,
    network_volume_id: str | None = None,
    volume_mount_path: str | None = None,
    env: dict[str, str] | None = None,
    cwd: Path | str | None = None,
) -> RunpodExecResult:
    cmd = build_runpod_pod_create_cmd(
        pod_name=pod_name,
        image=image,
        gpu_id=gpu_id,
        entrypoint_cmd=entrypoint_cmd,
        template_id=template_id,
        network_volume_id=network_volume_id,
        volume_mount_path=volume_mount_path,
        env=env,
    )
    logging.debug(f"Executing runpodctl command: {cmd}")
    return _run_runpodctl(cmd[1:], cwd=cwd)


def get_runpod_pod_status(pod_id: str, cwd: Path | str | None = None) -> RunpodExecResult:
    return _run_runpodctl(["pod", "get", pod_id], cwd=cwd)


def fetch_runpod_pod_logs(pod_id: str, cwd: Path | str | None = None) -> RunpodExecResult:
    return _run_runpodctl(["pod", "logs", pod_id], cwd=cwd)


def delete_runpod_pod(pod_id: str, cwd: Path | str | None = None) -> RunpodExecResult:
    return _run_runpodctl(["pod", "delete", pod_id], cwd=cwd)