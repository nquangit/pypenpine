"""Shared logging for penpine. No side effects at import time."""

from __future__ import annotations

import logging

_ROOT_NAME = "penpine"

_LEVEL_COLORS = {
    logging.DEBUG: "\033[36m",
    logging.INFO: "\033[32m",
    logging.WARNING: "\033[33m",
    logging.ERROR: "\033[31m",
    logging.CRITICAL: "\033[1;31m",
}
_RESET = "\033[0m"


class _ColorFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        color = _LEVEL_COLORS.get(record.levelno, "")
        base = super().format(record)
        return f"{color}{base}{_RESET}" if color else base


def get_logger(name: str) -> logging.Logger:
    """Return a namespaced logger. Does not attach handlers."""
    return logging.getLogger(name)


def configure_logging(level: int = logging.INFO) -> logging.Logger:
    """Attach a single colored console handler to the penpine root logger."""
    log = logging.getLogger(_ROOT_NAME)
    log.setLevel(level)
    log.propagate = False
    if not log.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(_ColorFormatter("%(levelname)s %(name)s: %(message)s"))
        log.addHandler(handler)
    return log
