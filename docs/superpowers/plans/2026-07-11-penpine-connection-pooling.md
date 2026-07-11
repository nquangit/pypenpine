# L1 Connection Pooling / Keep-Alive Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add opt-in HTTP/1.1 connection pooling with keep-alive reuse to the transport `Engine`, keyed by `(host, port, use_tls)`, with per-host idle cap + idle-timeout eviction and a guarded retry-once on stale reuse.

**Architecture:** A new `penpine/transport/pool.py` (`PoolConfig`, `_connection_reusable`, `ConnectionPool`) plus `Engine` integration behind a default-off `reuse_connections`/`pool` flag; the existing one-shot send path is unchanged when pooling is off.

**Tech Stack:** stdlib `asyncio`, `collections.deque`, `time`. No new dependencies. Python 3.11+.

**Spec:** `docs/superpowers/specs/2026-07-11-penpine-connection-pooling-design.md`

## Global Constraints

- Commit WITHOUT GPG signing: `git -c commit.gpgsign=false commit -m "..."` (`-c` BEFORE `commit`).
- Gates LIVE: before each commit run `ruff check <files> && ruff format <files>` (line-length 100; ruleset E,F,W,I,UP,B,C4,SIM) and `python -m pytest`.
- Async tests use `asyncio_mode = "auto"` — write `async def test_...` with NO `@pytest.mark.asyncio`.
- No new runtime dependencies. Pooling is OPT-IN; default `reuse_connections=False` keeps the one-shot path byte-for-byte unchanged.
- Do NOT run `git add -A`; stage only the files named per task. Leave `.superpowers/` alone.
- Baseline suite is `377 passed, 1 skipped`; new tests add to it, nothing regresses.

Verified existing facts:
- `Connection(host, port, *, use_tls=False, tls=None, proxy=None, timeouts=None, stream_opener=None)` with `open()`, `send_bytes(data)`, `read_response(method="GET")`, `close()`, `closed` (property).
- `Engine.__init__(*, tls=None, proxy=None, interceptors=(), timeouts=None, max_concurrency=10, max_retries=0, connection_factory=Connection)`; it calls `self._connection_factory(host, port, use_tls=…, tls=…, proxy=…, timeouts=…)`.
- `Response.version` (default `"HTTP/1.1"`), `Response.status_code`, `Response.headers.get(name)` (case-insensitive). Chunked responses keep `Transfer-Encoding: chunked`; `Content-Length` responses keep `Content-Length`.
- `ConnectError`, `IncompleteResponseError` in `penpine/transport/exceptions.py`.
- `parse_response(bytes)` from `penpine.core.parse.http_parser`; `Request.from_url(url)` sets meta.
- `transport/__init__.py` imports and `__all__`-lists the public transport names.

---

### Task 1: `pool.py` — `PoolConfig`, `_connection_reusable`, `ConnectionPool`

**Files:**
- Create: `penpine/transport/pool.py`
- Test: `tests/transport/test_pool.py`

**Interfaces:**
- Produces: `PoolConfig(max_per_host=8, idle_timeout=30.0)`; `_connection_reusable(request, response) -> bool`; `ConnectionPool(connection_factory, *, tls, proxy, timeouts, config=None)` with `async acquire(key, *, force_new=False) -> (conn, reused)`, `async release(key, conn, reusable)`, `async aclose()`. Task 2 (Engine) consumes all three.

