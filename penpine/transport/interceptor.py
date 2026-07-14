"""Interceptor seam. L2 supplies concrete implementations."""

from __future__ import annotations

import contextvars
import logging
import time

from penpine.logging import get_logger
from penpine.render import RequestTableRenderer, _humanize_bytes

_request_start: contextvars.ContextVar[float] = contextvars.ContextVar("penpine_request_start")


class Interceptor:
    async def before_send(self, request):
        return request

    async def after_receive(self, request, response):
        return response

    async def on_error(self, request, exc):
        """Called when a send ultimately fails (after retries). Default no-op.
        Must not raise."""
        return None


class RetrySignal(Exception):
    """Raised by an interceptor's after_receive to request a retry of send()."""


class RequestLogInterceptor(Interceptor):
    """Render each request as an aligned table row (STATUS METHOD SIZE TIME URL)
    and, when a log file is configured, write a plain audit line to it.

    A successful request renders in `after_receive`; a failed send renders an
    `ERR` row in `on_error` (a failed send never reaches `after_receive`). No
    output is produced in `before_send`. Rendering and the audit record are both
    gated by the logger's effective level, so LOG_LEVEL still applies."""

    def __init__(self, *, level: int = logging.INFO, logger_name: str = "penpine.transport"):
        self._level = level
        self._log = get_logger(logger_name)
        self._table = RequestTableRenderer()

    async def before_send(self, request):
        _request_start.set(time.perf_counter())
        return request

    def _timing(self) -> str:
        try:
            return f"{(time.perf_counter() - _request_start.get()) * 1000:.0f} ms"
        except LookupError:
            return "—"

    async def after_receive(self, request, response):
        if self._log.isEnabledFor(self._level):
            timing = self._timing()
            status = getattr(response, "status_code", "?")
            size = _humanize_bytes(len(getattr(response, "body", b"") or b""))
            self._table.row(
                status=status,
                method=request.method,
                size=size,
                timing=timing,
                url=request.target,
            )
            self._log.log(
                self._level,
                "%s %s %s (%s)",
                status,
                request.method,
                request.target,
                timing,
                extra={"_penpine_request": True},
            )
        return response

    async def on_error(self, request, exc):
        if self._log.isEnabledFor(self._level):
            timing = self._timing()
            summary = f"{type(exc).__name__}: {exc}"
            self._table.row(
                status="ERR",
                method=request.method,
                size="—",
                timing=timing,
                url=f"{request.target}  · {summary}",
                failed=True,
            )
            self._log.log(
                self._level,
                "ERR %s %s (failed: %s)",
                request.method,
                request.target,
                summary,
                extra={"_penpine_request": True},
            )
        return None
