from __future__ import annotations

import shlex
from pathlib import Path

from app.core.settings import settings
from app.services.docker_executor import _get_docker_base_args


def to_runpod_entrypoint(shell_command: str) -> list[str]:
    return [shell_command]


def _build_pose2d_shell_command(
    source_name: str,
    output_dir: str,
    estimate_local_only: bool = False,
    calib: str | None = None,
    visualize: bool = True,
    overlay_out: str | None = None,
) -> str:
    source_arg = shlex.quote(f"/videos/{source_name}")
    output_arg = shlex.quote(output_dir)
    parts = [
        "python3 scripts/extract_2d_poses.py",
        f"--video {source_arg}",
        f"--output_dir {output_arg}",
        "--device cuda:0",
    ]
    if estimate_local_only:
        parts.append("--estimate_local_only")
    if calib:
        parts.append(f"--calib {shlex.quote(calib)}")
    if visualize:
        parts.append("--visualize")
    if overlay_out:
        parts.append(f"--overlay_out {shlex.quote(overlay_out)}")
    return " ".join(parts)


def _build_logged_marker_shell_command(main_command: str, job_id: str) -> str:
    marker_path = f'${{WHAM_DATA_DIR}}/.wham_job_{job_id}_complete'
    temp_marker_path = f'${{WHAM_DATA_DIR}}/.wham_job_{job_id}_complete.tmp'
    return (
        f"mkdir -p \"${{WHAM_DATA_DIR}}\" && "
        f"{{ "
        f"  echo '=== WHAM JOB LOG START ==='; "
        f"  echo \"START_TIME: $(date -u +%Y-%m-%dT%H:%M:%SZ)\"; "
        f"  echo \"COMMAND: {shlex.quote(main_command)}\"; "
        f"  {main_command} 2>&1; "
        f"  EXIT_CODE=$?; "
        f"  echo '=== WHAM JOB LOG END ==='; "
        f"  echo \"EXIT_CODE: $EXIT_CODE\"; "
        f"  echo \"END_TIME: $(date -u +%Y-%m-%dT%H:%M:%SZ)\"; "
        f"}} > \"{temp_marker_path}\" && mv \"{temp_marker_path}\" \"{marker_path}\"; "
        f"exit $EXIT_CODE"
    )


def _build_pose3d_shell_command(
    source_name: str,
    output_dir: str,
    estimate_local_only: bool = False,
    visualize: bool = False,
    save_pkl: bool = True,
    run_smplify: bool = False,
    calib: str | None = None,
    result_name: str | None = None,
) -> str:
    source_arg = shlex.quote(f"/videos/{source_name}")
    output_arg = shlex.quote(output_dir)
    cmd_parts = [
        "python3 scripts/extract_3d_poses.py",
        f"--video {source_arg}",
        f"--output_dir {output_arg}",
        "--device cuda:0",
    ]
    if estimate_local_only:
        cmd_parts.append("--estimate_local_only")
    if visualize:
        cmd_parts.append("--visualize")
    if save_pkl:
        cmd_parts.append("--save_pkl")
    if run_smplify:
        cmd_parts.append("--run_smplify")
    if calib:
        cmd_parts.append(f"--calib {shlex.quote(calib)}")

    inner = " ".join(cmd_parts)
    if result_name:
        inner = (
            f"mkdir -p {output_arg} && "
            f"if [ ! -f {shlex.quote(f'{output_dir}/tracking_results.pth')} ] || [ ! -f {shlex.quote(f'{output_dir}/slam_results.pth')} ]; then "
            f"python3 scripts/extract_2d_poses.py --video {source_arg} --output_dir {output_arg} --device cuda:0"
        )
        if estimate_local_only:
            inner += " --estimate_local_only"
        if calib:
            inner += f" --calib {shlex.quote(calib)}"
        inner += "; fi && " + " ".join(cmd_parts)
        inner += (
            f" && if [ -f {shlex.quote(f'{output_dir}/output.mp4')} ]; then "
            f"mv {shlex.quote(f'{output_dir}/output.mp4')} {shlex.quote(f'{output_dir}/{result_name}')}; fi"
        )
    return inner


def build_pose2d_pipeline_spec(
    source_name: str,
    job_id: str,
    result_name: str,
    gpu_id: str,
    estimate_local_only: bool = False,
    calib: str | None = None,
) -> dict[str, list[str] | str]:
    stem = Path(source_name).stem
    out_base = f"output/pose2d/{job_id}"
    track_dir = f"{out_base}/{stem}"
    out_mp4 = f"{track_dir}/{result_name}"

    # Build the main command
    main_command = (
        f"mkdir -p {shlex.quote(track_dir)} && "
        f"{_build_pose2d_shell_command(source_name, track_dir, estimate_local_only=estimate_local_only, calib=calib, visualize=True, overlay_out=out_mp4)}"
    )
    
    # Append marker file writing for job completion detection.
    # WHAM_DATA_DIR is injected per backend and points at a mounted data root.
    shell_command = _build_logged_marker_shell_command(main_command, job_id)
    
    docker_cmd = _get_docker_base_args(gpu_id, container_name=f"wham-pose2d-{job_id}", remove_on_exit=False)
    docker_cmd.extend([
        settings.docker_image,
        "bash",
        "-lc",
        shell_command,
    ])
    return {
        "docker_cmd": docker_cmd,
        "runpod_entrypoint": to_runpod_entrypoint(shell_command),
        "shell_command": shell_command,
        "output_dir": track_dir,
        "result_path": out_mp4,
    }


def build_pose3d_pipeline_spec(
    source_name: str,
    job_id: str,
    output_dir: str,
    gpu_id: str,
    result_name: str,
    estimate_local_only: bool = False,
    visualize: bool = True,
    save_pkl: bool = True,
    run_smplify: bool = False,
    calib: str | None = None,
) -> dict[str, list[str] | str]:
    main_command = _build_pose3d_shell_command(
        source_name=source_name,
        output_dir=output_dir,
        estimate_local_only=estimate_local_only,
        visualize=visualize,
        save_pkl=save_pkl,
        run_smplify=run_smplify,
        calib=calib,
        result_name=result_name,
    )
    
    # Append marker file writing for job completion detection.
    # WHAM_DATA_DIR is injected per backend and points at a mounted data root.
    shell_command = _build_logged_marker_shell_command(main_command, job_id)
    
    docker_cmd = _get_docker_base_args(gpu_id, container_name=f"wham-pose3d-{job_id}", remove_on_exit=False)
    docker_cmd.extend([
        settings.docker_image,
        "bash",
        "-lc",
        shell_command,
    ])
    return {
        "docker_cmd": docker_cmd,
        "runpod_entrypoint": to_runpod_entrypoint(shell_command),
        "shell_command": shell_command,
        "output_dir": output_dir,
    }