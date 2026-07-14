"""Interruptible bridge from a sync caller to a background asyncio loop.

`future.result()` on a background-thread loop is an uninterruptible wait, so
KeyboardInterrupt is never delivered until the coroutine finishes. Polling with
a timeout keeps the main thread responsive to signals; on interrupt we cancel
the coroutine on the loop and re-raise.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
from collections.abc import Coroutine
from typing import Any, TypeVar

_T = TypeVar("_T")


def wait_interruptible(future: concurrent.futures.Future[_T], *, poll: float = 0.25) -> _T:
    try:
        while True:
            try:
                return future.result(timeout=poll)
            except concurrent.futures.TimeoutError:
                continue
    except (KeyboardInterrupt, SystemExit):
        future.cancel()
        raise


def run_on_loop(
    loop: asyncio.AbstractEventLoop, coro: Coroutine[Any, Any, _T], *, poll: float = 0.25
) -> _T:
    future = asyncio.run_coroutine_threadsafe(coro, loop)
    return wait_interruptible(future, poll=poll)
