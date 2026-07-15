"""Interceptor seam. L2 supplies concrete implementations."""

from __future__ import annotations

import contextvars
import logging
import time
from datetime import datetime

from penpine.logging import get_logger
from penpine.render import RequestTableRenderer, _humanize_bytes
from penpine.transport.trace import current_injection

_request_start: contextvars.ContextVar[float] = contextvars.ContextVar("penpine_request_start")
_row_rendered: contextvars.ContextVar[bool] = contextvars.ContextVar("penpine_row_rendered")


def _audit_suffix(injection) -> str:
    """`  locator=value` for the file-audit line, or "" if no injection.
    Newlines in the value are collapsed so a CRLF payload can't forge a log line."""
    if not injection:
        return ""
    value = str(injection.value).replace("\r", " ").replace("\n", " ")
    return f"  {injection.locator}={value}"


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
        _row_rendered.set(False)
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
            ts = datetime.now().strftime("%H:%M:%S")
            injection = current_injection.get()
            self._table.row(
                status=status,
                method=request.method,
                size=size,
                timing=timing,
                url=request.target,
                timestamp=ts,
                injection=injection,
            )
            inj = _audit_suffix(injection)
            self._log.log(
                self._level,
                "%s %s %s%s (%s)",
                status,
                request.method,
                request.target,
                inj,
                timing,
                extra={"_penpine_request": True},
            )
            _row_rendered.set(True)
        return response

    async def on_error(self, request, exc):
        try:
            already = _row_rendered.get()
        except LookupError:
            already = False
        if already:
            return None
        if self._log.isEnabledFor(self._level):
            timing = self._timing()
            summary = f"{type(exc).__name__}: {exc}"
            ts = datetime.now().strftime("%H:%M:%S")
            injection = current_injection.get()
            self._table.row(
                status="ERR",
                method=request.method,
                size="—",
                timing=timing,
                url=f"{request.target}  · {summary}",
                timestamp=ts,
                injection=injection,
                failed=True,
            )
            inj = _audit_suffix(injection)
            self._log.log(
                self._level,
                "ERR %s %s%s (failed: %s)",
                request.method,
                request.target,
                inj,
                summary,
                extra={"_penpine_request": True},
            )
        return None
