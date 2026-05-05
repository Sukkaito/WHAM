import os
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

# Load environment variables from .env file in service root directory
env_file = Path(__file__).parent.parent.parent / ".env"
if env_file.exists():
    load_dotenv(env_file, override=True)  # override=False keeps existing env vars


class Settings:
    """Runtime settings for WHAM API service filesystem paths.
    
    Values are loaded from environment variables (set via .env file or OS environment).
    Defaults point to the standard development workspace layout.
    """

    @staticmethod
    def _parse_utc_hhmm_to_minutes(raw_value: str, env_name: str) -> int:
        value = raw_value.strip()
        parts = value.split(":")
        if len(parts) != 2:
            raise ValueError(f"{env_name} must be in HH:MM format (UTC), got: {raw_value}")

        try:
            hour = int(parts[0])
            minute = int(parts[1])
        except ValueError as exc:
            raise ValueError(f"{env_name} must contain numeric HH:MM values (UTC), got: {raw_value}") from exc

        if hour < 0 or hour > 23 or minute < 0 or minute > 59:
            raise ValueError(f"{env_name} must be a valid UTC time between 00:00 and 23:59, got: {raw_value}")

        return hour * 60 + minute

    def __init__(self) -> None:
        data_root = os.getenv("WHAM_DATA_DIR", "/mnt/e/Code/IT4788/WHAM/WHAM_data")
        repo_root = os.getenv("WHAM_REPO_DIR", "/mnt/e/Code/IT4788/WHAM/WHAM")
        self.wham_data_dir = Path(data_root)
        self.repo_dir = Path(repo_root)
        self.database_url = os.getenv("WHAM_DATABASE_URL")
        self.execution_backend = os.getenv("WHAM_EXECUTION_BACKEND", "docker").strip().lower()
        self.videos_dir = self.wham_data_dir / "videos"
        self.video_index_file = self.videos_dir / ".video_index.json"
        self.docker_image = os.getenv("WHAM_DOCKER_IMAGE", "wham-local")
        # Separate GPU ID configuration for Docker vs Runpod backends
        self.default_gpu_id = os.getenv("WHAM_GPU_ID", "0")
        self.docker_gpu_id = os.getenv("WHAM_DOCKER_GPU_ID", os.getenv("WHAM_GPU_ID", "0"))
        self.runpod_gpu_id = os.getenv("WHAM_RUNPOD_GPU_ID", "")
        self.job_worker_count = int(os.getenv("WHAM_JOB_WORKER_COUNT", "1"))
        launch_start_utc = os.getenv("WHAM_JOB_LAUNCH_UTC_START", "").strip()
        launch_end_utc = os.getenv("WHAM_JOB_LAUNCH_UTC_END", "").strip()
        if bool(launch_start_utc) != bool(launch_end_utc):
            raise ValueError(
                "WHAM_JOB_LAUNCH_UTC_START and WHAM_JOB_LAUNCH_UTC_END must both be set or both be empty"
            )
        self.job_launch_window_enabled = bool(launch_start_utc and launch_end_utc)
        self.job_launch_utc_start = launch_start_utc or None
        self.job_launch_utc_end = launch_end_utc or None
        self.job_launch_utc_start_minutes = (
            self._parse_utc_hhmm_to_minutes(launch_start_utc, "WHAM_JOB_LAUNCH_UTC_START")
            if self.job_launch_window_enabled
            else None
        )
        self.job_launch_utc_end_minutes = (
            self._parse_utc_hhmm_to_minutes(launch_end_utc, "WHAM_JOB_LAUNCH_UTC_END")
            if self.job_launch_window_enabled
            else None
        )
        self.auth_subject_header = os.getenv("WHAM_AUTH_SUBJECT_HEADER", "X-WHAM-Subject")
        self.auth_api_key_header = os.getenv("WHAM_AUTH_API_KEY_HEADER", "X-WHAM-Api-Key")
        self.bootstrap_api_keys = os.getenv("WHAM_BOOTSTRAP_API_KEYS", "")
        self.bootstrap_api_keys_file = os.getenv("WHAM_BOOTSTRAP_API_KEYS_FILE", "")
        self.runpod_api_key = os.getenv("RUNPOD_API_KEY", "")
        self.runpod_template_id = os.getenv("WHAM_RUNPOD_TEMPLATE_ID", "")
        self.runpod_image = os.getenv("WHAM_RUNPOD_IMAGE", self.docker_image)
        self.runpod_network_volume_id = os.getenv("WHAM_RUNPOD_NETWORK_VOLUME_ID", "")
        self.runpod_volume_mount_path = os.getenv("WHAM_RUNPOD_VOLUME_MOUNT_PATH", "/code")
        self.runpod_poll_interval_seconds = int(os.getenv("WHAM_RUNPOD_POLL_INTERVAL_SECONDS", "10"))
        self.runpod_job_timeout_seconds = int(os.getenv("WHAM_RUNPOD_JOB_TIMEOUT_SECONDS", "7200"))
        self.runpod_delete_on_completion = os.getenv("WHAM_RUNPOD_DELETE_ON_COMPLETION", "true").lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        self.pose2d_visualize = os.getenv("WHAM_POSE2D_VISUALIZE", "true").lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        self.pose2d_estimate_local_only = os.getenv(
            "WHAM_POSE2D_ESTIMATE_LOCAL_ONLY",
            "false",
        ).lower() in {"1", "true", "yes", "on"}
        self.pose3d_visualize = os.getenv("WHAM_POSE3D_VISUALIZE", "true").lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        self.pose3d_estimate_local_only = os.getenv(
            "WHAM_POSE3D_ESTIMATE_LOCAL_ONLY",
            "false",
        ).lower() in {"1", "true", "yes", "on"}
        self.pose3d_save_pkl = os.getenv("WHAM_POSE3D_SAVE_PKL", "true").lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        self.pose3d_run_smplify = os.getenv("WHAM_POSE3D_RUN_SMPLIFY", "false").lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        self.docker_cleanup_enabled = os.getenv("WHAM_DOCKER_CLEANUP_ENABLED", "true").lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        self.requeue_jobs_on_startup = os.getenv("WHAM_REQUEUE_JOBS_ON_STARTUP", "true").lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        self.log_dir = Path(os.getenv("WHAM_LOG_DIR", str(self.wham_data_dir / "logs")))
        self.log_file_name = os.getenv("WHAM_LOG_FILE_NAME", "wham_api_service.log")
        self.log_file_path = self.log_dir / self.log_file_name
        self.log_max_bytes = int(os.getenv("WHAM_LOG_MAX_BYTES", "10485760"))
        self.log_backup_count = int(os.getenv("WHAM_LOG_BACKUP_COUNT", "5"))
        self.allowed_video_extensions = {
            ".mp4",
            ".mov",
            ".avi",
            ".mkv",
            ".webm",
            ".m4v",
        }
        self.cancel_jobs_on_startup = os.getenv("WHAM_CANCEL_JOBS_ON_STARTUP", "false").lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        
        # Log configuration at startup
        env_source = ".env file" if env_file.exists() else "defaults + OS environment"
        print(f"[WHAM API Settings] Loaded from {env_source}")
        print(f"  Data dir:     {self.wham_data_dir}")
        print(f"  Repo dir:     {self.repo_dir}")
        print(f"  Execution backend: {self.execution_backend}")
        print(f"  Docker image: {self.docker_image}")
        print(f"  GPU ID:       {self.default_gpu_id}")
        print(f"  Job workers:  {self.job_worker_count}")
        if self.job_launch_window_enabled:
            print(
                "  Job launch UTC window: "
                f"{self.job_launch_utc_start}-{self.job_launch_utc_end}"
            )
        else:
            print("  Job launch UTC window: disabled (always allow)")
        print(f"  Auth subject header: {self.auth_subject_header}")
        print(f"  Auth api-key header: {self.auth_api_key_header}")
        print(f"  Docker cleanup enabled: {self.docker_cleanup_enabled}")
        print(f"  Requeue jobs on startup: {self.requeue_jobs_on_startup}")
        print(f"  Runpod image: {self.runpod_image}")
        print(f"  Runpod template: {self.runpod_template_id or '<unset>'}")
        print(f"  Runpod volume: {self.runpod_network_volume_id or '<unset>'}")
        print(f"  Log file:     {self.log_file_path}")
        print(f"  Database URL: {self.database_url or '<unset>'}")

    def is_job_launch_time_allowed_utc(self, now_utc: datetime | None = None) -> bool:
        if not self.job_launch_window_enabled:
            return True

        if now_utc is None:
            now_utc = datetime.now(timezone.utc)

        minute_of_day = now_utc.hour * 60 + now_utc.minute
        start = self.job_launch_utc_start_minutes
        end = self.job_launch_utc_end_minutes

        if start is None or end is None:
            return True

        # Same start/end means allow full day.
        if start == end:
            return True

        if start < end:
            return start <= minute_of_day < end

        # Overnight window, e.g., 22:00-06:00.
        return minute_of_day >= start or minute_of_day < end

    def seconds_until_next_job_launch_window_utc(self, now_utc: datetime | None = None) -> int:
        if not self.job_launch_window_enabled:
            return 0

        if now_utc is None:
            now_utc = datetime.now(timezone.utc)

        if self.is_job_launch_time_allowed_utc(now_utc):
            return 0

        start = self.job_launch_utc_start_minutes
        end = self.job_launch_utc_end_minutes
        if start is None or end is None:
            return 0

        minute_of_day = now_utc.hour * 60 + now_utc.minute
        second_of_minute = now_utc.second
        current_seconds = minute_of_day * 60 + second_of_minute
        start_seconds = start * 60

        if minute_of_day < start:
            return max(start_seconds - current_seconds, 1)

        # If we are after today's start, next allowed time is tomorrow at start.
        full_day_seconds = 24 * 60 * 60
        return max((full_day_seconds - current_seconds) + start_seconds, 1)


settings = Settings()
