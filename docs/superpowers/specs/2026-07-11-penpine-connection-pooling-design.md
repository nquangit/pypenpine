# Penpine — L1 Connection Pooling / Keep-Alive (Design Spec)

**Date:** 2026-07-11
**Status:** Approved for implementation planning
**Scope:** Opt-in HTTP/1.1 connection pooling with keep-alive reuse in the transport `Engine`. Sub-project B of Tier 3 (value-first order).

---

## 1. Context

Today `Engine._send` opens a fresh socket per request (`connection_factory(...)` → `open()` → `send_bytes` → `read_response` → `finally: close()`). For a fuzzer firing hundreds of requests at one host this is the top throughput ceiling. There is no keep-alive handling anywhere. This adds an **opt-in** pool that reuses keep-alive-able connections keyed by `(host, port, use_tls)`.

Depends on (all existing):
- `Connection(host, port, *, use_tls, tls, proxy, timeouts, stream_opener)` with `open()`, `send_bytes()`, `read_response()`, `close()`, `closed` (property).
- `Engine(*, tls, proxy, interceptors, timeouts, max_concurrency, max_retries, connection_factory)`; the `_send`/`send`/`send_sync`/`send_many` methods.
- `Response.version` (default `"HTTP/1.1"`), `Response.status_code`, `Response.headers` (case-insensitive `.get`). Chunked responses retain the `Transfer-Encoding: chunked` header after parsing (verified); `Content-Length` responses retain `Content-Length`.
- `ConnectError`, `IncompleteResponseError` (`transport/exceptions.py`).

**Decisions (this round):**
- **Opt-in, default OFF** — `reuse_connections=False`; enable via `Engine(reuse_connections=True)` or `Engine(pool=PoolConfig(...))`.
- **Guarded retry-once** on a stale reused connection (server reaped an idle keep-alive).
- **Per-host idle cap + idle-timeout eviction** (no global cap / LRU in v1).

## 2. Goals & Non-Goals

**Goals**
- A `ConnectionPool` reusing keep-alive-able connections keyed by `(host, port, use_tls)`, with a per-host idle cap and idle-timeout eviction.
- Opt-in Engine integration that leaves the default one-shot path byte-for-byte unchanged.
- Correct HTTP/1.1 keep-alive determination (framing + `Connection` header + version).
- A guarded retry-once when a *reused* connection fails before completing.
- An `aclose()` / async context manager so pooled sockets are released.
- Fully unit-testable with fake connections — no real network.

**Non-Goals (documented follow-ups)**
- Global connection cap / LRU eviction across hosts.
- HTTP/2 or pipelining.
- Proactive idle-connection health checks (we validate `closed` + guarded retry instead).
- Exposing `--reuse` on `penpine run` (a trivial later add).
- Pool-acquire blocking/backpressure (concurrency stays bounded by the Engine semaphore).

## 3. Module Layout

```
penpine/transport/pool.py     # new — PoolConfig, ConnectionPool, _connection_reusable
penpine/transport/engine.py   # modified — reuse_connections/pool params, pooled _send path, retry, aclose
penpine/transport/__init__.py # modified — re-export PoolConfig
```
No changes to `Connection`, `reader`, `stream`, or the existing one-shot path.

## 4. `pool.py`

### 4.1 `PoolConfig`
```python
@dataclass
class PoolConfig:
    max_per_host: int = 8       # max IDLE connections retained per (host, port, use_tls)
    idle_timeout: float = 30.0  # close idle conns older than this (seconds) on acquire
```

### 4.2 `_connection_reusable(request, response) -> bool`
```python
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
    return False  # EOF-framed: socket is spent
```

### 4.3 `ConnectionPool`
```python
class ConnectionPool:
    def __init__(self, connection_factory, *, tls, proxy, timeouts, config=None): ...
    async def acquire(self, key, *, force_new=False) -> tuple[object, bool]: ...  # (conn, reused)
    async def release(self, key, conn, reusable: bool) -> None: ...
    async def aclose(self) -> None: ...
```
- `key = (host, port, use_tls)`.
- Internal state: `self._idle: dict[key, collections.deque[tuple[conn, released_monotonic]]]`, `self._lock = asyncio.Lock()`. `time.monotonic()` for ages.
- **`_open(key)`** (private): builds a connection via the factory and opens it (outside the lock):
  ```python
  host, port, use_tls = key
  conn = self._factory(host, port, use_tls=use_tls, tls=self._tls, proxy=self._proxy, timeouts=self._timeouts)
  await conn.open()
  return conn
  ```
- **`acquire(key, force_new=False)`**:
  - If not `force_new`: under the lock, pop from `self._idle[key]` (left) — collecting any `conn.closed` or `now - released > idle_timeout` (when `idle_timeout` truthy) as *stale*; the first live one is the winner. Release the lock, close the stale ones, and if a winner was found return `(winner, True)`.
  - Otherwise open a fresh connection: `(await self._open(key), False)`.