- [ ] **Step 1: Write the failing test** — `tests/transport/test_pool.py`:
```python
import time

from penpine.core.message import Request
from penpine.core.parse.http_parser import parse_response
from penpine.transport.pool import ConnectionPool, PoolConfig, _connection_reusable

KEY = ("h", 80, False)


class _PConn:
    def __init__(self):
        self.opened = False
        self._closed = False

    async def open(self):
        self.opened = True
        return self

    async def close(self):
        self._closed = True

    @property
    def closed(self):
        return self._closed


def _factory(created):
    def factory(host, port, **kwargs):
        conn = _PConn()
        created.append(conn)
        return conn

    return factory


def _pool(created, config=None):
    return ConnectionPool(_factory(created), tls=None, proxy=None, timeouts=None, config=config)


def _resp(raw):
    return parse_response(raw)


# --- _connection_reusable ---
def test_reusable_content_length():
    req = Request.from_url("http://h/")
    assert _connection_reusable(req, _resp(b"HTTP/1.1 200 OK\r\nContent-Length: 0\r\n\r\n")) is True


def test_reusable_chunked():
    req = Request.from_url("http://h/")
    raw = b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n0\r\n\r\n"
    assert _connection_reusable(req, _resp(raw)) is True


def test_reusable_bodiless_status():
    req = Request.from_url("http://h/")
    assert _connection_reusable(req, _resp(b"HTTP/1.1 204 No Content\r\n\r\n")) is True


def test_not_reusable_connection_close():
    req = Request.from_url("http://h/")
    raw = b"HTTP/1.1 200 OK\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
    assert _connection_reusable(req, _resp(raw)) is False


def test_not_reusable_eof_framed():
    req = Request.from_url("http://h/")
    assert _connection_reusable(req, _resp(b"HTTP/1.1 200 OK\r\n\r\nbody")) is False


def test_not_reusable_http10_without_keepalive():
    req = Request.from_url("http://h/")
    assert _connection_reusable(req, _resp(b"HTTP/1.0 200 OK\r\nContent-Length: 0\r\n\r\n")) is False


# --- ConnectionPool ---
async def test_acquire_opens_when_empty():
    created = []
    pool = _pool(created)
    conn, reused = await pool.acquire(KEY)
    assert reused is False
    assert conn.opened is True
    assert len(created) == 1


async def test_release_then_acquire_reuses():
    created = []
    pool = _pool(created)
    conn, _ = await pool.acquire(KEY)
    await pool.release(KEY, conn, reusable=True)
    conn2, reused = await pool.acquire(KEY)
    assert conn2 is conn
    assert reused is True
    assert len(created) == 1  # no new open


async def test_release_non_reusable_closes():
    created = []
    pool = _pool(created)
    conn, _ = await pool.acquire(KEY)
    await pool.release(KEY, conn, reusable=False)
    assert conn.closed is True


async def test_release_over_cap_closes_overflow():
    created = []
    pool = _pool(created, PoolConfig(max_per_host=1))
    a, _ = await pool.acquire(KEY)
    b, _ = await pool.acquire(KEY)  # opens a 2nd (idle empty)
    await pool.release(KEY, a, reusable=True)  # parks a
    await pool.release(KEY, b, reusable=True)  # over cap -> closes b
    assert b.closed is True


async def test_acquire_skips_closed_parked():
    created = []
    pool = _pool(created)
    conn, _ = await pool.acquire(KEY)
    await pool.release(KEY, conn, reusable=True)
    conn._closed = True  # simulate server-closed idle socket
    conn2, reused = await pool.acquire(KEY)
    assert reused is False
    assert conn2 is not conn
    assert len(created) == 2


async def test_acquire_evicts_expired():
    created = []
    pool = _pool(created, PoolConfig(idle_timeout=10.0))
    conn, _ = await pool.acquire(KEY)
    await pool.release(KEY, conn, reusable=True)
    # backdate the parked timestamp so it is older than idle_timeout
    dq = pool._idle[KEY]
    parked_conn, _ts = dq[0]
    dq[0] = (parked_conn, time.monotonic() - 100)
    conn2, reused = await pool.acquire(KEY)
    assert reused is False
    assert parked_conn.closed is True  # expired one was closed
    assert conn2 is not parked_conn


async def test_force_new_ignores_idle():
    created = []
    pool = _pool(created)
    conn, _ = await pool.acquire(KEY)
    await pool.release(KEY, conn, reusable=True)
    conn2, reused = await pool.acquire(KEY, force_new=True)
    assert reused is False
    assert conn2 is not conn
    assert conn.closed is False  # parked one left intact


async def test_aclose_closes_all_parked():
    created = []
    pool = _pool(created)
    a, _ = await pool.acquire(KEY)
    await pool.release(KEY, a, reusable=True)
    await pool.aclose()
    assert a.closed is True
```

- [ ] **Step 2: Run to confirm fail** — `python -m pytest tests/transport/test_pool.py -q` → `ModuleNotFoundError: No module named 'penpine.transport.pool'`.

