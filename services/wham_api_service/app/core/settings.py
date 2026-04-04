import os
from pathlib import Path

from dotenv import load_dotenv

# Load environment variables from .env file in service root directory
env_file = Path(__file__).parent.parent.parent / ".env"
if env_file.exists():
    load_dotenv(env_file, override=False)  # override=False keeps existing env vars


class Settings:
    """Runtime settings for WHAM API service filesystem paths.
    
    Values are loaded from environment variables (set via .env file or OS environment).
    Defaults point to the standard development workspace layout.
    """

    def __init__(self) -> None:
        data_root = os.getenv("WHAM_DATA_DIR", "/mnt/e/Code/IT4788/WHAM/WHAM_data")
        repo_root = os.getenv("WHAM_REPO_DIR", "/mnt/e/Code/IT4788/WHAM/WHAM")
        self.wham_data_dir = Path(data_root)
        self.repo_dir = Path(repo_root)
        self.database_url = os.getenv("WHAM_DATABASE_URL")
        self.videos_dir = self.wham_data_dir / "videos"
        self.video_index_file = self.videos_dir / ".video_index.json"
        self.docker_image = os.getenv("WHAM_DOCKER_IMAGE", "wham-local")
        self.default_gpu_id = os.getenv("WHAM_GPU_ID", "0")
        self.auth_subject_header = os.getenv("WHAM_AUTH_SUBJECT_HEADER", "X-WHAM-Subject")
        self.auth_api_key_header = os.getenv("WHAM_AUTH_API_KEY_HEADER", "X-WHAM-Api-Key")
        self.bootstrap_api_keys = os.getenv("WHAM_BOOTSTRAP_API_KEYS", "")
        self.bootstrap_api_keys_file = os.getenv("WHAM_BOOTSTRAP_API_KEYS_FILE", "")
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
        self.allowed_video_extensions = {
            ".mp4",
            ".mov",
            ".avi",
            ".mkv",
            ".webm",
            ".m4v",
        }
        
        # Log configuration at startup
        env_source = ".env file" if env_file.exists() else "defaults + OS environment"
        print(f"[WHAM API Settings] Loaded from {env_source}")
        print(f"  Data dir:     {self.wham_data_dir}")
        print(f"  Repo dir:     {self.repo_dir}")
        print(f"  Docker image: {self.docker_image}")
        print(f"  GPU ID:       {self.default_gpu_id}")
        print(f"  Auth subject header: {self.auth_subject_header}")
        print(f"  Auth api-key header: {self.auth_api_key_header}")
        print(f"  Docker cleanup enabled: {self.docker_cleanup_enabled}")
        print(f"  Database URL: {self.database_url or '<unset>'}")


settings = Settings()
