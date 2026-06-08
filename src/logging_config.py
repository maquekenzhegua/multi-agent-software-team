from __future__ import annotations

import logging
import os
import sys
from pathlib import Path


LOG_FORMAT = "%(asctime)s [%(levelname)-5s] %(name)s | %(message)s"
LOG_DATE_FMT = "%H:%M:%S"


def setup_logging(level: str = "INFO", log_file: str = "",
                  verbose: bool = False) -> logging.Logger:
    root = logging.getLogger("agent_team")
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    if root.handlers:
        return root

    console = logging.StreamHandler(sys.stderr)
    console.setLevel(logging.DEBUG if verbose else logging.INFO)
    console.setFormatter(logging.Formatter(LOG_FORMAT, LOG_DATE_FMT))
    root.addHandler(console)

    if log_file:
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(logging.Formatter(LOG_FORMAT, LOG_DATE_FMT))
        root.addHandler(file_handler)

    return root


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"agent_team.{name}")


logger = get_logger("core")
