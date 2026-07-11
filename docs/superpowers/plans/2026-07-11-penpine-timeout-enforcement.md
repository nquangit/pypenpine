# L1 Read/Total Timeout Enforcement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enforce the `read` (whole-response deadline) and `total` (whole-send ceiling) transport timeouts that are defined but currently unenforced, raising `ReadTimeout`/`TotalTimeout`.

**Architecture:** Add a `TransportTimeout` exception base + `TotalTimeout`, reparent `ReadTimeout`; wrap `Connection.read_response` in `asyncio.wait_for(read)`; rename `Engine.send`'s body to `_send` and wrap it in `asyncio.wait_for(total)`. No signature changes; `Timeouts` already carries the fields.

**Tech Stack:** stdlib `asyncio`. No new dependencies. Python 3.11+.

**Spec:** `docs/superpowers/specs/2026-07-11-penpine-timeout-enforcement-design.md`

## Global Constraints

- Commit WITHOUT GPG signing: `git -c commit.gpgsign=false commit -m "..."` (`-c` BEFORE `commit`).
- Gates LIVE: before each commit run `ruff check <files> && ruff format <files>` (line-length 100; ruleset E,F,W,I,UP,B,C4,SIM) and `python -m pytest`.
- No new runtime dependencies.
- `asyncio.TimeoutError` is `TimeoutError` in Python 3.11+; catch `TimeoutError`.
- Do NOT run `git add -A`; stage only the files named per task. Leave `.superpowers/` alone.
- Baseline suite is `371 passed, 1 skipped`; new tests add to it, nothing regresses.

Verified existing facts:
- `Timeouts(connect=10.0, read=30.0, total=None)` (`transport/timeouts.py`).
- `ResponseReader.read(stream, request_method=…)` blocks on `stream.read(4096)`.
- `ByteStream` ABC + `FakeByteStream` live in `penpine/transport/stream.py`; `ByteStream` methods: `read(n)`, `readexactly(n)`, `readline()`, `write(data)`, `drain()`, `start_tls(ctx, host)`, `close()`, `closed` (property).
- `Connection(host, port, *, use_tls=False, tls=None, proxy=None, timeouts=None, stream_opener=None)`; `Connection.open()` does `self._stream = await self._opener(host, port, self.timeouts)`; `read_response` calls `ResponseReader.read(self._stream, request_method=method)`.
- `Engine(*, tls=None, proxy=None, interceptors=(), timeouts=None, max_concurrency=10, max_retries=0, connection_factory=Connection)`; `engine.py` already imports `asyncio` and `from penpine.transport.exceptions import TransportError` (plus `RetrySignal`). `Engine.send` currently contains the whole send logic.
- `transport/exceptions.py` currently: `TransportError`, `ConnectError`, `TLSError`, `ProxyError`, `ReadTimeout(TransportError)`, `IncompleteResponseError`.
- `transport/__init__.py` imports exceptions in a block and lists them in `__all__`.
- `parse_response(bytes)` from `penpine.core.parse.http_parser` (for test doubles).

---

### Task 1: Exception model — `TransportTimeout` + `TotalTimeout`, reparent `ReadTimeout`

**Files:**
- Modify: `penpine/transport/exceptions.py`
- Modify: `penpine/transport/__init__.py` (re-export the two new names)
- Test: `tests/transport/test_timeout_exceptions.py`

**Interfaces:**
- Produces: `TransportTimeout(TransportError)`, `TotalTimeout(TransportTimeout)`, and `ReadTimeout(TransportTimeout)`. Tasks 2–3 raise `ReadTimeout`/`TotalTimeout`.

