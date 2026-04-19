"""Shared script bootstrap helpers."""

from pathlib import Path
import sys
import os


def ensure_repo_root_on_path() -> None:
    """Add repository root to sys.path for direct script execution."""
    root_dir = Path(__file__).resolve().parents[1]
    root_dir_str = str(root_dir)
    if root_dir_str not in sys.path:
        sys.path.insert(0, root_dir_str)

    base = Path(__file__).parent.parent / "third-party" / "ViTPose"
    sys.path.insert(0, str(base))
    #print(dict(os.environ))
    

