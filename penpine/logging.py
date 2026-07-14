"""Shared logging for penpine. No side effects at import time."""

from __future__ import annotations

import logging

from rich.logging import RichHandler
from rich.text import Text

from penpine.render import console as _console

_ROOT_NAME = "penpine"


class _PlainFormatter(logging.Formatter):
    """Strip rich markup from markup-opted records so log files stay plain text."""

    def format(self, record: logging.LogRecord) -> str:
        s = super().format(record)
        if getattr(record, "markup", False):
            try:
                return Text.from_markup(s).plain
            except Exception:
                return s
        return s


def get_logger(name: str) -> logging.Logger:
    """Return a namespaced logger. Does not attach handlers."""
    return logging.getLogger(name)


def configure_logging(
    level: int | str = logging.INFO, *, log_file: str | None = None
) -> logging.Logger:
    """Attach a rich console handler (and optionally a plain file handler) to the
    penpine root logger. `level` may be an int or a level-name string.
    Idempotent: repeat calls do not duplicate handlers."""
    log = logging.getLogger(_ROOT_NAME)
    log.setLevel(level)
    log.propagate = False

    if not any(getattr(h, "_penpine_console", False) for h in log.handlers):
        handler = RichHandler(console=_console, markup=False, rich_tracebacks=True, show_path=False)
        handler._penpine_console = True  # type: ignore[attr-defined]
        handler.setFormatter(logging.Formatter("%(name)s: %(message)s"))
        handler.addFilter(lambda record: not getattr(record, "_penpine_request", False))
        log.addHandler(handler)

    if log_file is not None:
        target = str(log_file)
        if not any(getattr(h, "_penpine_file", None) == target for h in log.handlers):
            file_handler = logging.FileHandler(target)
            file_handler._penpine_file = target  # type: ignore[attr-defined]
            file_handler.setFormatter(_PlainFormatter("%(levelname)s %(name)s: %(message)s"))
            log.addHandler(file_handler)

    return log