- **`release(key, conn, reusable)`**:
  - If `not reusable or conn.closed` → `await conn.close()`; return.
  - Under the lock: if `len(self._idle[key]) >= config.max_per_host` → mark to close; else append `(conn, time.monotonic())` and return. Close the marked one outside the lock.
- **`aclose()`**: under the lock, drain all deques into a list and clear; then `await conn.close()` for each.
- Awaiting network I/O (`open`, `close`) happens **outside** the lock; only dict/deque manipulation is under it.

## 5. Engine integration (`engine.py`)

### 5.1 Constructor
Add params: `reuse_connections: bool = False`, `pool: PoolConfig | None = None`.
```python
if pool is not None or reuse_connections:
    self._pool = ConnectionPool(
        self._connection_factory, tls=self.tls, proxy=self.proxy,
        timeouts=self.timeouts, config=pool or PoolConfig(),
    )
else:
    self._pool = None
```

### 5.2 `_send` pooled path
When `self._pool is None`, the existing one-shot body runs unchanged. When pooling is on, replace the per-attempt `factory/open/try/finally-close` block with a call to `_send_pooled(key, req)` where `key = (meta.host, meta.port, use_tls)`; the surrounding retry loop, interceptors, proxy target-rewrite, and `RetrySignal` handling are unchanged.

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
        # stale keep-alive: the server reaped the idle conn before processing -> retry once fresh
        conn, _ = await self._pool.acquire(key, force_new=True)
        try:
            await conn.send_bytes(req.serialize())
            resp = await conn.read_response(req.method)
        except BaseException:
            await conn.close()
            raise
    await self._pool.release(key, conn, _connection_reusable(req, resp))
    return resp
```
- The L1 `total` timeout still wraps the whole `send()`; `read` still wraps `read_response` inside `Connection`. A `ReadTimeout` (not a `ConnectError`/`OSError`) propagates and is **not** retried.
- The pooled path itself does not add retries beyond the single stale-reuse retry; `RetrySignal` from interceptors still drives the outer loop.

### 5.3 Lifecycle
- Add `async def aclose(self)`: `if self._pool is not None: await self._pool.aclose()`. No-op when pooling is off.
- Add async context manager: `__aenter__` returns `self`; `__aexit__` calls `await self.aclose()`.
- Extend sync `close()`: if `self._pool is not None` and the loop thread exists, drain the pool on the loop before stopping it — `asyncio.run_coroutine_threadsafe(self.aclose(), self._loop).result(timeout=2)` — then proceed with the existing loop teardown. If pooling is off, `close()` is unchanged.

## 6. Public API / exports

- `penpine/transport/__init__.py` re-exports `PoolConfig` (add to the import block and `__all__`). `ConnectionPool` stays internal (not exported).
- No change to `penpine/__init__.py`.

## 7. Errors

- Stale reused connection → transparent single retry (§5.2). A failure on the retry (or on a fresh connection) propagates as the underlying transport error.
- `_connection_reusable` never raises (pure header inspection).
- Pool operations raise only what `Connection.open()`/`close()` raise (connect/TLS errors), surfaced through `acquire`.

## 8. Testing Strategy (TDD)

All unit-level, no real sockets. A fake connection records `opened`/`closed` and a scripted response.

- **`_connection_reusable`:** `Content-Length`→True; `Transfer-Encoding: chunked`→True; `204`/`304`→True; `HEAD` request→True; `Connection: close` on request or response→False; HTTP/1.0 without keep-alive→False; EOF-framed (no CL/TE, 200 GET)→False.
- **pool acquire/release:** empty pool opens (reused=False); after `release(reusable=True)`, a subsequent `acquire` returns that conn (reused=True); a `closed` parked conn is skipped and a new one opened; an entry older than `idle_timeout` is evicted (use `idle_timeout` small + monkeypatched/awaited delay, or inject the released timestamp); `release` beyond `max_per_host` closes the overflow; `force_new=True` ignores idle; `aclose` closes all parked conns.
- **engine reuse:** counting fake `connection_factory` returning a `Content-Length` response; two sequential `send`s to the same host with `reuse_connections=True` → factory invoked **once**; with default (off) → **twice**; a second host key → a separate connection.
- **stale retry:** a fake whose first *reused* use raises `IncompleteResponseError`, second use returns a response → `send` returns the response and the factory opened a replacement; a failure on a fresh conn raises.
- **lifecycle:** `await engine.aclose()` closes parked conns; `async with Engine(reuse_connections=True) as e:` closes on exit; `engine.send_sync` works with pooling and `engine.close()` drains the pool.
- **regression:** default Engine (no pool) — the full existing transport suite stays green (one-shot path untouched).

## 9. Dependencies

Runtime: stdlib `asyncio`, `collections.deque`, `time`. No new dependencies. Python 3.11+.

## 10. Forward Hooks

- A global cap + LRU eviction extends `PoolConfig`/`ConnectionPool` without touching the Engine.
- `penpine run --reuse` maps a CLI flag to `Engine(reuse_connections=True)`.
- Proactive idle health checks or HTTP/2 are separate, larger efforts that can reuse the pool boundary.
