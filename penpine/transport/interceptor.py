"""Interceptor seam. L2 supplies concrete implementations."""

from __future__ import annotations

import contextvars
import logging
import time

from rich.markup import escape

from penpine.logging import get_logger
from penpine.render import _humanize_bytes, _status_style

_request_start: contextvars.ContextVar[float] = contextvars.ContextVar("penpine_request_start")


class Interceptor:
    async def before_send(self, request):
        return request

    async def after_receive(self, request, response):
        return response


class RetrySignal(Exception):
    """Raised by an interceptor's after_receive to request a retry of send()."""


class RequestLogInterceptor(Interceptor):
    """Log every request on send and its response on receive, e.g.
    `-> GET /path` then `<- 200 GET /path (12 ms)`.

    Logging the request in `before_send` (not only the response in
    `after_receive`) is deliberate: a send that fails — a refused connection,
    timeout, or TLS error — never reaches `after_receive`, so a response-only
    logger would leave failed or unreachable requests invisible.
    """

    def __init__(self, *, level: int = logging.INFO, logger_name: str = "penpine.transport"):
        self._level = level
        self._log = get_logger(logger_name)

    async def before_send(self, request):
        _request_start.set(time.perf_counter())
        self._log.log(
            self._level,
            "[dim]->[/] %s %s",
            escape(request.method),
            escape(request.target),
            extra={"markup": True},
        )
        return request

    async def after_receive(self, request, response):
        try:
            elapsed_ms = (time.perf_counter() - _request_start.get()) * 1000
            timing = f"{elapsed_ms:.0f} ms"
        except LookupError:
            timing = ""
        status = getattr(response, "status_code", "?")
        size = _humanize_bytes(len(getattr(response, "body", b"") or b""))
        self._log.log(
            self._level,
            "[dim]<-[/] [%s]%s[/] %s %s   %s   %s",
            _status_style(status),
            status,
            escape(request.method),
            escape(request.target),
            size,
            timing,
            extra={"markup": True},
        )
        return response