- [ ] **Step 3: Create `penpine/transport/pool.py`:**
```python
"""Opt-in HTTP/1.1 connection pool for the transport Engine."""

from __future__ import annotations

import asyncio
import time
from collections import deque
from dataclasses import dataclass


@dataclass
class PoolConfig:
    max_per_host: int = 8
    idle_timeout: float = 30.0


def _connection_reusable(request, response) -> bool:
    resp_conn = (response.headers.get("Connection") or "").lower()
    req_conn = (request.headers.get("Connection") or "").lower()
    if "close" in resp_conn or "close" in req_conn:
        return False
    if getattr(response, "version", "HTTP/1.1") == "HTTP/1.0" and "keep-alive" not in resp_conn:
        return False
    if response.headers.get("Content-Length") is not None:
        return True
    if "chunked" in (response.headers.get("Transfer-Encoding") or "").lower():
        return True
    if response.status_code in (204, 304) or request.method.upper() == "HEAD":
        return True
    return False


class ConnectionPool:
    def __init__(self, connection_factory, *, tls, proxy, timeouts, config=None):
        self._factory = connection_factory
        self._tls = tls
        self._proxy = proxy
        self._timeouts = timeouts
        self._config = config or PoolConfig()
        self._idle: dict[tuple, deque] = {}
        self._lock = asyncio.Lock()

    async def _open(self, key):
        host, port, use_tls = key
        conn = self._factory(
            host, port, use_tls=use_tls, tls=self._tls, proxy=self._proxy, timeouts=self._timeouts
        )
        await conn.open()
        return conn

    async def acquire(self, key, *, force_new=False):
        if not force_new:
            stale = []
            winner = None
            async with self._lock:
                dq = self._idle.get(key)
                if dq:
                    now = time.monotonic()
                    while dq:
                        conn, released = dq.popleft()
                        expired = bool(self._config.idle_timeout) and (
                            now - released > self._config.idle_timeout
                        )
                        if conn.closed or expired:
                            stale.append(conn)
                            continue
                        winner = conn
                        break
            for conn in stale:
                await conn.close()
            if winner is not None:
                return winner, True
        return await self._open(key), False

    async def release(self, key, conn, reusable):
        if not reusable or conn.closed:
            await conn.close()
            return
        to_close = None
        async with self._lock:
            dq = self._idle.setdefault(key, deque())
            if len(dq) >= self._config.max_per_host:
                to_close = conn
            else:
                dq.append((conn, time.monotonic()))
        if to_close is not None:
            await to_close.close()

    async def aclose(self):
        async with self._lock:
            conns = [conn for dq in self._idle.values() for (conn, _ts) in dq]
            self._idle.clear()
        for conn in conns:
            await conn.close()
```

- [ ] **Step 4: Run to confirm pass** — `python -m pytest tests/transport/test_pool.py -q` → all pass.

- [ ] **Step 5: Lint, format, commit.**
```bash
ruff check penpine/transport/pool.py tests/transport/test_pool.py && ruff format penpine/transport/pool.py tests/transport/test_pool.py
git add penpine/transport/pool.py tests/transport/test_pool.py
git -c commit.gpgsign=false commit -m "feat(transport): add ConnectionPool, PoolConfig, and keep-alive reusability rule"
```

---

### Task 2: Engine integration + `PoolConfig` export

**Files:**
- Modify: `penpine/transport/engine.py`
- Modify: `penpine/transport/__init__.py` (re-export `PoolConfig`)
- Test: `tests/transport/test_engine_pool.py`

**Interfaces:**
- Consumes: `ConnectionPool`, `PoolConfig`, `_connection_reusable` (Task 1); `ConnectError`, `IncompleteResponseError`.
- Produces: `Engine(reuse_connections=False, pool=None)`; `Engine.aclose()`; async context manager; a pooled `_send` path.

