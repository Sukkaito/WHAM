from __future__ import annotations

import logging
from typing import Any


_LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"


def setup_logging() -> None:
    logging.basicConfig(level=logging.INFO, format=_LOG_FORMAT)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


def log_event(logger: logging.Logger, event: str, **fields: Any) -> None:
    payload = " ".join(f"{key}={value}" for key, value in fields.items() if value is not None)
    if payload:
        logger.info("%s %s", event, payload)
    else:
        logger.info("%s", event)
