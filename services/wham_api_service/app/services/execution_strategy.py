from __future__ import annotations

import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, NamedTuple

from app.core.settings import settings
from app.models.schemas import JobStatus as ApiJobStatus
from .docker_executor import (
    execute_docker_detached,
    execute_docker_blocking,
    inspect_container,
    remove_container,
    wait_for_container,
)
from .runpod_executor import create_runpod_pod, delete_runpod_pod, fetch_runpod_pod_logs, get_runpod_pod_status


class ExecutionLaunchResult(NamedTuple):
    success: bool
    identifier: str | None
    stdout: str
    stderr: str
    returncode: int
    metadata_updates: dict[str, Any]


class ExecutionInspectionResult(NamedTuple):
    state: str
    exit_code: int | None
    error_summary: str | None
    stdout: str
    stderr: str


class ExecutionCompletionResult(NamedTuple):
    status_value: ApiJobStatus
    exit_code: int | None
    error_summary: str | None


class ExecutionStrategy(ABC):
    backend_name: str

    @abstractmethod
    def launch(self, job_id: str, runtime_params: dict[str, Any]) -> ExecutionLaunchResult:
        raise NotImplementedError

    @abstractmethod
    def inspect(self, identifier: str, runtime_params: dict[str, Any]) -> ExecutionInspectionResult:
        raise NotImplementedError

    @abstractmethod
    def wait_for_completion(self, job_id: str, identifier: str, runtime_params: dict[str, Any]) -> ExecutionCompletionResult:
        raise NotImplementedError

    @abstractmethod
    def terminate(self, identifier: str, runtime_params: dict[str, Any]) -> ExecutionInspectionResult:
        raise NotImplementedError

    @abstractmethod
    def cleanup(self, identifier: str | None) -> None:
        raise NotImplementedError


def _normalize_runpod_state(text: str) -> str:
    lowered = text.lower()
    if any(token in lowered for token in ("running", "queued", "pending", "starting")):
        return "running"
    if any(token in lowered for token in ("succeeded", "completed", "complete", "finished", "exit code 0")):
        return "succeeded"
    if any(token in lowered for token in ("failed", "error", "terminated", "exit code 1")):
        return "failed"
    if "not found" in lowered or "missing" in lowered:
        return "missing"
    return "unknown"


def _normalize_docker_state(text: str) -> str:
    payload = text.strip().split()
    if len(payload) >= 2 and payload[0].lower() not in {"running", "created", "paused"}:
        try:
            exit_code = int(payload[1])
        except Exception:
            exit_code = None
        if exit_code == 0:
            return "succeeded"
        return "failed"
    if payload and payload[0].lower() in {"running", "created", "paused"}:
        return "running"
    return "unknown"


