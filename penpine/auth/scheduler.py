"""RefreshScheduler: periodic / ahead-of-expiry gated session refresh."""
from __future__ import annotations

import asyncio
import time

from penpine.logging import get_logger

log = get_logger(__name__)


class RefreshScheduler:
    def __init__(self, manager, *, every=None, before_expiry=30.0):
        self._manager = manager
        self._every = every
        self._before_expiry = before_expiry
        self._task = None

    def _next_tick(self) -> tuple[float, bool]:
        """Return (delay_seconds, should_refresh). should_refresh is False when
        there is nothing to schedule (no `every` and no session expiry) — the
        scheduler then idles instead of refreshing."""
        if self._every is not None:
            return self._every, True
        session = self._manager.session
        if session is not None and session.expires_at is not None:
            return max(0.0, session.expires_at - self._before_expiry - time.time()), True
        return 1.0, False

    async def _run(self):
        while True:
            delay, should_refresh = self._next_tick()
            await asyncio.sleep(delay)
            if not should_refresh:
                continue
            try:
                await self._manager.refresh_now(force=True)
            except Exception as exc:
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
