"""RefreshScheduler: periodic / ahead-of-expiry gated session refresh."""
from __future__ import annotations

import asyncio
import time

from penpine.auth.exceptions import AuthError
from penpine.logging import get_logger

log = get_logger(__name__)


class RefreshScheduler:
    def __init__(self, manager, *, every=None, before_expiry=30.0):
        self._manager = manager
        self._every = every
        self._before_expiry = before_expiry
        self._task = None

    def _next_delay(self) -> float:
        delays = []
        if self._every is not None:
            delays.append(self._every)
        session = self._manager.session
        if session is not None and session.expires_at is not None:
            delays.append(max(0.0, session.expires_at - self._before_expiry - time.time()))
        if not delays:
            return self._every if self._every is not None else 1.0
        return max(0.0, min(delays))

    async def _run(self):
        while True:
            await asyncio.sleep(self._next_delay())
            try:
                await self._manager.refresh_now(force=True)
            except AuthError as exc:
                log.warning("scheduled refresh failed: %s", exc)

    async def start(self):
        if self._task is None:
            self._task = asyncio.create_task(self._run())

    async def stop(self):
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