class DockerExecutionStrategy(ExecutionStrategy):
    backend_name = "docker"

    def launch(self, job_id: str, runtime_params: dict[str, Any]) -> ExecutionLaunchResult:
        docker_cmd = runtime_params.get("docker_cmd") if isinstance(runtime_params, dict) else None
        if not isinstance(docker_cmd, list) or not docker_cmd:
            return ExecutionLaunchResult(False, None, "", "Missing docker command for queued job", 1, {})

        result = execute_docker_detached(docker_cmd, cwd=settings.repo_dir)
        identifier = runtime_params.get("container_name")
        metadata_updates = {"execution_backend": self.backend_name}
        if identifier:
            metadata_updates["container_name"] = identifier
        return ExecutionLaunchResult(
            success=result.success,
            identifier=identifier,
            stdout=result.stdout,
            stderr=result.stderr,
            returncode=result.returncode,
            metadata_updates=metadata_updates,
        )

    def inspect(self, identifier: str, runtime_params: dict[str, Any]) -> ExecutionInspectionResult:
        inspect_result = inspect_container(identifier)
        if not inspect_result.success:
            return ExecutionInspectionResult(
                state="missing",
                exit_code=None,
                error_summary=(inspect_result.stderr or inspect_result.stdout or "Container not found").strip(),
                stdout=inspect_result.stdout,
                stderr=inspect_result.stderr,
            )

        payload = inspect_result.stdout.strip().split()
        if len(payload) >= 2 and payload[0].lower() not in {"running", "created", "paused"}:
            try:
                exit_code = int(payload[1])
            except Exception:
                exit_code = None
            state = "succeeded" if exit_code == 0 else "failed"
            error_summary = None if state == "succeeded" else f"Docker container {identifier} exited with status {payload[0].lower()}"
            return ExecutionInspectionResult(state=state, exit_code=exit_code, error_summary=error_summary, stdout=inspect_result.stdout, stderr=inspect_result.stderr)

        return ExecutionInspectionResult(state="running", exit_code=None, error_summary=None, stdout=inspect_result.stdout, stderr=inspect_result.stderr)

    def wait_for_completion(self, job_id: str, identifier: str, runtime_params: dict[str, Any]) -> ExecutionCompletionResult:
        wait_result = wait_for_container(identifier)
        if not wait_result.success:
            return ExecutionCompletionResult(
                status_value=ApiJobStatus.failed,
                exit_code=None,
                error_summary=(wait_result.stderr or wait_result.stdout or "Docker wait failed").strip(),
            )

        try:
            exit_code = int(wait_result.stdout.strip().splitlines()[-1])
        except Exception:
            exit_code = None

        if exit_code == 0:
            return ExecutionCompletionResult(status_value=ApiJobStatus.succeeded, exit_code=exit_code, error_summary=None)

        logs_result = execute_docker_blocking(["docker", "logs", "--tail", "200", identifier], cwd=settings.repo_dir)
        error_summary = (logs_result.stderr or logs_result.stdout or "Docker container failed").strip()
        return ExecutionCompletionResult(status_value=ApiJobStatus.failed, exit_code=exit_code, error_summary=error_summary)

    def terminate(self, identifier: str, runtime_params: dict[str, Any]) -> ExecutionInspectionResult:
        remove_result = remove_container(identifier)
        if remove_result.success:
            return ExecutionInspectionResult(
                state="failed",
                exit_code=137,
                error_summary="Job cancelled by user request",
                stdout=remove_result.stdout,
                stderr=remove_result.stderr,
            )

        error_summary = (remove_result.stderr or remove_result.stdout or f"Failed to terminate Docker container {identifier}").strip()
        return ExecutionInspectionResult(
            state="missing" if "No such container" in error_summary else "running",
            exit_code=remove_result.returncode,
            error_summary=error_summary,
            stdout=remove_result.stdout,
            stderr=remove_result.stderr,
        )

    def cleanup(self, identifier: str | None) -> None:
        if not identifier or not settings.docker_cleanup_enabled:
            return
        remove_container(identifier)


