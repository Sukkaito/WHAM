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
        self.videos_dir = self.wham_data_dir / "videos"
        self.video_index_file = self.videos_dir / ".video_index.json"
        self.docker_image = os.getenv("WHAM_DOCKER_IMAGE", "wham-local")
        self.default_gpu_id = os.getenv("WHAM_GPU_ID", "0")
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


settings = Settings()