- [ ] **Step 1: Write the failing test** — `tests/transport/test_engine_pool.py`:
```python
from penpine.core.message import Request
from penpine.core.parse.http_parser import parse_response
from penpine.transport.engine import Engine
from penpine.transport.exceptions import IncompleteResponseError

_OK = b"HTTP/1.1 200 OK\r\nContent-Length: 0\r\n\r\n"


class _Conn:
    def __init__(self, host, port, response, fail_on_use=None, **kwargs):
        self.host = host
        self.port = port
        self._resp = response
        self._fail_on = fail_on_use
        self._closed = False
        self.uses = 0

    async def open(self):
        return self

    async def send_bytes(self, data):
        return None

    async def read_response(self, method="GET"):
        self.uses += 1
        if self._fail_on is not None and self.uses == self._fail_on:
            raise IncompleteResponseError("server closed idle connection")
        return self._resp

    async def close(self):
        self._closed = True

    @property
    def closed(self):
        return self._closed


def _counting_factory(response, first_fail_on_use=None):
    created = []

    def factory(host, port, **kwargs):
        fail = first_fail_on_use if not created else None
        conn = _Conn(host, port, response, fail_on_use=fail)
        created.append(conn)
        return conn

    return factory, created


async def test_pool_reuses_connection():
    factory, created = _counting_factory(parse_response(_OK))
    engine = Engine(connection_factory=factory, reuse_connections=True)
    await engine.send(Request.from_url("http://h/a"))
    await engine.send(Request.from_url("http://h/b"))
    assert len(created) == 1  # second send reused the parked connection
    await engine.aclose()


async def test_default_engine_opens_each_time():
    factory, created = _counting_factory(parse_response(_OK))
    engine = Engine(connection_factory=factory)  # pooling OFF
    await engine.send(Request.from_url("http://h/a"))
    await engine.send(Request.from_url("http://h/b"))
    assert len(created) == 2


async def test_different_host_uses_separate_connection():
    factory, created = _counting_factory(parse_response(_OK))
    engine = Engine(connection_factory=factory, reuse_connections=True)
    await engine.send(Request.from_url("http://h1/a"))
    await engine.send(Request.from_url("http://h2/a"))
    assert len(created) == 2
    await engine.aclose()


async def test_stale_reused_connection_retries_once():
    factory, created = _counting_factory(parse_response(_OK), first_fail_on_use=2)
    engine = Engine(connection_factory=factory, reuse_connections=True)
    await engine.send(Request.from_url("http://h/a"))  # conn A use#1 ok -> parked
    resp = await engine.send(Request.from_url("http://h/b"))  # A reused, use#2 raises -> retry B
    assert resp.status_code == 200
    assert len(created) == 2  # A then fresh B
    assert created[0].closed is True  # stale A closed
    await engine.aclose()


async def test_aclose_closes_parked_connections():
    factory, created = _counting_factory(parse_response(_OK))
    engine = Engine(connection_factory=factory, reuse_connections=True)
    await engine.send(Request.from_url("http://h/a"))
    assert created[0].closed is False  # parked, still open
    await engine.aclose()
    assert created[0].closed is True


async def test_async_context_manager_closes_pool():
    factory, created = _counting_factory(parse_response(_OK))
    async with Engine(connection_factory=factory, reuse_connections=True) as engine:
        await engine.send(Request.from_url("http://h/a"))
    assert created[0].closed is True


def test_sync_close_drains_pool():
    factory, created = _counting_factory(parse_response(_OK))
    engine = Engine(connection_factory=factory, reuse_connections=True)
    engine.send_sync(Request.from_url("http://h/a"))
    engine.close()
    assert created[0].closed is True
```

- [ ] **Step 2: Run to confirm fail** — `python -m pytest tests/transport/test_engine_pool.py -q` → fails (`Engine` has no `reuse_connections` kwarg → `TypeError`).

- [ ] **Step 3a: Edit imports in `penpine/transport/engine.py`.** Change the exceptions import and add the pool import:
```python
from penpine.transport.connection import Connection
from penpine.transport.exceptions import (
    ConnectError,
    IncompleteResponseError,
    TotalTimeout,
    TransportError,
)
from penpine.transport.interceptor import RetrySignal
from penpine.transport.pool import ConnectionPool, PoolConfig, _connection_reusable
from penpine.transport.timeouts import Timeouts
from penpine.transport.tls import TLSConfig
```

- [ ] **Step 3b: Add the constructor params + pool.** Change the `__init__` signature to add `reuse_connections=False,` and `pool=None,` (place them after `connection_factory=Connection,`), and replace the end of `__init__` (`self._connection_factory = connection_factory` onward) with:
```python
        self._connection_factory = connection_factory
        if pool is not None or reuse_connections:
            self._pool = ConnectionPool(
                connection_factory,
                tls=self.tls,
                proxy=self.proxy,
                timeouts=self.timeouts,
                config=pool or PoolConfig(),
            )
        else:
            self._pool = None
        self._loop = None
        self._loop_thread = None
```

- [ ] **Step 3c: Make `_send` use the pool.** In `_send`, replace the connection block — currently:
```python
            conn = self._connection_factory(
                meta.host,
                meta.port,
                use_tls=use_tls,
                tls=self.tls,
                proxy=self.proxy,
                timeouts=self.timeouts,
            )
            try:
                await conn.open()
                await conn.send_bytes(req.serialize())
                resp = await conn.read_response(req.method)
            finally:
                await conn.close()
```
with:
```python
            if self._pool is None:
                conn = self._connection_factory(
                    meta.host,
                    meta.port,
                    use_tls=use_tls,
                    tls=self.tls,
                    proxy=self.proxy,
                    timeouts=self.timeouts,
                )
                try:
                    await conn.open()
                    await conn.send_bytes(req.serialize())
                    resp = await conn.read_response(req.method)
                finally:
                    await conn.close()
            else:
                resp = await self._send_pooled((meta.host, meta.port, use_tls), req)
```