class RunpodExecutionStrategy(ExecutionStrategy):
    backend_name = "runpod"

    def launch(self, job_id: str, runtime_params: dict[str, Any]) -> ExecutionLaunchResult:
        runpod_entrypoint = runtime_params.get("runpod_entrypoint") if isinstance(runtime_params, dict) else None
        if not isinstance(runpod_entrypoint, list) or not runpod_entrypoint:
            return ExecutionLaunchResult(False, None, "", "Missing runpod entrypoint for queued job", 1, {})

        pod_name = runtime_params.get("pod_name") or runtime_params.get("container_name") or f"wham-{job_id}"
        
        # Use Runpod-specific GPU ID if configured, otherwise use default
        gpu_id_for_pod = settings.runpod_gpu_id or settings.default_gpu_id
        
        pod_env = {
            "WHAM_JOB_ID": job_id,
            "WHAM_EXECUTION_BACKEND": self.backend_name,
            "WHAM_DATA_DIR": str(settings.wham_data_dir),
            "WHAM_OUTPUT_DIR": runtime_params.get("output_dir", ""),
            "WHAM_SOURCE_FILENAME": runtime_params.get("source_filename", ""),
        }
        result = create_runpod_pod(
            pod_name=pod_name,
            image=settings.runpod_image,
            gpu_id=str(gpu_id_for_pod),
            entrypoint_cmd=runpod_entrypoint,
            template_id=settings.runpod_template_id or None,
            network_volume_id=settings.runpod_network_volume_id or None,
            volume_mount_path=settings.runpod_volume_mount_path or None,
            env={key: value for key, value in pod_env.items() if value},
            cwd=settings.repo_dir,
        )
        metadata_updates = {
            "pod_id": result.pod_id,
            "pod_name": pod_name,
            "container_name": pod_name,
            "execution_backend": self.backend_name,
        }
        return ExecutionLaunchResult(
            success=result.success,
            identifier=result.pod_id,
            stdout=result.stdout,
            stderr=result.stderr,
            returncode=result.returncode,
            metadata_updates=metadata_updates,
        )

    def inspect(self, identifier: str, runtime_params: dict[str, Any]) -> ExecutionInspectionResult:
        status_result = get_runpod_pod_status(identifier, cwd=settings.repo_dir)
        status_text = f"{status_result.stdout}\n{status_result.stderr}".strip()
        normalized_state = _normalize_runpod_state(status_text)
        if normalized_state == "running" or normalized_state == "unknown":
            return ExecutionInspectionResult(state="running", exit_code=None, error_summary=None, stdout=status_result.stdout, stderr=status_result.stderr)
        if normalized_state == "succeeded":
            return ExecutionInspectionResult(state="succeeded", exit_code=0, error_summary=None, stdout=status_result.stdout, stderr=status_result.stderr)
        if normalized_state == "missing":
            return ExecutionInspectionResult(
                state="missing",
                exit_code=None,
                error_summary=(status_result.stderr or status_result.stdout or f"Runpod pod {identifier} not found").strip(),
                stdout=status_result.stdout,
                stderr=status_result.stderr,
            )
        return ExecutionInspectionResult(
            state="failed",
            exit_code=status_result.returncode,
            error_summary=(status_result.stderr or status_result.stdout or f"Runpod pod {identifier} failed").strip(),
            stdout=status_result.stdout,
            stderr=status_result.stderr,
        )

    def wait_for_completion(self, job_id: str, identifier: str, runtime_params: dict[str, Any]) -> ExecutionCompletionResult:
        """Poll for pod completion by checking a marker file in mounted volume.
        
        The entrypoint script writes a marker file to the mounted volume after
        execution completes. We poll for this file to detect completion since
        runpodctl provides no direct stdout/stderr or job completion signal.
        """
        deadline = time.monotonic() + settings.runpod_job_timeout_seconds
        marker_path = Path(settings.wham_data_dir) / f".wham_job_{job_id}_complete"

        while time.monotonic() < deadline:
            # Check if completion marker exists
            if marker_path.exists():
                try:
                    exit_code_text = marker_path.read_text().strip()
                    exit_code = int(exit_code_text.split()[0])
                except Exception as e:
                    return ExecutionCompletionResult(
                        status_value=ApiJobStatus.failed,
                        exit_code=None,
                        error_summary=f"Failed to read completion marker: {e}",
                    )
                
                if exit_code == 0:
                    return ExecutionCompletionResult(status_value=ApiJobStatus.succeeded, exit_code=0, error_summary=None)
                
                return ExecutionCompletionResult(
                    status_value=ApiJobStatus.failed,
                    exit_code=exit_code,
                    error_summary=f"Job {job_id} exited with code {exit_code}",
                )
            
            time.sleep(max(settings.runpod_poll_interval_seconds, 1))

        return ExecutionCompletionResult(
            status_value=ApiJobStatus.failed,
            exit_code=None,
            error_summary=f"Job {job_id} exceeded timeout ({settings.runpod_job_timeout_seconds}s) waiting for completion marker",
        )

    def terminate(self, identifier: str, runtime_params: dict[str, Any]) -> ExecutionInspectionResult:
        delete_result = delete_runpod_pod(identifier)
        if delete_result.success:
            return ExecutionInspectionResult(
                state="failed",
                exit_code=137,
                error_summary="Job cancelled by user request",
                stdout=delete_result.stdout,
                stderr=delete_result.stderr,
            )

        error_summary = (delete_result.stderr or delete_result.stdout or f"Failed to terminate Runpod pod {identifier}").strip()
        lowered = error_summary.lower()
        if "not found" in lowered or "missing" in lowered:
            state = "missing"
        else:
            state = "running"
        return ExecutionInspectionResult(
            state=state,
            exit_code=delete_result.returncode,
            error_summary=error_summary,
            stdout=delete_result.stdout,
            stderr=delete_result.stderr,
        )

    def cleanup(self, identifier: str | None) -> None:
        if not identifier or not settings.runpod_delete_on_completion:
            return
        delete_runpod_pod(identifier)


def get_execution_strategy(backend: str | None = None) -> ExecutionStrategy:
    normalized = (backend or settings.execution_backend or "docker").strip().lower()
    if normalized == "runpod":
        return RunpodExecutionStrategy()
    return DockerExecutionStrategy()