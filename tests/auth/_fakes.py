"""Async engine stub for auth tests (no sockets)."""

import asyncio

from penpine.core.parse.http_parser import parse_response


class FakeEngine:
    """`script` is a list of raw response bytes, or callables taking the request
    and returning raw bytes. The last entry repeats once exhausted."""

    def __init__(self, script):
        self._script = list(script)
        self._i = 0
        self.sent = []

    async def send(self, request):
        self.sent.append(request)
        idx = min(self._i, len(self._script) - 1)
        self._i += 1
        item = self._script[idx]
        raw = item(request) if callable(item) else item
        return parse_response(raw)

    async def send_many(self, requests, *, return_exceptions=False):
        return await asyncio.gather(
            *(self.send(r) for r in requests), return_exceptions=return_exceptions
        )