- [ ] **Step 3d: Add `_send_pooled` + lifecycle methods.** Add `_send_pooled` immediately after `_send`:
```python
    async def _send_pooled(self, key, req):
        conn, reused = await self._pool.acquire(key)
        try:
            await conn.send_bytes(req.serialize())
            resp = await conn.read_response(req.method)
        except (ConnectError, IncompleteResponseError, OSError):
            await conn.close()
            if not reused:
                raise
            conn, _ = await self._pool.acquire(key, force_new=True)
            try:
                await conn.send_bytes(req.serialize())
                resp = await conn.read_response(req.method)
            except BaseException:
                await conn.close()
                raise
        await self._pool.release(key, conn, _connection_reusable(req, resp))
        return resp

    async def aclose(self):
        if self._pool is not None:
            await self._pool.aclose()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        await self.aclose()
```

- [ ] **Step 3e: Drain the pool in sync `close()`.** Replace the existing `close` method with:
```python
    def close(self):
        if self._loop is not None:
            if self._pool is not None:
                asyncio.run_coroutine_threadsafe(self.aclose(), self._loop).result(timeout=2)
            self._loop.call_soon_threadsafe(self._loop.stop)
            self._loop_thread.join(timeout=2)
            self._loop.close()
            self._loop = None
            self._loop_thread = None
```
(The existing sync `__enter__`/`__exit__` stay as they are — do not remove them.)

- [ ] **Step 3f: Re-export `PoolConfig`.** In `penpine/transport/__init__.py`, add `from penpine.transport.pool import PoolConfig` (place it with the other transport imports, keeping import order ruff-clean) and add `"PoolConfig",` to `__all__`.

- [ ] **Step 4: Run to confirm pass** — `python -m pytest tests/transport/test_engine_pool.py -q` → all 7 pass.

- [ ] **Step 5: Full suite + gates, then commit.**
```bash
python -m pytest -q          # expect 377 baseline + pool + engine-pool tests, 1 skipped, no regressions
ruff check . && ruff format --check .
git add penpine/transport/engine.py penpine/transport/__init__.py tests/transport/test_engine_pool.py
git -c commit.gpgsign=false commit -m "feat(transport): opt-in connection pooling in Engine with guarded stale retry"
```

---

### Final verification (after all tasks)

- [ ] `ruff check . && ruff format --check . && python -m pytest -q` → gates clean; suite green (377 baseline + ~24 new pool/engine-pool tests, 1 skipped).
- [ ] Confirm default-off compatibility: the pre-existing `tests/transport/` suite (one-shot path) stays green.

---

## Self-Review

**Spec coverage:**
- §4.1 `PoolConfig` → Task 1. ✓
- §4.2 `_connection_reusable` (all branches) → Task 1 + the six reusability tests. ✓
- §4.3 `ConnectionPool` (acquire/release/aclose, eviction, cap, force_new, I/O outside lock) → Task 1 + pool tests. ✓
- §5.1 constructor params + pool build → Task 2 Step 3b. ✓
- §5.2 pooled `_send` path + guarded retry-once → Task 2 Step 3c/3d + `test_pool_reuses_connection`/`test_stale_reused_connection_retries_once`. ✓
- §5.3 `aclose`/async context + sync `close` drains pool → Task 2 Step 3d/3e + lifecycle tests. ✓
- §6 `PoolConfig` re-export → Task 2 Step 3f. ✓
- §7 errors (stale retry, propagation) → `test_stale_reused_connection_retries_once`. ✓
- §8 testing strategy → Tasks 1–2 tests, incl. default-off regression. ✓

**Placeholder scan:** No TBD/TODO; every code step is complete. The Task 2 Step 3c/3e edits show the exact before/after blocks. ✓

**Type/name consistency:** `PoolConfig`, `_connection_reusable`, `ConnectionPool(...).acquire/release/aclose` defined in Task 1 are imported and called with matching signatures in Task 2 (`acquire(key)` → `(conn, reused)`, `acquire(key, force_new=True)`, `release(key, conn, reusable)`, `aclose()`). Fake connections in both test files implement exactly the methods the code calls (`open`, `send_bytes`, `read_response`, `close`, `closed`). Engine constructor `reuse_connections`/`pool` names match the spec and the `__init__.py` export adds `PoolConfig`. ✓
