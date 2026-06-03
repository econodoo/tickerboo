"""
Logging configuration for TickerBoo.

Call `setup_logging()` once at startup (in main.py lifespan).

Strategy:
  - stdout  → always on (uvicorn + systemd journal picks it up)
  - file    → rotating, 10 MB × 10 files, survives restarts

Log levels are set per environment via TICKERBOO_LOG_LEVEL.
External noisy libraries are quieted to WARNING.
"""
from __future__ import annotations

import logging
import logging.handlers
import sys
from pathlib import Path


def setup_logging(log_path: Path, log_level: str = "DEBUG") -> None:
    level = getattr(logging, log_level.upper(), logging.DEBUG)

    fmt = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    root = logging.getLogger()
    root.setLevel(level)

    # ── Stdout handler ───────────────────────────────────────────────────
    sh = logging.StreamHandler(sys.stdout)
    sh.setLevel(level)
    sh.setFormatter(fmt)
    root.addHandler(sh)

    # ── Rotating file handler ────────────────────────────────────────────
    log_path.parent.mkdir(parents=True, exist_ok=True)
    fh = logging.handlers.RotatingFileHandler(
        filename=log_path,
        maxBytes=10 * 1024 * 1024,   # 10 MB
        backupCount=10,
        encoding="utf-8",
    )
    fh.setLevel(level)
    fh.setFormatter(fmt)
    root.addHandler(fh)

    # ── Quiet noisy third-party loggers ──────────────────────────────────
    for noisy in ("httpx", "httpcore", "urllib3", "multipart"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    logging.getLogger("tickerboo").info(
        "Logging initialised — level=%s file=%s", log_level, log_path
    )
