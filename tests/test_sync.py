import asyncio
import concurrent.futures
import threading

import pytest

from penpine._sync import run_on_loop, wait_interruptible


class _FakeFuture:
    def __init__(self, script):
        self._script = list(script)
        self._i = 0
        self.cancelled = False

    def result(self, timeout=None):
        item = self._script[min(self._i, len(self._script) - 1)]
        self._i += 1
        if isinstance(item, BaseException):
            raise item
        return item

    def cancel(self):
        self.cancelled = True


def test_wait_interruptible_returns_after_timeouts():
    f = _FakeFuture([concurrent.futures.TimeoutError(), concurrent.futures.TimeoutError(), 42])
    assert wait_interruptible(f, poll=0.01) == 42
    assert f.cancelled is False


def test_wait_interruptible_cancels_and_reraises_on_keyboardinterrupt():
    f = _FakeFuture([KeyboardInterrupt()])
    with pytest.raises(KeyboardInterrupt):
        wait_interruptible(f, poll=0.01)
    assert f.cancelled is True


def test_run_on_loop_returns_result_from_background_loop():
    loop = asyncio.new_event_loop()
    t = threading.Thread(target=loop.run_forever, daemon=True)
    t.start()
    try:

        async def work():
            await asyncio.sleep(0)
            return "ok"

        assert run_on_loop(loop, work(), poll=0.01) == "ok"
    finally:
        loop.call_soon_threadsafe(loop.stop)
        t.join(timeout=2)
        loop.close()
