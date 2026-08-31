"""Structured logging setup (structlog over stdlib logging).

Every log record is emitted as JSON to a rotating file under the user data
directory, and as a human-readable line to the console. UI log tailing reads
the SQLite `upload_logs`/`event_logs` tables (see db layer), not this file —
this is for developer/ops diagnostics, not the in-app Logs view.
"""

from __future__ import annotations

import logging
import logging.handlers
import sys
from pathlib import Path

import structlog


def configure_logging(data_dir: Path, level: str = "INFO") -> None:
    log_dir = data_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "instacore_sync.log"

    file_handler = logging.handlers.RotatingFileHandler(
        log_file, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    console_handler = logging.StreamHandler(sys.stdout)

    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(message)s",
        handlers=[file_handler, console_handler],
        force=True,
    )

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, level.upper(), logging.INFO)
        ),
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)
