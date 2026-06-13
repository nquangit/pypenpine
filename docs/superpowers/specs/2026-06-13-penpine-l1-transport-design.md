# Penpine — L1: Transport Engine (Design Spec)

**Date:** 2026-06-13
**Status:** Approved for implementation planning
**Scope:** This spec covers **L1 only** — the transport engine. L0 is complete and merged. L2–L4 are out of scope and each get their own spec→plan→build cycle.

---

## 1. Context

L1 sits directly on top of L0 (the HTTP message core, merged into `main`). It is the network layer: it takes an L0 `Request`, sends its exact wire bytes over a raw socket, reads the response stream, and returns an L0 `Response`.

L0 already provides everything L1 consumes:
- `Request.meta` (`ConnectionMeta`: scheme/host/port) — where to connect.
- `Request.serialize()` — exact bytes to put on the wire.
- `parse_response(bytes) -> Response` — turns raw response bytes back into a structured, byte-faithful `Response`.
- `get_logger`, `configure_logging` — shared logging.
- `PenpineError` — base exception.

**Foundational decisions (locked across the project):**
- Transport: raw `socket` via asyncio + stdlib `ssl` (no requests/httpx/urllib). All HTTP framing is hand-rolled.
- Protocol: HTTP/1.1 only.
- Concurrency: async core + synchronous facade.

**L1 decisions (this round):**
- TLS certificate verification is **off by default** (pentest convention), configurable on.
- Expose **both** a low-level persistent `Connection` and a high-level `Engine`.
- Proxy support: **HTTP CONNECT and SOCKS5**.
- Include a **minimal interceptor seam** (before_send / after_receive + retry signal) that L2 fills.

## 2. Goals & Non-Goals

**Goals**
- Send an L0 `Request` and receive an L0 `Response` over TCP, with optional TLS and optional proxy.
- A persistent, manually-drivable `Connection` primitive (for smuggling/pipelining/desync) and a convenient `Engine.send` / `Engine.send_many`.
- Async core with a synchronous facade that works with or without a running event loop.
- Configurable TLS (verify, versions, ciphers, SNI, client cert, CA) and proxy (HTTP CONNECT, SOCKS5).
- An interceptor seam with a retry mechanism, so L2 can implement 401→re-login→retry without modifying the Engine.
- Robust, typed error handling and shared logging.
- The read path is fully unit-testable with **zero real sockets**.

**Non-Goals (deferred)**
- Connection pooling / automatic keep-alive reuse in the Engine (one-shot per `send`; manual reuse via `Connection`). Focused follow-up.
- HTTP/2.
- Auth/session logic (L2) — interceptors are empty seams here.
- Data profiles / attacks (L3/L4).

## 3. Module Layout

```
penpine/transport/
  __init__.py
  exceptions.py     # TransportError hierarchy
  timeouts.py       # Timeouts(connect, read, total)
  stream.py         # ByteStream (asyncio-backed) + FakeByteStream (tests)
  reader.py         # ResponseReader: stream -> raw response bytes -> L0 Response
  tls.py            # TLSConfig + build_ssl_context()
  proxy.py          # ProxyConfig + HTTP CONNECT / SOCKS5 handshakes
  connection.py     # Connection
  interceptor.py    # Interceptor, RetrySignal, run helpers
  engine.py         # Engine (async) + sync facade
```

## 4. ByteStream (the I/O seam)

`ByteStream` is a thin async abstraction so all framing/handshake logic is testable without sockets.

Interface:
- `async read(n) -> bytes` — up to n bytes (may be short; `b""` on EOF).
- `async readexactly(n) -> bytes` — exactly n bytes or raise `IncompleteResponseError`.
- `async readline() -> bytes` — through and including `\n` (or to EOF).
- `write(b) -> None` and `async drain() -> None`.
- `async start_tls(ctx: ssl.SSLContext, server_hostname: str | None) -> None` — upgrade in place.
- `async close() -> None`; `closed: bool`.

Two implementations:
- `AsyncioByteStream` — wraps `(asyncio.StreamReader, asyncio.StreamWriter)`. `start_tls` delegates to the writer's `start_tls`.
- `FakeByteStream` — constructed with a scripted `bytes` buffer for reads and an accessible `sent: bytearray` for writes; `start_tls` records the call. Used throughout unit tests.

## 5. ResponseReader

`ResponseReader.read(stream: ByteStream, *, request_method: str) -> Response`

