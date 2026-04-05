from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

from app.core.settings import settings


_LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"


def setup_logging() -> None:
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    formatter = logging.Formatter(_LOG_FORMAT)

    if not any(isinstance(handler, logging.StreamHandler) and not isinstance(handler, RotatingFileHandler) for handler in root.handlers):
        stream_handler = logging.StreamHandler()
        stream_handler.setLevel(logging.INFO)
        stream_handler.setFormatter(formatter)
        root.addHandler(stream_handler)

    settings.log_dir.mkdir(parents=True, exist_ok=True)
    target_log_path = settings.log_file_path.resolve()
    has_file_handler = any(
        isinstance(handler, RotatingFileHandler)
        and Path(handler.baseFilename).resolve() == target_log_path
        for handler in root.handlers
    )
    if not has_file_handler:
        file_handler = RotatingFileHandler(
            target_log_path,
            maxBytes=settings.log_max_bytes,
            backupCount=settings.log_backup_count,
            encoding="utf-8",
        )
        file_handler.setLevel(logging.INFO)
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


def log_event(logger: logging.Logger, event: str, **fields: Any) -> None:
    payload = " ".join(f"{key}={value}" for key, value in fields.items() if value is not None)
    if payload:
        logger.info("%s %s", event, payload)
    else:
        logger.info("%s", event)
