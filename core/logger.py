"""Unified logger for the `arbitrage` package.

This module exposes a module-level `logger` object and helper functions
so other modules can import a ready-to-use logger:

    from arbitrage.core.logger import logger

The logger is configured with a console handler and a rotating file handler.
"""
from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler
from typing import Optional

_PACKAGE_NAME = "arbitrage"

# Directory for logs (placed next to this file)
_BASE_DIR = os.path.dirname(__file__)
_LOG_DIR = os.path.join(_BASE_DIR, "logs")
os.makedirs(_LOG_DIR, exist_ok=True)

_LOG_FILE = os.path.join(_LOG_DIR, "arbitrage.log")


def _build_logger(name: Optional[str] = None) -> logging.Logger:
    name = name or _PACKAGE_NAME
    logger = logging.getLogger(name)

    # Avoid adding duplicate handlers if module is reloaded
    if logger.handlers:
        return logger

    logger.setLevel(logging.INFO)

    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    sh = logging.StreamHandler()
    sh.setFormatter(fmt)

    fh = RotatingFileHandler(_LOG_FILE, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8")
    fh.setFormatter(fmt)

    logger.addHandler(sh)
    logger.addHandler(fh)

    # Do not propagate to root handlers to avoid duplicate messages
    logger.propagate = False

    return logger


# Module-level default logger for the whole package
logger: logging.Logger = _build_logger()


def get_logger(name: Optional[str] = None) -> logging.Logger:
    """Return a child or named logger based on package logger configuration.

    If `name` is None returns the package-level `logger`.
    """
    if not name:
        return logger
    return _build_logger(name)


def set_level(level: int | str) -> None:
    """Set logging level for the package logger and its handlers.

    `level` may be an int (e.g., `logging.DEBUG`) or a string (e.g., "DEBUG").
    """
    if isinstance(level, str):
        level = logging._nameToLevel.get(level.upper(), logging.INFO)

    logger.setLevel(level)
    for h in logger.handlers:
        h.setLevel(level)


__all__ = ["logger", "get_logger", "set_level"]
