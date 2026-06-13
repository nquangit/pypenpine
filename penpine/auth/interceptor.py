"""AuthInterceptor: lightweight L1-seam auth (apply + reactive 401 retry).

Does NOT provide the in-flight drain barrier (the L1 hooks cannot span the
network call). Use SessionManager.send for the full gated path.
"""
from __future__ import annotations

from penpine.transport.interceptor import Interceptor, RetrySignal


class AuthInterceptor(Interceptor):
    def __init__(self, manager):
        self._manager = manager

    async def before_send(self, request):
        await self._manager.ensure_fresh()
        return self._manager.apply(request)

    async def after_receive(self, request, response):
        if self._manager.is_auth_failure(response):
            self._manager.invalidate()
            raise RetrySignal
        return response
