"""Logging that never crashes the editor when the disk is not writable."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

from .paths import app_data_dir


def configure_logging(level: int = logging.INFO) -> logging.Logger:
    logger = logging.getLogger("reasonable")
    if logger.handlers:
        return logger
    logger.setLevel(level)
    formatter = logging.Formatter("%(asctime)s  %(levelname)-7s  %(name)s  %(message)s")
    try:
        log_dir = app_data_dir() / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        handler: logging.Handler = RotatingFileHandler(
            log_dir / "engine.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8"
        )
    except OSError:
        handler = logging.StreamHandler()
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    return logger