Algorithm:
1. Read bytes until the header terminator (`\r\n\r\n`, lenient also accepts `\n\n`), accumulating the head.
2. Parse just enough to get headers via L0 (`parse_response` will re-parse fully at the end; here we only need headers to decide framing — reuse L0's header parsing helper or a minimal local split, then `body_length(headers)`).
3. Determine the body bytes:
   - **No body** if `request_method == "HEAD"` or status is `204`/`304`: body is empty regardless of headers.
   - **chunked**: read chunk-size line, then that many bytes + trailing CRLF, repeating until a `0` chunk; then consume trailer lines until a blank line. Preserve the *exact framed bytes* read.
   - **content-length N**: `readexactly(N)`.
   - **neither**: read until EOF (`read` returns `b""`).
4. Concatenate head + framed body into the complete raw response bytes; return `parse_response(raw)`.

This keeps structure parsing entirely in L0; `ResponseReader` only does socket framing. `Response.raw` therefore holds the exact on-wire bytes (framed body included), and `Response.body.raw` holds the decoded body (L0 behavior).

Errors: a truncated head or body raises `IncompleteResponseError`; a malformed chunk-size raises `TransportError` (wrapping L0 `ParseError` where relevant).

## 6. TLSConfig

```
@dataclass
class TLSConfig:
    verify: bool = False
    server_hostname: str | None = None   # SNI; defaults to connection host
    min_version: ssl.TLSVersion | None = None
    max_version: ssl.TLSVersion | None = None
    ciphers: str | None = None
    ca_file: str | None = None
    client_cert: tuple[str, str | None] | None = None   # (certfile, keyfile)
    alpn: list[str] | None = None
```

`build_ssl_context() -> ssl.SSLContext`:
- Start from `ssl.create_default_context()`.
- If `verify is False`: `check_hostname = False`, `verify_mode = ssl.CERT_NONE`.
- If `verify is True` and `ca_file`: load it.
- Apply `min_version`/`max_version`/`ciphers`/`client_cert`/`alpn` when set.

## 7. ProxyConfig

`ProxyConfig.from_url(url)` parses `http://[user:pass@]host:port` or `socks5://[user:pass@]host:port` (scheme, host, port, optional credentials).

`async establish(open_stream, target_host, target_port) -> ByteStream` where `open_stream(host, port) -> ByteStream` opens a raw stream to a given address:
- **HTTP CONNECT**: open stream to proxy; send `CONNECT target_host:target_port HTTP/1.1\r\nHost: target_host:target_port\r\n` (+ `Proxy-Authorization: Basic ...` if creds) `\r\n`; read status line; require `2xx` else `ProxyError`. The returned stream is the tunnel (TLS upgrade happens afterward in `Connection`).
- **SOCKS5**: open stream to proxy; version/method greeting (`05 01 00`, or `05 02 00 02` with username/password auth when creds present); on `02`, perform username/password sub-negotiation; send `CONNECT` command (`05 01 00 03 <len><host> <port>`) using domain address type; read reply, require success (`00`) else `ProxyError`.

(For plain-HTTP-through-HTTP-proxy, `Engine`/`Connection` will send the request in absolute-form rather than CONNECT — see §8.)

All handshakes are hand-rolled and unit-tested against `FakeByteStream`.

## 8. Connection

```
Connection(host, port, *, use_tls=False, tls=TLSConfig(), proxy=None,
           timeouts=Timeouts(), stream_opener=open_asyncio_stream)
```
- `stream_opener(host, port, timeouts) -> ByteStream` is injectable (defaults to the asyncio opener); tests pass a fake opener.
- `async open()`:
  1. If `proxy`: `stream = await proxy.establish(opener, host, port)`. Else `stream = await opener(host, port, timeouts)`.
  2. If `use_tls`: `await stream.start_tls(tls.build_ssl_context(), tls.server_hostname or host)`.
- `async send_bytes(b)`: `stream.write(b)`, `await stream.drain()`.
- `async read_response(method="GET") -> Response`: `ResponseReader.read(stream, request_method=method)`, bounded by `timeouts.read`.
- `async close()`; `closed`; `async with` support.
- **Plain HTTP via HTTP proxy:** when `proxy` is an HTTP proxy and `use_tls is False`, no CONNECT tunnel is used; instead the caller sends the request in absolute-form. The Engine handles target-form rewriting (§9); `Connection` simply connects to the proxy address in that case. (SOCKS always tunnels regardless of TLS.)

## 9. Engine

```
Engine(*, tls=TLSConfig(), proxy=None, interceptors=(), timeouts=Timeouts(),
       max_concurrency=10, max_retries=0, connection_factory=Connection)
```

`async send(request) -> Response`:
1. Resolve target from `request.meta` (`scheme`, `host`, `port`); `use_tls = scheme == "https"`. Raise `TransportError` if host/port missing.
2. Retry loop (≤ `max_retries + 1` attempts):
   a. `req = request`; run each interceptor's `before_send(req)` in order (each may return a transformed request).
   b. If using an HTTP proxy over plain HTTP, rewrite the request target to absolute-form for the wire.
   c. Open a one-shot `Connection(...)` (via `connection_factory`), `send_bytes(req.serialize())`, `resp = read_response(req.method)`, close.
   d. Run each interceptor's `after_receive(req, resp)` in reverse order (each may return a transformed response). If one raises `RetrySignal`, continue the loop; otherwise return `resp`.
3. If retries are exhausted after a `RetrySignal`, return the last response.

`async send_many(requests, *, return_exceptions=False) -> list[Response]`:
- Bounded by `asyncio.Semaphore(max_concurrency)`; preserves input order; semantics mirror `asyncio.gather(..., return_exceptions=...)`.

**Sync facade:** a lazily-started private event loop on a daemon thread; `send_sync(request)` / `send_many_sync(requests)` submit coroutines via `run_coroutine_threadsafe` and block for the result. Works whether or not the caller already runs an event loop. `Engine.close()` / context manager stops the loop thread.

## 10. Interceptors

```
class Interceptor:
    async def before_send(self, request): return request
    async def after_receive(self, request, response): return response


class RetrySignal(Exception):
    """Raised by an interceptor's after_receive to request a retry of send()."""
```

L1 ships the base class (no-op) and `RetrySignal` only. The Engine runs the chain and honors `RetrySignal` within `max_retries`. L2 supplies concrete interceptors (auth header injection in `before_send`; 401 detection → session refresh → `RetrySignal` in `after_receive`). No auth knowledge lives in L1.

## 11. Timeouts & Errors

```
@dataclass
class Timeouts:
    connect: float | None = 10.0
    read: float | None = 30.0
    total: float | None = None
```
Applied via `asyncio.timeout()` / `wait_for` around connect, read, and (optionally) whole-send.

```
TransportError(PenpineError)
├── ConnectError          # TCP connect failure (wraps OSError)
├── TLSError              # handshake/verify failure (wraps ssl.SSLError)
├── ProxyError            # CONNECT/SOCKS negotiation failure
├── ReadTimeout           # read exceeded timeout
└── IncompleteResponseError  # EOF before a complete response
```
Stdlib `OSError`/`ssl.SSLError`/`asyncio.TimeoutError` are caught and re-raised as the appropriate `TransportError` with host/port context.

## 12. Logging

Each module uses `get_logger(__name__)`. DEBUG: connection open, bytes sent, chunk reads, proxy handshake steps. INFO: one line per `send` with method, target, status, elapsed ms. No import-time logging configuration.

## 13. Testing Strategy (TDD)

**Unit (no sockets — primary coverage):**
- `FakeByteStream` read/readexactly/readline/EOF behavior.
- `ResponseReader`: content-length, chunked (incl. trailers), read-until-EOF, HEAD, 204, 304, truncated head/body → `IncompleteResponseError`.
- `TLSConfig.build_ssl_context`: `verify=False` ⇒ `check_hostname False` / `CERT_NONE`; version/cipher application.
- `ProxyConfig.from_url` parsing; HTTP CONNECT success + non-2xx → `ProxyError`; SOCKS5 no-auth + user/pass success + failure replies, against `FakeByteStream`.
- `Connection.open` flow with a fake `stream_opener` (direct, proxy, TLS-upgrade call recorded).
- `Engine.send` pipeline with a stub `connection_factory`: interceptor ordering, request/response transforms, `RetrySignal` retry within `max_retries`, target resolution errors.
- `Engine.send_many`: ordering, concurrency bound, `return_exceptions`.
- Sync facade: `send_sync` returns correct result; works when no loop is running.

**Integration (localhost, opt-in / skippable):**
- Plaintext round-trip against a stdlib `http.server` in a thread.
- TLS round-trip using a runtime self-signed cert with `verify=False`.
- One end-to-end HTTP-CONNECT test via a tiny in-process proxy.

## 14. Dependencies

- Runtime: none beyond L0's (`jsonpath-ng`) — L1 uses only stdlib `asyncio`/`ssl`/`socket`.
- Dev/test: `pytest`, `pytest-asyncio` (for async unit tests). Python 3.11+ (`asyncio.timeout`, `start_tls`).

## 15. Forward Hooks

- The interceptor seam (§10) is consumed by L2 (auth providers, 401→re-login, scheduler-driven session refresh that gates sends).
- `connection_factory` / `stream_opener` injection points make L1 fully testable and let L2/L4 wrap or observe transport.
- Connection pooling/keep-alive is a planned follow-up that will live behind the existing `Engine.send` interface without changing its signature.
```
