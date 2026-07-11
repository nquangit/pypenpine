"""SessionManager: session lifecycle + gated send with auth retry."""

from __future__ import annotations

import asyncio
import threading

from penpine.auth.gate import RefreshGate
from penpine.transport.engine import Engine


def _default_auth_failure(response) -> bool:
    return response.status_code in (401, 403)


class SessionManager:
    def __init__(
        self,
        provider,
        scheme,
        *,
        auth_engine=None,
        send_engine=None,
        expiry_skew=30.0,
        auth_failure=None,
    ):
        self._provider = provider
        self._scheme = scheme
        self._auth_engine = auth_engine if auth_engine is not None else Engine()
        self._send_engine = send_engine if send_engine is not None else self._auth_engine
        self._skew = expiry_skew
        self._auth_failure = auth_failure or _default_auth_failure
        self._session = None
        self._gate = RefreshGate()
        self._loop = None
        self._loop_thread = None
        self._loop_lock = threading.Lock()

    @property
    def session(self):
        return self._session

    def is_auth_failure(self, response) -> bool:
        return self._auth_failure(response)

    def apply(self, request):
        return self._scheme.apply(request, self._session)

    def invalidate(self) -> None:
        self._session = None

    async def ensure_fresh(self) -> None:
        if self._session is None or self._session.is_expired(self._skew):
            await self.refresh_now()

    async def refresh_now(self, *, force=False) -> None:
        async with self._gate.exclusive():
            if self._session is None:
                self._session = await self._provider.login(self._auth_engine)
            elif force or self._session.is_expired(self._skew):
                self._session = await self._provider.refresh(self._auth_engine, self._session)

    async def send(self, request, *, max_auth_retries=1):
        resp = None
        for attempt in range(max_auth_retries + 1):
            await self.ensure_fresh()
            async with self._gate.access():
                req = self.apply(request)
                resp = await self._send_engine.send(req)
            if attempt < max_auth_retries and self.is_auth_failure(resp):
                self.invalidate()
                continue
            return resp
        return resp

    async def send_many(self, requests, *, return_exceptions=False):
        return await asyncio.gather(
            *(self.send(r) for r in requests), return_exceptions=return_exceptions
        )

    def _ensure_loop(self):
        with self._loop_lock:
            if self._loop is None:
                self._loop = asyncio.new_event_loop()
                self._loop_thread = threading.Thread(target=self._loop.run_forever, daemon=True)
                self._loop_thread.start()

    def send_sync(self, request, **kwargs):
        self._ensure_loop()
        return asyncio.run_coroutine_threadsafe(self.send(request, **kwargs), self._loop).result()

    def send_many_sync(self, requests, **kwargs):
        self._ensure_loop()
        return asyncio.run_coroutine_threadsafe(
            self.send_many(requests, **kwargs), self._loop
        ).result()

    def close(self):
        if self._loop is not None:
            self._loop.call_soon_threadsafe(self._loop.stop)
            self._loop_thread.join(timeout=2)
            self._loop.close()
            self._loop = None
            self._loop_thread = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
