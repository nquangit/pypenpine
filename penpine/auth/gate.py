"""RefreshGate: an async barrier coordinating shared sends vs. exclusive refresh.

Correctness is guarded by a single asyncio.Condition: all transitions of the
open-flag and in-flight counter happen under its lock, and waiters re-check
their predicate after every wake.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager


class RefreshGate:
    def __init__(self):
        self._cond = asyncio.Condition()
        self._open = True
        self._in_flight = 0

    @asynccontextmanager
    async def access(self):
        async with self._cond:
            while not self._open:
                await self._cond.wait()
            self._in_flight += 1
        try:
            yield
        finally:
            async with self._cond:
                self._in_flight -= 1
                if self._in_flight == 0:
                    self._cond.notify_all()

    @asynccontextmanager
    async def exclusive(self):
        async with self._cond:
            while not self._open:
                await self._cond.wait()
            self._open = False
            while self._in_flight > 0:
                await self._cond.wait()
        try:
            yield
        finally:
            async with self._cond:
                self._open = True
                self._cond.notify_all()
