"""Interceptor seam. L2 supplies concrete implementations."""
from __future__ import annotations


class Interceptor:
    async def before_send(self, request):
        return request

    async def after_receive(self, request, response):
        return response


class RetrySignal(Exception):
    """Raised by an interceptor's after_receive to request a retry of send()."""