- [ ] **Step 1: Write the failing test** — `tests/transport/test_timeout_exceptions.py`:
```python
def test_timeout_hierarchy():
    from penpine.transport.exceptions import (
        ReadTimeout,
        TotalTimeout,
        TransportError,
        TransportTimeout,
    )

    assert issubclass(TransportTimeout, TransportError)
    assert issubclass(ReadTimeout, TransportTimeout)
    assert issubclass(TotalTimeout, TransportTimeout)
    assert issubclass(ReadTimeout, TransportError)  # still broadly catchable


def test_reexported_from_transport_package():
    from penpine.transport import TotalTimeout, TransportTimeout
    from penpine.transport.exceptions import TotalTimeout as E_TotalTimeout

    assert TotalTimeout is E_TotalTimeout
    assert TransportTimeout is not None
```

- [ ] **Step 2: Run to confirm fail** — `python -m pytest tests/transport/test_timeout_exceptions.py -v` → `ImportError` (`TransportTimeout`/`TotalTimeout` don't exist).

- [ ] **Step 3a: Edit `penpine/transport/exceptions.py`.** Replace the existing `ReadTimeout` class and add the base + `TotalTimeout`. The `ReadTimeout` block currently is:
```python
class ReadTimeout(TransportError):
    """A read exceeded its timeout."""
```
Replace it with:
```python
class TransportTimeout(TransportError):
    """Base class for transport timeouts."""


class ReadTimeout(TransportTimeout):
    """A read exceeded its timeout."""


class TotalTimeout(TransportTimeout):
    """A send exceeded its total timeout."""
```
(Placement: keep it where `ReadTimeout` was, after `ProxyError`. `IncompleteResponseError` stays as-is.)

- [ ] **Step 3b: Edit `penpine/transport/__init__.py`.** Add `TotalTimeout` and `TransportTimeout` to the exceptions import block and to `__all__`. The import block becomes:
```python
from penpine.transport.exceptions import (
    ConnectError,
    IncompleteResponseError,
    ProxyError,
    ReadTimeout,
    TLSError,
    TotalTimeout,
    TransportError,
    TransportTimeout,
)
```
And add `"TransportTimeout",` and `"TotalTimeout",` to the `__all__` list (next to the existing `"ReadTimeout",`).

- [ ] **Step 4: Run to confirm pass** — `python -m pytest tests/transport/test_timeout_exceptions.py -v` → both pass.

- [ ] **Step 5: Lint, format, commit.**
```bash
ruff check penpine/transport/exceptions.py penpine/transport/__init__.py tests/transport/test_timeout_exceptions.py && ruff format penpine/transport/exceptions.py penpine/transport/__init__.py tests/transport/test_timeout_exceptions.py
git add penpine/transport/exceptions.py penpine/transport/__init__.py tests/transport/test_timeout_exceptions.py
git -c commit.gpgsign=false commit -m "feat(transport): add TransportTimeout base and TotalTimeout; reparent ReadTimeout"
```

---

### Task 2: Read enforcement in `Connection.read_response`

**Files:**
- Modify: `penpine/transport/connection.py`
- Test: `tests/transport/test_read_timeout.py`

**Interfaces:**
- Consumes: `ReadTimeout` (Task 1).
- Produces: `Connection.read_response` raises `ReadTimeout` when `timeouts.read` elapses.

- [ ] **Step 1: Write the failing test** — `tests/transport/test_read_timeout.py`:
```python
import asyncio

import pytest

from penpine.transport.connection import Connection
from penpine.transport.exceptions import ReadTimeout
from penpine.transport.stream import ByteStream
from penpine.transport.timeouts import Timeouts


class _HangingStream(ByteStream):
    async def read(self, n=-1):
        await asyncio.sleep(10)
        return b""

    async def close(self):
        return None

    @property
    def closed(self):
        return False


class _CompleteStream(ByteStream):
    def __init__(self, data):
        self._data = data
        self._sent = False

    async def read(self, n=-1):
        if self._sent:
            return b""
        self._sent = True
        return self._data

    async def close(self):
        return None

    @property
    def closed(self):
        return False


async def test_read_timeout_raises():
    hanging = _HangingStream()

    async def _open(host, port, timeouts):
        return hanging

    conn = Connection("h", 80, timeouts=Timeouts(read=0.05), stream_opener=_open)
    await conn.open()
    with pytest.raises(ReadTimeout):
        await conn.read_response("GET")


async def test_read_timeout_disabled_completes():
    raw = b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nhi"
    stream = _CompleteStream(raw)

    async def _open(host, port, timeouts):
        return stream

    conn = Connection("h", 80, timeouts=Timeouts(read=None), stream_opener=_open)
    await conn.open()
    resp = await conn.read_response("GET")
    assert resp.status_code == 200
    assert resp.body.raw == b"hi"
```

- [ ] **Step 2: Run to confirm fail** — `python -m pytest tests/transport/test_read_timeout.py -v` → `test_read_timeout_raises` FAILS (it hangs then fails, or errors) because `read_response` has no timeout. (If it truly hangs, that itself confirms the gap; add the implementation next.)

- [ ] **Step 3: Edit `penpine/transport/connection.py`.** Add `import asyncio` at the top (after `from __future__ import annotations`) and import `ReadTimeout`. The imports become:
```python
from __future__ import annotations

import asyncio

from penpine.transport.exceptions import ReadTimeout
from penpine.transport.reader import ResponseReader
from penpine.transport.stream import open_asyncio_stream
from penpine.transport.timeouts import Timeouts
from penpine.transport.tls import TLSConfig
```
Replace the `read_response` method:
```python
    async def read_response(self, method: str = "GET"):
        coro = ResponseReader.read(self._stream, request_method=method)
        if self.timeouts.read:
            try:
                return await asyncio.wait_for(coro, self.timeouts.read)
            except TimeoutError as exc:
                raise ReadTimeout(f"read timed out after {self.timeouts.read}s") from exc
        return await coro
```

- [ ] **Step 4: Run to confirm pass** — `python -m pytest tests/transport/test_read_timeout.py -v` → both pass (the hanging test now raises `ReadTimeout` in ~0.05s).

- [ ] **Step 5: Lint, format, commit.**
```bash
ruff check penpine/transport/connection.py tests/transport/test_read_timeout.py && ruff format penpine/transport/connection.py tests/transport/test_read_timeout.py
git add penpine/transport/connection.py tests/transport/test_read_timeout.py
git -c commit.gpgsign=false commit -m "feat(transport): enforce read timeout in Connection.read_response"
```

---

### Task 3: Total enforcement in `Engine.send`

**Files:**
- Modify: `penpine/transport/engine.py`
- Test: `tests/transport/test_total_timeout.py`

**Interfaces:**
- Consumes: `TotalTimeout` (Task 1).
- Produces: `Engine.send` raises `TotalTimeout` when `timeouts.total` elapses; behavior otherwise unchanged.

- [ ] **Step 1: Write the failing test** — `tests/transport/test_total_timeout.py`:
```python
import asyncio

import pytest

from penpine.core.message import Request
from penpine.core.parse.http_parser import parse_response
from penpine.transport.engine import Engine
from penpine.transport.exceptions import TotalTimeout
from penpine.transport.timeouts import Timeouts


class _SlowConn:
    def __init__(self, host, port, **kwargs):
        self.host = host
        self.port = port

    async def open(self):
        await asyncio.sleep(10)
        return self

    async def send_bytes(self, data):
        return None

    async def read_response(self, method="GET"):
        return parse_response(b"HTTP/1.1 200 OK\r\nContent-Length: 0\r\n\r\n")

    async def close(self):
        return None


class _FastConn:
    def __init__(self, host, port, **kwargs):
        self.host = host
        self.port = port

    async def open(self):
        return self

    async def send_bytes(self, data):
        return None

    async def read_response(self, method="GET"):
        return parse_response(b"HTTP/1.1 200 OK\r\nContent-Length: 0\r\n\r\n")

    async def close(self):
        return None


async def test_total_timeout_raises():
    engine = Engine(
        connection_factory=_SlowConn,
        timeouts=Timeouts(connect=None, read=None, total=0.05),
    )
    with pytest.raises(TotalTimeout):
        await engine.send(Request.from_url("http://h/"))


async def test_total_timeout_disabled_completes():
    engine = Engine(
        connection_factory=_FastConn,
        timeouts=Timeouts(connect=None, read=None, total=None),
    )
    resp = await engine.send(Request.from_url("http://h/"))
    assert resp.status_code == 200
```

- [ ] **Step 2: Run to confirm fail** — `python -m pytest tests/transport/test_total_timeout.py -v` → `test_total_timeout_raises` fails (no total enforcement; hangs on the 10s sleep and the test has no timeout guard — so it will hang until you implement; implement next).

- [ ] **Step 3: Edit `penpine/transport/engine.py`.**
  1. Add `TotalTimeout` to the exceptions import — change `from penpine.transport.exceptions import TransportError` to:
```python
from penpine.transport.exceptions import TotalTimeout, TransportError
```
  2. Rename the existing `async def send(self, request):` method to `async def _send(self, request):` — keep its entire body EXACTLY as is (the meta check, retry loop, interceptors, `return`).
  3. Add a new `send` wrapper immediately ABOVE `_send`:
```python
    async def send(self, request):
        if self.timeouts.total:
            try:
                return await asyncio.wait_for(self._send(request), self.timeouts.total)
            except TimeoutError as exc:
                raise TotalTimeout(
                    f"send exceeded total timeout of {self.timeouts.total}s"
                ) from exc
        return await self._send(request)
```
(`asyncio` is already imported in `engine.py`. Do not change `send_sync`/`send_many`/`send_many_sync` — they call `send`.)

- [ ] **Step 4: Run to confirm pass** — `python -m pytest tests/transport/test_total_timeout.py -v` → both pass (`test_total_timeout_raises` raises in ~0.05s).

- [ ] **Step 5: Full suite + gates, then commit.**
```bash
python -m pytest -q          # expect 371 baseline + new timeout tests, 1 skipped, no regressions
ruff check . && ruff format --check .
git add penpine/transport/engine.py tests/transport/test_total_timeout.py
git -c commit.gpgsign=false commit -m "feat(transport): enforce total timeout in Engine.send"
```

---

### Final verification (after all tasks)

- [ ] `ruff check . && ruff format --check . && python -m pytest -q` → gates clean; suite green (371 baseline + 6 new timeout tests, 1 skipped).
- [ ] Confirm the read default now bites without breaking anything: the full transport suite passes (fast fakes never approach 30s).

---

## Self-Review

**Spec coverage:**
- §3 exception model (TransportTimeout base, TotalTimeout, ReadTimeout reparent, re-exports) → Task 1 + tests. ✓
- §4 read enforcement (wait_for(read) in read_response, None disables) → Task 2 + `test_read_timeout_raises`/`test_read_timeout_disabled_completes`. ✓
- §5 total enforcement (send→_send rename + wait_for(total) wrapper, None disables, send_sync/many untouched) → Task 3 + `test_total_timeout_raises`/`test_total_timeout_disabled_completes`. ✓
- §6 behavior change (read=30 default now applies) → covered by the full-suite regression check (fast fakes stay green). ✓
- §7 testing strategy → Tasks 1–3 tests. ✓

**Placeholder scan:** No TBD/TODO; every code step is complete. The Task 3 rename step describes the mechanical rename precisely (change the `def` line, keep the body verbatim) rather than repeating ~35 unchanged lines — the body is not modified. ✓

**Type/name consistency:** `TransportTimeout`/`TotalTimeout`/`ReadTimeout` defined in Task 1 are imported and raised in Tasks 2–3. `Connection(..., stream_opener=_open, timeouts=Timeouts(...))` and `Engine(connection_factory=…, timeouts=Timeouts(...))` match the verified constructor signatures. Test doubles implement the `ByteStream`/connection methods the code calls (`read`, `open`, `send_bytes`, `read_response`, `close`). `asyncio.wait_for`/`TimeoutError` usage matches Python 3.11+. ✓
