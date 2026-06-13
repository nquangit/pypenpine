"""Capture: write extracted response values into a Context."""
from __future__ import annotations

from penpine.data.extract import extract_value, run_extractors
from penpine.logging import get_logger
from penpine.transport.interceptor import Interceptor

log = get_logger(__name__)


def capture(context, response, specs) -> dict:
    """Strict: a missing required value raises ExtractError."""
    captured = run_extractors(response, specs)
    context.update(captured)
    return captured


class CaptureInterceptor(Interceptor):
    """Best-effort auto-capture on every response (L1 seam)."""

    def __init__(self, context, specs):
        self._context = context
        self._specs = list(specs)

    async def before_send(self, request):
        return request

    async def after_receive(self, request, response):
        for spec in self._specs:
            try:
                value = extract_value(response, spec)
            except Exception as exc:
                log.warning("auto-capture for key %r failed: %s", spec.key, exc)
                continue
            self._context.set(spec.key, value)
        return response
