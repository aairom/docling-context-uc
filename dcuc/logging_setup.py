"""Centralised logging configuration."""

from __future__ import annotations

import logging
from pathlib import Path

_FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"


def configure_logging(level: str = "INFO", log_file: Path | None = None) -> None:
    """Configure root logging once; safe to call repeatedly (e.g. from tests)."""
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    if log_file is not None:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(log_file, encoding="utf-8"))
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format=_FORMAT,
        handlers=handlers,
        force=True,
    )
    # Third-party libraries are chatty at INFO; keep our own logs readable.
    for noisy in ("httpx", "httpcore", "gradio", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
