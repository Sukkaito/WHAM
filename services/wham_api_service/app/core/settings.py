import os
from pathlib import Path


class Settings:
    """Runtime settings for WHAM API service filesystem paths."""

    def __init__(self) -> None:
        data_root = os.getenv("WHAM_DATA_DIR", "/mnt/nvme1n1p1/mydata/WHAM_data")
        repo_root = os.getenv("WHAM_REPO_DIR", "/mnt/nvme1n1p1/mydata/WHAM")
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


settings = Settings()
