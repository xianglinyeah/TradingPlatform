"""Standard logging configuration for the adaptor."""
from __future__ import annotations

import logging
import logging.handlers
import os


def setup_logging(log_dir: str, level: str = "INFO") -> None:
    os.makedirs(log_dir, exist_ok=True)
    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    info_handler = logging.handlers.RotatingFileHandler(
        os.path.join(log_dir, "execution-adapters-gm-realtime.log"),
        maxBytes=50 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    info_handler.setFormatter(fmt)

    err_handler = logging.handlers.RotatingFileHandler(
        os.path.join(log_dir, "execution-adapters-gm-error.log"),
        maxBytes=20 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    err_handler.setLevel(logging.ERROR)
    err_handler.setFormatter(fmt)

    console = logging.StreamHandler()
    console.setFormatter(fmt)

    root = logging.getLogger()
    root.setLevel(level)
    # Clear previous handlers (in case setup_logging runs twice in tests)
    for h in list(root.handlers):
        root.removeHandler(h)
    root.addHandler(info_handler)
    root.addHandler(err_handler)
    root.addHandler(console)
