"""Interceptor seam. L2 supplies concrete implementations."""

from __future__ import annotations

import contextvars
import logging
import time

from penpine.logging import get_logger

_request_start: contextvars.ContextVar[float] = contextvars.ContextVar("penpine_request_start")


class Interceptor:
    async def before_send(self, request):
        return request

    async def after_receive(self, request, response):
        return response


class RetrySignal(Exception):
    """Raised by an interceptor's after_receive to request a retry of send()."""


class RequestLogInterceptor(Interceptor):
    """Log one line per request/response, e.g. `GET /path -> 200 (12 ms)`."""

    def __init__(self, *, level: int = logging.INFO, logger_name: str = "penpine.transport"):
        self._level = level
        self._log = get_logger(logger_name)

    async def before_send(self, request):
        _request_start.set(time.perf_counter())
        return request

    async def after_receive(self, request, response):
        try:
            elapsed_ms = (time.perf_counter() - _request_start.get()) * 1000
            timing = f" ({elapsed_ms:.0f} ms)"
        except LookupError:
            timing = ""
        status = getattr(response, "status_code", "?")
        self._log.log(self._level, "%s %s -> %s%s", request.method, request.target, status, timing)
        return response
