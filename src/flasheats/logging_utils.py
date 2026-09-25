"""Logging goes to stdout and to a per-run file, so a failed overnight run is diagnosable."""
from __future__ import annotations

import logging
import sys
from pathlib import Path

_FORMAT = "%(asctime)s | %(levelname)-7s | %(name)-22s | %(message)s"


def get_logger(run_id: str, log_dir: Path) -> logging.Logger:
    log_dir.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("flasheats")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    logger.propagate = False

    stream = logging.StreamHandler(sys.stdout)
    stream.setFormatter(logging.Formatter(_FORMAT))
    logger.addHandler(stream)

    file_handler = logging.FileHandler(log_dir / f"{run_id}.log", encoding="utf-8")
    file_handler.setFormatter(logging.Formatter(_FORMAT))
    logger.addHandler(file_handler)

    return logger
