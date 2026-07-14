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


def configure_logging(
    level: int | str = logging.INFO, *, log_file: str | None = None
) -> logging.Logger:
    """Attach a colored console handler (and optionally a plain file handler) to
    the penpine root logger. `level` may be an int or a level-name string.
    Idempotent: repeat calls do not duplicate handlers."""
    log = logging.getLogger(_ROOT_NAME)
    log.setLevel(level)
    log.propagate = False

    if not any(getattr(h, "_penpine_console", False) for h in log.handlers):
        console = logging.StreamHandler()
        console._penpine_console = True  # type: ignore[attr-defined]
        console.setFormatter(_ColorFormatter("%(levelname)s %(name)s: %(message)s"))
        log.addHandler(console)

    if log_file is not None:
        target = str(log_file)
        if not any(getattr(h, "_penpine_file", None) == target for h in log.handlers):
            file_handler = logging.FileHandler(target)
            file_handler._penpine_file = target  # type: ignore[attr-defined]
            file_handler.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
            log.addHandler(file_handler)

    return log
