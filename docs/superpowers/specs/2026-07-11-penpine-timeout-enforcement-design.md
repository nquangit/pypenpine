# Penpine — L1 Read/Total Timeout Enforcement (Design Spec)

**Date:** 2026-07-11
**Status:** Approved for implementation planning
**Scope:** Enforce the `read` and `total` transport timeouts (currently defined but unenforced). Sub-project A of Tier 3 (value-first order).

---

## 1. Context

`Timeouts(connect=10.0, read=30.0, total=None)` exists and is threaded through `Engine` → `Connection`. Only **connect** is enforced (`asyncio.wait_for` in `open_asyncio_stream`, raising `ConnectError`). `Connection.read_response` calls `ResponseReader.read(stream)` with no timeout, so a slow/hung server read blocks forever and `ReadTimeout` (defined in `transport/exceptions.py`) is never raised; nothing bounds the overall `send()`, so `total` is ignored. This closes both gaps.

Depends on (all existing):
- `Timeouts` (`transport/timeouts.py`), `Connection` (`transport/connection.py`), `Engine` (`transport/engine.py`), `ResponseReader.read`, `transport/exceptions.py` (`TransportError`, `ReadTimeout`, `ConnectError`).

**Decisions (this round):**
- **read** = whole-response deadline: the full response must finish arriving within `read` seconds (wrap `read_response` in `wait_for`).
- **total** = overall ceiling on one `send()` call, including connect/TLS/write/read/interceptors/retries (wrap the send body in `wait_for`).
- **connect** behavior is unchanged (stays `ConnectError`).
- Exception model gains a `TransportTimeout` base and a `TotalTimeout`; `ReadTimeout` is reparented under `TransportTimeout` (still a `TransportError`).

## 2. Goals & Non-Goals

**Goals**
- `Connection.read_response` raises `ReadTimeout` when the response is not fully read within `timeouts.read`.
- `Engine.send` raises `TotalTimeout` when a single send exceeds `timeouts.total`.
- Both timeouts are opt-out via `None`; the existing `read=30.0` default now actually applies.
- A `TransportTimeout` base so callers can catch any timeout uniformly.
- Fully unit-testable with fake streams/connections — no real network.

**Non-Goals (documented follow-ups)**
- Per-read idle (httpx-style) read timeout — chose whole-response deadline.
- A `ConnectTimeout` subtype (connect stays `ConnectError`).
- A write/send timeout (writes are buffered and fast; `total` backstops any stall).
- Pool/keep-alive timeouts (that is sub-project B).

## 3. Exception model (`transport/exceptions.py`)

```python
class TransportTimeout(TransportError):
    """Base class for transport timeouts."""


class ReadTimeout(TransportTimeout):   # was: (TransportError)
    """A read exceeded its timeout."""


class TotalTimeout(TransportTimeout):
    """A send exceeded its total timeout."""
```
- `ReadTimeout` is reparented from `TransportError` to `TransportTimeout` — it remains a `TransportError` transitively, so any `except TransportError` still catches it.
- `TotalTimeout` is new.
- `__init__.py` of `transport` re-exports `TransportTimeout` and `TotalTimeout` alongside the existing `ReadTimeout` (keep the existing export list; add the two new names).

## 4. Read enforcement (`transport/connection.py`)

Add `import asyncio` and import `ReadTimeout`. Replace `read_response`:
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
- `timeouts.read is None` (or `0`/falsy) → no timeout, original behavior.
- On timeout, `asyncio.wait_for` cancels the read coroutine; the caller (`Engine._send`) closes the connection in its `finally`, so the socket is released.
- `asyncio.TimeoutError` is `TimeoutError` in Python 3.11+, so `except TimeoutError` is correct.

## 5. Total enforcement (`transport/engine.py`)

Rename the current `async def send(self, request)` body to `async def _send(self, request)` (unchanged logic), and add a thin wrapper:
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
- `asyncio` is already imported in `engine.py`; add `TotalTimeout` to the exceptions import.
- Wraps the entire operation: meta check, interceptor `before_send`, connect, TLS, write, read, `after_receive`, and any `RetrySignal` retries.
- If both `read` and `total` are set, whichever elapses first raises its error (`ReadTimeout` vs `TotalTimeout`).
- On total timeout, the inner `_send` task is cancelled; its `try/finally: await conn.close()` runs during cancellation, closing the socket.
- `send_sync`, `send_many`, and `send_many_sync` are unchanged — they call `send`, so each request gets its own `total` budget.

## 6. Behavior change (defaults)

`Timeouts` already defaults `read=30.0`. Before this change reads were unbounded; after it, a response that does not fully arrive within 30s raises `ReadTimeout`. This is the intended fix and is ample for the suite's small synthetic responses (which complete instantly). `total` defaults to `None` (opt-in), so no overall ceiling is imposed unless configured. No other default becomes newly restrictive.

## 7. Testing Strategy (TDD)

All unit-level, no real sockets. Uses fake streams/connections injected via the existing `stream_opener`/`connection_factory` seams.

- **read fires:** a fake `ByteStream` whose `readline` awaits `asyncio.sleep(10)`; `Connection("h", 80, stream_opener=lambda *_: hanging, timeouts=Timeouts(read=0.05))`; `await conn.open(); await conn.read_response()` → raises `ReadTimeout`.
- **read disabled:** `timeouts=Timeouts(read=None)` with a fake stream that returns a complete response → `read_response()` returns the `Response`, no timeout.
- **total fires:** a fake connection class whose `open()` does `await asyncio.sleep(10)`; `Engine(connection_factory=SlowConn, timeouts=Timeouts(total=0.05, read=None))`; `await engine.send(Request.from_url("http://h/"))` → raises `TotalTimeout`.
- **total disabled:** `Timeouts(total=None)` with a fast fake connection → `send()` returns the `Response`.
- **hierarchy:** `issubclass(ReadTimeout, TransportTimeout)`, `issubclass(TotalTimeout, TransportTimeout)`, and both are `TransportError`.
- **re-export:** `from penpine.transport import TransportTimeout, TotalTimeout, ReadTimeout` works.
- **regression:** the existing transport suite stays green (fast fakes never trip the 30s read default).

## 8. Dependencies

Runtime: stdlib `asyncio` only (already used). No new dependencies. Python 3.11+.

## 9. Forward Hooks

- Sub-project B (pooling/keep-alive) adds a pool-acquire timeout and an idle-connection timeout; both slot onto `Timeouts` without disturbing read/total.
- A `ConnectTimeout(TransportTimeout)` and a per-read idle mode are clean later refinements that reuse the `TransportTimeout` base.
