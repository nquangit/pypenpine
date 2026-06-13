# Penpine L1 — Transport Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build L1 of Penpine — an asyncio transport engine that sends an L0 `Request` over raw sockets (with optional TLS and HTTP/SOCKS5 proxy) and returns an L0 `Response`, with a sync facade and an interceptor/retry seam.

**Architecture:** All HTTP framing is hand-rolled over `asyncio.open_connection`. A `ByteStream` abstraction makes the read path and proxy handshakes unit-testable with zero sockets (`FakeByteStream`). `ResponseReader` frames the response and delegates structure parsing back to L0's `parse_response`. A persistent `Connection` is the raw primitive; `Engine` adds one-shot send, bounded-concurrency batch, interceptors with a `RetrySignal` retry loop, and a sync facade on a background event loop.

**Tech Stack:** Python 3.11+, stdlib `asyncio`/`ssl`/`socket`, `pytest`, `pytest-asyncio`. Depends on L0 (already on `main`).

---

## File Structure

```
penpine/transport/
  __init__.py        # public exports
  exceptions.py      # TransportError hierarchy
  timeouts.py        # Timeouts
  stream.py          # ByteStream, FakeByteStream, AsyncioByteStream, open_asyncio_stream
  reader.py          # ResponseReader + framing helpers
  tls.py             # TLSConfig + build_ssl_context
  proxy.py           # ProxyConfig + HTTP CONNECT / SOCKS5
  connection.py      # Connection
  interceptor.py     # Interceptor, RetrySignal
  engine.py          # Engine (async + sync facade)
tests/transport/
  ... mirrors the above
```

Build order: scaffolding → exceptions/timeouts → stream → reader → tls → proxy → connection → interceptor → engine.send → engine.send_many → sync facade → public API + integration.

---

## Task 0: Transport scaffolding

**Files:**
- Create: `penpine/transport/__init__.py`, `tests/transport/__init__.py`
- Modify: `pyproject.toml`

- [ ] **Step 1: Add `pytest-asyncio` and asyncio mode to `pyproject.toml`**

Change the `[project.optional-dependencies]` and `[tool.pytest.ini_options]` sections to:

```toml
[project.optional-dependencies]
dev = ["pytest>=8.0", "pytest-asyncio>=0.23"]

[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"
```

- [ ] **Step 2: Create empty package inits**

Create empty files: `penpine/transport/__init__.py`, `tests/transport/__init__.py`.

- [ ] **Step 3: Install updated dev deps**

Run: `python -m pip install -e ".[dev]"`
Expected: installs `pytest-asyncio` successfully.

- [ ] **Step 4: Verify suite still green**

Run: `python -m pytest -q`
Expected: `77 passed` (L0 unaffected).

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml penpine/transport tests/transport
git commit -c commit.gpgsign=false -m "chore: scaffold L1 transport package + pytest-asyncio"
```

---

## Task 1: Exceptions + Timeouts

**Files:**
- Create: `penpine/transport/exceptions.py`, `penpine/transport/timeouts.py`
- Test: `tests/transport/test_exceptions.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/transport/test_exceptions.py
from penpine.exceptions import PenpineError
from penpine.transport.exceptions import (
    TransportError, ConnectError, TLSError, ProxyError,
    ReadTimeout, IncompleteResponseError,
)
from penpine.transport.timeouts import Timeouts


def test_hierarchy():
    for cls in (ConnectError, TLSError, ProxyError, ReadTimeout, IncompleteResponseError):
        assert issubclass(cls, TransportError)
    assert issubclass(TransportError, PenpineError)


def test_timeouts_defaults():
    t = Timeouts()
    assert t.connect == 10.0
    assert t.read == 30.0
    assert t.total is None
    assert Timeouts(connect=1.0).connect == 1.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/transport/test_exceptions.py -v`
Expected: FAIL — modules missing.

- [ ] **Step 3: Write minimal implementation**

```python
# penpine/transport/exceptions.py
"""Transport-layer exceptions."""
from __future__ import annotations

from penpine.exceptions import PenpineError


class TransportError(PenpineError):
    """Base class for transport failures."""


class ConnectError(TransportError):
    """TCP connection could not be established."""


class TLSError(TransportError):
    """TLS handshake or verification failed."""


class ProxyError(TransportError):
    """Proxy negotiation (HTTP CONNECT / SOCKS5) failed."""


class ReadTimeout(TransportError):
    """A read exceeded its timeout."""


class IncompleteResponseError(TransportError):
    """Connection ended before a complete response was read."""
```

```python
# penpine/transport/timeouts.py
"""Timeout configuration for the transport layer."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Timeouts:
    connect: float | None = 10.0
    read: float | None = 30.0
    total: float | None = None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/transport/test_exceptions.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add penpine/transport/exceptions.py penpine/transport/timeouts.py tests/transport/test_exceptions.py
git commit -c commit.gpgsign=false -m "feat: add transport exceptions and timeouts"
```

---

## Task 2: ByteStream (+ FakeByteStream, AsyncioByteStream, opener)

**Files:**
- Create: `penpine/transport/stream.py`
- Test: `tests/transport/test_stream.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/transport/test_stream.py
import pytest
from penpine.transport.stream import FakeByteStream
from penpine.transport.exceptions import IncompleteResponseError


async def test_read_returns_up_to_n_then_empty_on_eof():
    s = FakeByteStream(b"hello")
    assert await s.read(3) == b"hel"
    assert await s.read(10) == b"lo"
    assert await s.read(10) == b""


async def test_readexactly_ok_and_incomplete():
    s = FakeByteStream(b"abc")
    assert await s.readexactly(2) == b"ab"
    with pytest.raises(IncompleteResponseError):
        await s.readexactly(5)


async def test_readline_includes_newline():
    s = FakeByteStream(b"line1\r\nline2")
    assert await s.readline() == b"line1\r\n"
    assert await s.readline() == b"line2"


async def test_write_and_sent_and_tls_and_close():
    s = FakeByteStream()
    s.write(b"xy")
    await s.drain()
    assert s.sent == b"xy"
    await s.start_tls(object(), "example.com")
    assert s.tls_calls == ["example.com"]
    assert not s.closed
    await s.close()
    assert s.closed
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/transport/test_stream.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Write minimal implementation**

```python
# penpine/transport/stream.py
"""Async byte-stream abstraction over asyncio, plus a socket-free fake."""
from __future__ import annotations

import asyncio

from penpine.transport.exceptions import ConnectError, IncompleteResponseError
from penpine.transport.timeouts import Timeouts


class ByteStream:
    """Abstract async byte stream."""

    async def read(self, n: int) -> bytes:
        raise NotImplementedError

    async def readexactly(self, n: int) -> bytes:
        raise NotImplementedError

    async def readline(self) -> bytes:
        raise NotImplementedError

    def write(self, data: bytes) -> None:
        raise NotImplementedError

    async def drain(self) -> None:
        raise NotImplementedError

    async def start_tls(self, ctx, server_hostname) -> None:
        raise NotImplementedError

    async def close(self) -> None:
        raise NotImplementedError

    @property
    def closed(self) -> bool:
        raise NotImplementedError


class FakeByteStream(ByteStream):
    """In-memory stream for tests. `sent` captures writes; `tls_calls` records start_tls."""

    def __init__(self, incoming: bytes = b""):
        self._buf = bytearray(incoming)
        self._pos = 0
        self.sent = bytearray()
        self.tls_calls: list = []
        self._closed = False

    def feed(self, data: bytes) -> None:
        self._buf.extend(data)

    async def read(self, n: int) -> bytes:
        chunk = bytes(self._buf[self._pos:self._pos + n])
        self._pos += len(chunk)
        return chunk

    async def readexactly(self, n: int) -> bytes:
        end = self._pos + n
        if end > len(self._buf):
            raise IncompleteResponseError(
                f"expected {n} bytes, got {len(self._buf) - self._pos}")
        chunk = bytes(self._buf[self._pos:end])
        self._pos = end
        return chunk

    async def readline(self) -> bytes:
        idx = self._buf.find(b"\n", self._pos)
        if idx == -1:
            chunk = bytes(self._buf[self._pos:])
            self._pos = len(self._buf)
            return chunk
        chunk = bytes(self._buf[self._pos:idx + 1])
        self._pos = idx + 1
        return chunk

    def write(self, data: bytes) -> None:
        self.sent.extend(data)

    async def drain(self) -> None:
        pass

    async def start_tls(self, ctx, server_hostname) -> None:
        self.tls_calls.append(server_hostname)

    async def close(self) -> None:
        self._closed = True

    @property
    def closed(self) -> bool:
        return self._closed


class AsyncioByteStream(ByteStream):
    """ByteStream backed by an asyncio reader/writer pair."""

    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        self._reader = reader
        self._writer = writer
        self._closed = False

    async def read(self, n: int) -> bytes:
        return await self._reader.read(n)

    async def readexactly(self, n: int) -> bytes:
        try:
            return await self._reader.readexactly(n)
        except asyncio.IncompleteReadError as exc:
            raise IncompleteResponseError(
                f"expected {n} bytes, got {len(exc.partial)}") from exc

    async def readline(self) -> bytes:
        return await self._reader.readline()

    def write(self, data: bytes) -> None:
        self._writer.write(data)

    async def drain(self) -> None:
        await self._writer.drain()

    async def start_tls(self, ctx, server_hostname) -> None:
        await self._writer.start_tls(ctx, server_hostname=server_hostname)

    async def close(self) -> None:
        self._closed = True
        self._writer.close()
        try:
            await self._writer.wait_closed()
        except Exception:
            pass

    @property
    def closed(self) -> bool:
        return self._closed


async def open_asyncio_stream(host: str, port: int, timeouts: Timeouts | None = None) -> AsyncioByteStream:
    """Default stream opener: connect a TCP socket and wrap it."""
    timeouts = timeouts or Timeouts()
    try:
        coro = asyncio.open_connection(host, port)
        if timeouts.connect:
            reader, writer = await asyncio.wait_for(coro, timeouts.connect)
        else:
            reader, writer = await coro
    except (OSError, asyncio.TimeoutError) as exc:
        raise ConnectError(f"failed to connect to {host}:{port}: {exc}") from exc
    return AsyncioByteStream(reader, writer)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/transport/test_stream.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add penpine/transport/stream.py tests/transport/test_stream.py
git commit -c commit.gpgsign=false -m "feat: add ByteStream abstraction with fake and asyncio backends"
```

---

## Task 3: ResponseReader

**Files:**
- Create: `penpine/transport/reader.py`
- Test: `tests/transport/test_reader.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/transport/test_reader.py
import pytest
from penpine.transport.reader import ResponseReader
from penpine.transport.stream import FakeByteStream
from penpine.transport.exceptions import IncompleteResponseError


async def test_content_length_body():
    raw = b"HTTP/1.1 200 OK\r\nContent-Length: 5\r\n\r\nhello"
    resp = await ResponseReader.read(FakeByteStream(raw), request_method="GET")
    assert resp.status_code == 200
    assert resp.body.raw == b"hello"
    assert resp.raw == raw


async def test_chunked_body_decoded_and_raw_preserved():
    raw = (b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n"
           b"5\r\nhello\r\n0\r\n\r\n")
    resp = await ResponseReader.read(FakeByteStream(raw), request_method="GET")
    assert resp.body.raw == b"hello"
    assert resp.raw == raw


async def test_chunked_with_trailers():
    raw = (b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n"
           b"4\r\nWiki\r\n0\r\nX-T: v\r\n\r\n")
    resp = await ResponseReader.read(FakeByteStream(raw), request_method="GET")
    assert resp.body.raw == b"Wiki"
    assert resp.raw == raw


async def test_read_until_eof_when_no_framing():
    raw = b"HTTP/1.1 200 OK\r\nConnection: close\r\n\r\nbodybytes"
    resp = await ResponseReader.read(FakeByteStream(raw), request_method="GET")
    assert resp.body.raw == b"bodybytes"


async def test_head_request_has_no_body():
    raw = b"HTTP/1.1 200 OK\r\nContent-Length: 5\r\n\r\n"
    resp = await ResponseReader.read(FakeByteStream(raw), request_method="HEAD")
    assert resp.body.raw == b""


async def test_304_has_no_body():
    raw = b"HTTP/1.1 304 Not Modified\r\nContent-Length: 5\r\n\r\n"
    resp = await ResponseReader.read(FakeByteStream(raw), request_method="GET")
    assert resp.status_code == 304
    assert resp.body.raw == b""


async def test_truncated_headers_raise():
    with pytest.raises(IncompleteResponseError):
        await ResponseReader.read(FakeByteStream(b"HTTP/1.1 200 OK\r\nContent-"),
                                  request_method="GET")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/transport/test_reader.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Write minimal implementation**

```python
# penpine/transport/reader.py
"""Read one full HTTP/1.1 response off a ByteStream, then hand to L0 to parse."""
from __future__ import annotations

from penpine.core.parse.framing import body_length
from penpine.core.parse.http_parser import parse_response
from penpine.transport.exceptions import IncompleteResponseError, TransportError
from penpine.transport.stream import ByteStream


class _Buffered:
    """Small read buffer over a ByteStream for line/exact reads (chunked decoding)."""

    def __init__(self, stream: ByteStream, initial: bytes = b""):
        self._stream = stream
        self._buf = bytearray(initial)

    async def _fill(self) -> bool:
        chunk = await self._stream.read(4096)
        if not chunk:
            return False
        self._buf.extend(chunk)
        return True

    async def read_line(self) -> bytes:
        while True:
            idx = self._buf.find(b"\r\n")
            if idx != -1:
                line = bytes(self._buf[:idx + 2])
                del self._buf[:idx + 2]
                return line
            if not await self._fill():
                raise IncompleteResponseError("EOF while reading chunk line")

    async def read_exact(self, n: int) -> bytes:
        while len(self._buf) < n:
            if not await self._fill():
                raise IncompleteResponseError("EOF while reading chunk data")
        data = bytes(self._buf[:n])
        del self._buf[:n]
        return data


async def _read_head(stream: ByteStream) -> tuple[bytes, bytes]:
    """Return (head_including_terminator, leftover_bytes_after_head)."""
    buf = bytearray()
    while True:
        i = buf.find(b"\r\n\r\n")
        j = buf.find(b"\n\n")
        idx, tlen = -1, 0
        if i != -1 and (j == -1 or i <= j):
            idx, tlen = i, 4
        elif j != -1:
            idx, tlen = j, 2
        if idx != -1:
            end = idx + tlen
            return bytes(buf[:end]), bytes(buf[end:])
        chunk = await stream.read(4096)
        if not chunk:
            raise IncompleteResponseError("EOF before end of response headers")
        buf.extend(chunk)


async def _read_n(stream: ByteStream, n: int, remainder: bytes) -> bytes:
    buf = bytearray(remainder)
    while len(buf) < n:
        chunk = await stream.read(4096)
        if not chunk:
            raise IncompleteResponseError(f"expected {n} body bytes, got {len(buf)}")
        buf.extend(chunk)
    return bytes(buf[:n])


async def _read_to_eof(stream: ByteStream, remainder: bytes) -> bytes:
    buf = bytearray(remainder)
    while True:
        chunk = await stream.read(4096)
        if not chunk:
            return bytes(buf)
        buf.extend(chunk)


async def _read_chunked(stream: ByteStream, remainder: bytes) -> bytes:
    buf = _Buffered(stream, remainder)
    framed = bytearray()
    while True:
        line = await buf.read_line()
        framed.extend(line)
        size_str = line.split(b";", 1)[0].strip()
        try:
            size = int(size_str, 16)
        except ValueError as exc:
            raise TransportError(f"invalid chunk size {size_str!r}") from exc
        if size == 0:
            while True:
                tline = await buf.read_line()
                framed.extend(tline)
                if tline == b"\r\n":
                    break
            return bytes(framed)
        framed.extend(await buf.read_exact(size))
        framed.extend(await buf.read_exact(2))


class ResponseReader:
    @staticmethod
    async def read(stream: ByteStream, *, request_method: str = "GET"):
        head, remainder = await _read_head(stream)
        preview = parse_response(head)
        method = request_method.upper()
        if method == "HEAD" or preview.status_code in (204, 304):
            body = b""
        else:
            kind, length = body_length(preview.headers)
            if kind == "length":
                body = await _read_n(stream, length, remainder)
            elif kind == "chunked":
                body = await _read_chunked(stream, remainder)
            else:
                body = await _read_to_eof(stream, remainder)
        return parse_response(head + body)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/transport/test_reader.py -v`
Expected: PASS (7 passed).

- [ ] **Step 5: Commit**

```bash
git add penpine/transport/reader.py tests/transport/test_reader.py
git commit -c commit.gpgsign=false -m "feat: add ResponseReader with chunked/length/eof framing"
```

---

## Task 4: TLSConfig

**Files:**
- Create: `penpine/transport/tls.py`
- Test: `tests/transport/test_tls.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/transport/test_tls.py
import ssl
from penpine.transport.tls import TLSConfig


def test_default_is_unverified():
    ctx = TLSConfig().build_ssl_context()
    assert ctx.check_hostname is False
    assert ctx.verify_mode == ssl.CERT_NONE


def test_verify_true_keeps_hostname_checking():
    ctx = TLSConfig(verify=True).build_ssl_context()
    assert ctx.check_hostname is True
    assert ctx.verify_mode == ssl.CERT_REQUIRED


def test_versions_and_ciphers_applied():
    cfg = TLSConfig(min_version=ssl.TLSVersion.TLSv1_2,
                    max_version=ssl.TLSVersion.TLSv1_2)
    ctx = cfg.build_ssl_context()
    assert ctx.minimum_version == ssl.TLSVersion.TLSv1_2
    assert ctx.maximum_version == ssl.TLSVersion.TLSv1_2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/transport/test_tls.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Write minimal implementation**

```python
# penpine/transport/tls.py
"""TLS configuration. Verification is OFF by default (pentest convention)."""
from __future__ import annotations

import ssl
from dataclasses import dataclass


@dataclass
class TLSConfig:
    verify: bool = False
    server_hostname: str | None = None
    min_version: ssl.TLSVersion | None = None
    max_version: ssl.TLSVersion | None = None
    ciphers: str | None = None
    ca_file: str | None = None
    client_cert: tuple[str, str | None] | None = None
    alpn: list[str] | None = None

    def build_ssl_context(self) -> ssl.SSLContext:
        ctx = ssl.create_default_context()
        if not self.verify:
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
        elif self.ca_file:
            ctx.load_verify_locations(self.ca_file)
        if self.min_version is not None:
            ctx.minimum_version = self.min_version
        if self.max_version is not None:
            ctx.maximum_version = self.max_version
        if self.ciphers:
            ctx.set_ciphers(self.ciphers)
        if self.client_cert:
            certfile, keyfile = self.client_cert
            ctx.load_cert_chain(certfile, keyfile)
        if self.alpn:
            ctx.set_alpn_protocols(self.alpn)
        return ctx
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/transport/test_tls.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add penpine/transport/tls.py tests/transport/test_tls.py
git commit -c commit.gpgsign=false -m "feat: add TLSConfig with unverified default"
```

---

## Task 5: ProxyConfig (HTTP CONNECT + SOCKS5)

**Files:**
- Create: `penpine/transport/proxy.py`
- Test: `tests/transport/test_proxy.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/transport/test_proxy.py
import pytest
from penpine.transport.proxy import ProxyConfig
from penpine.transport.stream import FakeByteStream
from penpine.transport.exceptions import ProxyError


def test_from_url_http_with_creds():
    p = ProxyConfig.from_url("http://user:pass@127.0.0.1:8080")
    assert p.scheme == "http"
    assert p.host == "127.0.0.1"
    assert p.port == 8080
    assert p.username == "user"
    assert p.password == "pass"


def test_from_url_socks5_defaults_port():
    p = ProxyConfig.from_url("socks5://10.0.0.1")
    assert p.scheme == "socks5"
    assert p.port == 1080


async def test_http_connect_success_sends_connect_and_consumes_headers():
    proxy_reply = b"HTTP/1.1 200 Connection Established\r\nX-Proxy: y\r\n\r\n"
    stream = FakeByteStream(proxy_reply)

    async def opener(host, port):
        assert (host, port) == ("127.0.0.1", 8080)
        return stream

    p = ProxyConfig.from_url("http://127.0.0.1:8080")
    out = await p.establish(opener, "target.com", 443)
    assert out is stream
    assert stream.sent.startswith(b"CONNECT target.com:443 HTTP/1.1\r\n")
    assert b"Host: target.com:443\r\n" in bytes(stream.sent)


async def test_http_connect_failure_raises():
    stream = FakeByteStream(b"HTTP/1.1 403 Forbidden\r\n\r\n")

    async def opener(host, port):
        return stream

    p = ProxyConfig.from_url("http://127.0.0.1:8080")
    with pytest.raises(ProxyError):
        await p.establish(opener, "target.com", 443)


async def test_socks5_no_auth_success():
    # greeting reply: version 5, method 0 ; connect reply: ok, atyp ipv4 + 6 bytes
    reply = b"\x05\x00" + b"\x05\x00\x00\x01" + b"\x00\x00\x00\x00\x00\x00"
    stream = FakeByteStream(reply)

    async def opener(host, port):
        return stream

    p = ProxyConfig.from_url("socks5://127.0.0.1:1080")
    out = await p.establish(opener, "target.com", 80)
    assert out is stream
    assert stream.sent.startswith(b"\x05\x01\x00")          # greeting
    assert b"\x05\x01\x00\x03\x0atarget.com" in bytes(stream.sent)  # connect, domain len 10


async def test_socks5_connect_failure_raises():
    reply = b"\x05\x00" + b"\x05\x01\x00\x01" + b"\x00\x00\x00\x00\x00\x00"
    stream = FakeByteStream(reply)

    async def opener(host, port):
        return stream

    p = ProxyConfig.from_url("socks5://127.0.0.1:1080")
    with pytest.raises(ProxyError):
        await p.establish(opener, "target.com", 80)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/transport/test_proxy.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Write minimal implementation**

```python
# penpine/transport/proxy.py
"""Proxy support: HTTP CONNECT and SOCKS5, hand-rolled over a ByteStream."""
from __future__ import annotations

import base64
import struct
from dataclasses import dataclass

from penpine.transport.exceptions import ProxyError


@dataclass
class ProxyConfig:
    scheme: str
    host: str
    port: int
    username: str | None = None
    password: str | None = None

    @classmethod
    def from_url(cls, url: str) -> "ProxyConfig":
        scheme, _, rest = url.partition("://")
        scheme = scheme.lower()
        creds = None
        authority = rest
        if "@" in rest:
            creds, authority = rest.rsplit("@", 1)
        host, _, port_s = authority.partition(":")
        default = 1080 if scheme.startswith("socks") else 8080
        port = int(port_s) if port_s else default
        username = password = None
        if creds:
            username, _, password = creds.partition(":")
        return cls(scheme=scheme, host=host, port=port,
                   username=username or None, password=password or None)

    async def establish(self, open_stream, target_host: str, target_port: int):
        stream = await open_stream(self.host, self.port)
        if self.scheme == "socks5":
            await _socks5_connect(stream, target_host, target_port,
                                  self.username, self.password)
        else:
            await _http_connect(stream, target_host, target_port,
                                self.username, self.password)
        return stream


async def _http_connect(stream, host, port, username, password) -> None:
    lines = [f"CONNECT {host}:{port} HTTP/1.1", f"Host: {host}:{port}"]
    if username is not None:
        token = base64.b64encode(f"{username}:{password or ''}".encode()).decode()
        lines.append(f"Proxy-Authorization: Basic {token}")
    stream.write(("\r\n".join(lines) + "\r\n\r\n").encode())
    await stream.drain()
    status_line = await stream.readline()
    parts = status_line.split(b" ")
    if len(parts) < 2 or not parts[1].startswith(b"2"):
        raise ProxyError(f"HTTP CONNECT failed: {status_line!r}")
    while True:
        line = await stream.readline()
        if line in (b"\r\n", b"\n", b""):
            break


async def _socks5_connect(stream, host, port, username, password) -> None:
    if username is not None:
        stream.write(b"\x05\x02\x00\x02")
    else:
        stream.write(b"\x05\x01\x00")
    await stream.drain()
    greeting = await stream.readexactly(2)
    if greeting[0:1] != b"\x05":
        raise ProxyError("SOCKS5: bad version in greeting reply")
    method = greeting[1]
    if method == 0x02:
        if username is None:
            raise ProxyError("SOCKS5: server requires auth but no credentials given")
        u = username.encode()
        p = (password or "").encode()
        stream.write(b"\x01" + bytes([len(u)]) + u + bytes([len(p)]) + p)
        await stream.drain()
        auth = await stream.readexactly(2)
        if auth[1] != 0x00:
            raise ProxyError("SOCKS5: authentication failed")
    elif method != 0x00:
        raise ProxyError(f"SOCKS5: no acceptable auth method ({method:#x})")
    host_b = host.encode()
    stream.write(b"\x05\x01\x00\x03" + bytes([len(host_b)]) + host_b
                 + struct.pack("!H", port))
    await stream.drain()
    reply = await stream.readexactly(4)
    if reply[1] != 0x00:
        raise ProxyError(f"SOCKS5: connect failed (code {reply[1]:#x})")
    atyp = reply[3]
    if atyp == 0x01:
        await stream.readexactly(4 + 2)
    elif atyp == 0x03:
        ln = (await stream.readexactly(1))[0]
        await stream.readexactly(ln + 2)
    elif atyp == 0x04:
        await stream.readexactly(16 + 2)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/transport/test_proxy.py -v`
Expected: PASS (6 passed).

- [ ] **Step 5: Commit**

```bash
git add penpine/transport/proxy.py tests/transport/test_proxy.py
git commit -c commit.gpgsign=false -m "feat: add HTTP CONNECT and SOCKS5 proxy support"
```

---

## Task 6: Connection

**Files:**
- Create: `penpine/transport/connection.py`
- Test: `tests/transport/test_connection.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/transport/test_connection.py
from penpine.transport.connection import Connection
from penpine.transport.stream import FakeByteStream
from penpine.transport.tls import TLSConfig
from penpine.transport.proxy import ProxyConfig


def make_opener(stream):
    async def opener(host, port, timeouts=None):
        opener.calls.append((host, port))
        return stream
    opener.calls = []
    return opener


async def test_direct_open_send_read():
    stream = FakeByteStream(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nok")
    opener = make_opener(stream)
    conn = Connection("h", 80, stream_opener=opener)
    await conn.open()
    await conn.send_bytes(b"GET / HTTP/1.1\r\nHost: h\r\n\r\n")
    resp = await conn.read_response("GET")
    assert resp.status_code == 200
    assert stream.sent.startswith(b"GET /")
    assert opener.calls == [("h", 80)]
    await conn.close()
    assert conn.closed


async def test_tls_upgrade_called_with_sni():
    stream = FakeByteStream(b"HTTP/1.1 200 OK\r\nContent-Length: 0\r\n\r\n")
    conn = Connection("secure.test", 443, use_tls=True, tls=TLSConfig(),
                      stream_opener=make_opener(stream))
    await conn.open()
    assert stream.tls_calls == ["secure.test"]


async def test_proxy_tunnels_to_target():
    # proxy reply then HTTP response, all on one fake stream
    stream = FakeByteStream(b"HTTP/1.1 200 Connection Established\r\n\r\n")
    opener = make_opener(stream)
    proxy = ProxyConfig.from_url("http://127.0.0.1:8080")
    conn = Connection("target.com", 443, use_tls=True, proxy=proxy,
                      stream_opener=opener)
    await conn.open()
    # opener was called with the PROXY address, not the target
    assert opener.calls == [("127.0.0.1", 8080)]
    assert bytes(stream.sent).startswith(b"CONNECT target.com:443")
    assert stream.tls_calls == ["target.com"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/transport/test_connection.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Write minimal implementation**

```python
# penpine/transport/connection.py
"""A persistent transport connection: open (direct/proxy/TLS), send, read."""
from __future__ import annotations

from penpine.transport.reader import ResponseReader
from penpine.transport.stream import open_asyncio_stream
from penpine.transport.timeouts import Timeouts
from penpine.transport.tls import TLSConfig


class Connection:
    def __init__(self, host, port, *, use_tls=False, tls=None, proxy=None,
                 timeouts=None, stream_opener=None):
        self.host = host
        self.port = port
        self.use_tls = use_tls
        self.tls = tls or TLSConfig()
        self.proxy = proxy
        self.timeouts = timeouts or Timeouts()
        self._opener = stream_opener or open_asyncio_stream
        self._stream = None

    async def open(self) -> "Connection":
        if self.proxy is not None and (self.proxy.scheme == "socks5" or self.use_tls):
            async def open_to(host, port):
                return await self._opener(host, port, self.timeouts)
            self._stream = await self.proxy.establish(open_to, self.host, self.port)
        elif self.proxy is not None:
            # plain HTTP via HTTP proxy: connect to the proxy directly (no CONNECT);
            # the Engine sends the request in absolute-form.
            self._stream = await self._opener(self.proxy.host, self.proxy.port, self.timeouts)
        else:
            self._stream = await self._opener(self.host, self.port, self.timeouts)
        if self.use_tls:
            ctx = self.tls.build_ssl_context()
            await self._stream.start_tls(ctx, self.tls.server_hostname or self.host)
        return self

    async def send_bytes(self, data: bytes) -> None:
        self._stream.write(data)
        await self._stream.drain()

    async def read_response(self, method: str = "GET"):
        return await ResponseReader.read(self._stream, request_method=method)

    async def close(self) -> None:
        if self._stream is not None and not self._stream.closed:
            await self._stream.close()

    @property
    def closed(self) -> bool:
        return self._stream is None or self._stream.closed

    async def __aenter__(self):
        return await self.open()

    async def __aexit__(self, *exc):
        await self.close()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/transport/test_connection.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add penpine/transport/connection.py tests/transport/test_connection.py
git commit -c commit.gpgsign=false -m "feat: add Connection primitive (direct/proxy/TLS)"
```

---

## Task 7: Interceptor + Engine.send (with retry loop)

**Files:**
- Create: `penpine/transport/interceptor.py`, `penpine/transport/engine.py`
- Test: `tests/transport/test_engine_send.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/transport/test_engine_send.py
import pytest
from penpine.core.message import Request
from penpine.core.parse.http_parser import parse_response
from penpine.transport.engine import Engine
from penpine.transport.interceptor import Interceptor, RetrySignal
from penpine.transport.exceptions import TransportError


class StubConn:
    instances = []

    def __init__(self, host, port, *, use_tls, tls, proxy, timeouts):
        self.host = host
        self.port = port
        self.use_tls = use_tls
        self.sent = None
        StubConn.instances.append(self)

    async def open(self):
        return self

    async def send_bytes(self, data):
        self.sent = data

    async def read_response(self, method="GET"):
        return parse_response(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nok")

    async def close(self):
        pass


def setup_function():
    StubConn.instances = []


async def test_send_uses_meta_and_returns_response():
    req = Request.from_url("http://h:8080/path")
    engine = Engine(connection_factory=StubConn)
    resp = await engine.send(req)
    assert resp.status_code == 200
    assert StubConn.instances[0].host == "h"
    assert StubConn.instances[0].port == 8080
    assert StubConn.instances[0].use_tls is False
    assert StubConn.instances[0].sent.startswith(b"GET /path")


async def test_https_meta_sets_use_tls():
    req = Request.from_url("https://h/x")
    engine = Engine(connection_factory=StubConn)
    await engine.send(req)
    assert StubConn.instances[0].use_tls is True


async def test_missing_meta_raises():
    req = Request(method="GET", target="/")
    with pytest.raises(TransportError):
        await Engine(connection_factory=StubConn).send(req)


async def test_before_send_transforms_request():
    class AddHeader(Interceptor):
        async def before_send(self, request):
            return request.set_header("X-Auth", "tok")

    req = Request.from_url("http://h:8080/")
    engine = Engine(interceptors=[AddHeader()], connection_factory=StubConn)
    await engine.send(req)
    assert b"X-Auth: tok" in StubConn.instances[0].sent


async def test_retry_signal_retries_until_max():
    calls = {"n": 0}

    class RetryOnce(Interceptor):
        async def after_receive(self, request, response):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RetrySignal
            return response

    req = Request.from_url("http://h:8080/")
    engine = Engine(interceptors=[RetryOnce()], max_retries=1,
                    connection_factory=StubConn)
    resp = await engine.send(req)
    assert resp.status_code == 200
    assert len(StubConn.instances) == 2  # one retry => two connections
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/transport/test_engine_send.py -v`
Expected: FAIL — modules missing.

- [ ] **Step 3: Write minimal implementation**

```python
# penpine/transport/interceptor.py
"""Interceptor seam. L2 supplies concrete implementations."""
from __future__ import annotations


class Interceptor:
    async def before_send(self, request):
        return request

    async def after_receive(self, request, response):
        return response


class RetrySignal(Exception):
    """Raised by an interceptor's after_receive to request a retry of send()."""
```

```python
# penpine/transport/engine.py
"""Engine: high-level send over one-shot connections, with interceptors + retry."""
from __future__ import annotations

from penpine.transport.connection import Connection
from penpine.transport.exceptions import TransportError
from penpine.transport.interceptor import RetrySignal
from penpine.transport.timeouts import Timeouts
from penpine.transport.tls import TLSConfig


class Engine:
    def __init__(self, *, tls=None, proxy=None, interceptors=(), timeouts=None,
                 max_concurrency=10, max_retries=0, connection_factory=Connection):
        self.tls = tls or TLSConfig()
        self.proxy = proxy
        self.interceptors = list(interceptors)
        self.timeouts = timeouts or Timeouts()
        self.max_concurrency = max_concurrency
        self.max_retries = max_retries
        self._connection_factory = connection_factory

    async def send(self, request):
        meta = request.meta
        if not meta.host or not meta.port:
            raise TransportError(
                "request.meta missing host/port; build via Request.from_url or set meta")
        use_tls = meta.scheme == "https"
        last_resp = None
        for _ in range(self.max_retries + 1):
            req = request
            for ic in self.interceptors:
                req = await ic.before_send(req)
            if (self.proxy is not None
                    and self.proxy.scheme.startswith("http") and not use_tls):
                req = req.with_target(f"http://{meta.host}:{meta.port}{req.target}")
            conn = self._connection_factory(
                meta.host, meta.port, use_tls=use_tls, tls=self.tls,
                proxy=self.proxy, timeouts=self.timeouts)
            await conn.open()
            try:
                await conn.send_bytes(req.serialize())
                resp = await conn.read_response(req.method)
            finally:
                await conn.close()
            last_resp = resp
            try:
                for ic in reversed(self.interceptors):
                    resp = await ic.after_receive(req, resp)
                return resp
            except RetrySignal:
                continue
        return last_resp
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/transport/test_engine_send.py -v`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add penpine/transport/interceptor.py penpine/transport/engine.py tests/transport/test_engine_send.py
git commit -c commit.gpgsign=false -m "feat: add interceptor seam and Engine.send with retry loop"
```

---

## Task 8: Engine.send_many (bounded concurrency)

**Files:**
- Modify: `penpine/transport/engine.py`
- Test: `tests/transport/test_engine_many.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/transport/test_engine_many.py
import asyncio
from penpine.core.message import Request
from penpine.core.parse.http_parser import parse_response
from penpine.transport.engine import Engine


class CountingConn:
    live = 0
    peak = 0

    def __init__(self, host, port, *, use_tls, tls, proxy, timeouts):
        self.port = port

    async def open(self):
        CountingConn.live += 1
        CountingConn.peak = max(CountingConn.peak, CountingConn.live)
        await asyncio.sleep(0.01)
        return self

    async def send_bytes(self, data):
        pass

    async def read_response(self, method="GET"):
        return parse_response(
            f"HTTP/1.1 200 OK\r\nContent-Length: 1\r\n\r\n{self.port % 10}".encode())

    async def close(self):
        CountingConn.live -= 1


async def test_send_many_preserves_order():
    reqs = [Request.from_url(f"http://h:{8000+i}/") for i in range(5)]
    engine = Engine(connection_factory=CountingConn)
    resps = await engine.send_many(reqs)
    assert [r.status_code for r in resps] == [200] * 5
    assert len(resps) == 5


async def test_send_many_respects_concurrency_limit():
    CountingConn.live = 0
    CountingConn.peak = 0
    reqs = [Request.from_url(f"http://h:{8000+i}/") for i in range(10)]
    engine = Engine(max_concurrency=3, connection_factory=CountingConn)
    await engine.send_many(reqs)
    assert CountingConn.peak <= 3


async def test_send_many_return_exceptions():
    class Boom:
        def __init__(self, *a, **k):
            pass

        async def open(self):
            raise RuntimeError("boom")

        async def close(self):
            pass

    reqs = [Request.from_url("http://h:8080/")]
    engine = Engine(connection_factory=Boom)
    results = await engine.send_many(reqs, return_exceptions=True)
    assert isinstance(results[0], RuntimeError)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/transport/test_engine_many.py -v`
Expected: FAIL — `send_many` missing.

- [ ] **Step 3: Write minimal implementation**

Add `import asyncio` at the top of `penpine/transport/engine.py` (below `from __future__ import annotations`), and add this method to `class Engine` (after `send`):

```python
    async def send_many(self, requests, *, return_exceptions=False):
        sem = asyncio.Semaphore(self.max_concurrency)

        async def one(req):
            async with sem:
                return await self.send(req)

        return await asyncio.gather(
            *(one(r) for r in requests), return_exceptions=return_exceptions)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/transport/test_engine_many.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add penpine/transport/engine.py tests/transport/test_engine_many.py
git commit -c commit.gpgsign=false -m "feat: add Engine.send_many with bounded concurrency"
```

---

## Task 9: Sync facade

**Files:**
- Modify: `penpine/transport/engine.py`
- Test: `tests/transport/test_engine_sync.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/transport/test_engine_sync.py
from penpine.core.message import Request
from penpine.core.parse.http_parser import parse_response
from penpine.transport.engine import Engine


class StubConn:
    def __init__(self, host, port, *, use_tls, tls, proxy, timeouts):
        pass

    async def open(self):
        return self

    async def send_bytes(self, data):
        pass

    async def read_response(self, method="GET"):
        return parse_response(b"HTTP/1.1 201 Created\r\nContent-Length: 0\r\n\r\n")

    async def close(self):
        pass


def test_send_sync_blocks_and_returns_result():
    # NOTE: a plain (non-async) test fn — there is no running event loop here.
    req = Request.from_url("http://h:8080/")
    engine = Engine(connection_factory=StubConn)
    try:
        resp = engine.send_sync(req)
        assert resp.status_code == 201
        resp2 = engine.send_many_sync([req, req])
        assert [r.status_code for r in resp2] == [201, 201]
    finally:
        engine.close()


def test_engine_context_manager_closes_loop():
    req = Request.from_url("http://h:8080/")
    with Engine(connection_factory=StubConn) as engine:
        assert engine.send_sync(req).status_code == 201
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/transport/test_engine_sync.py -v`
Expected: FAIL — `send_sync` missing.

- [ ] **Step 3: Write minimal implementation**

Add `import threading` at the top of `penpine/transport/engine.py` (with the other imports). In `Engine.__init__`, add these two lines at the end:

```python
        self._loop = None
        self._loop_thread = None
```

Then add these methods to `class Engine`:

```python
    def _ensure_loop(self):
        if self._loop is None:
            self._loop = asyncio.new_event_loop()
            self._loop_thread = threading.Thread(
                target=self._loop.run_forever, daemon=True)
            self._loop_thread.start()

    def send_sync(self, request):
        self._ensure_loop()
        future = asyncio.run_coroutine_threadsafe(self.send(request), self._loop)
        return future.result()

    def send_many_sync(self, requests, *, return_exceptions=False):
        self._ensure_loop()
        future = asyncio.run_coroutine_threadsafe(
            self.send_many(requests, return_exceptions=return_exceptions), self._loop)
        return future.result()

    def close(self):
        if self._loop is not None:
            self._loop.call_soon_threadsafe(self._loop.stop)
            self._loop_thread.join(timeout=2)
            self._loop.close()
            self._loop = None
            self._loop_thread = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/transport/test_engine_sync.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add penpine/transport/engine.py tests/transport/test_engine_sync.py
git commit -c commit.gpgsign=false -m "feat: add synchronous facade to Engine"
```

---

## Task 10: Public API + localhost integration tests

**Files:**
- Modify: `penpine/transport/__init__.py`, `penpine/__init__.py`
- Test: `tests/transport/test_public_api.py`, `tests/transport/test_integration.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/transport/test_public_api.py
import penpine
from penpine.transport import (
    Engine, Connection, TLSConfig, ProxyConfig, Timeouts, Interceptor, RetrySignal,
)


def test_transport_exports_exist():
    assert all([Engine, Connection, TLSConfig, ProxyConfig, Timeouts,
                Interceptor, RetrySignal])


def test_top_level_reexports_engine():
    assert hasattr(penpine, "Engine")
    assert penpine.Engine is Engine
```

```python
# tests/transport/test_integration.py
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

import penpine
from penpine.transport.engine import Engine


@pytest.fixture()
def http_server():
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            body = b"hello-from-server"
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    yield host, port
    server.shutdown()


def test_real_http_round_trip(http_server):
    host, port = http_server
    req = penpine.Request.from_url(f"http://{host}:{port}/")
    with Engine() as engine:
        resp = engine.send_sync(req)
    assert resp.status_code == 200
    assert resp.body.raw == b"hello-from-server"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/transport/test_public_api.py tests/transport/test_integration.py -v`
Expected: FAIL — transport exports / `penpine.Engine` missing.

- [ ] **Step 3: Write minimal implementation**

```python
# penpine/transport/__init__.py
"""Penpine L1 transport engine."""
from penpine.transport.connection import Connection
from penpine.transport.engine import Engine
from penpine.transport.interceptor import Interceptor, RetrySignal
from penpine.transport.proxy import ProxyConfig
from penpine.transport.timeouts import Timeouts
from penpine.transport.tls import TLSConfig
from penpine.transport.exceptions import (
    TransportError, ConnectError, TLSError, ProxyError,
    ReadTimeout, IncompleteResponseError,
)

__all__ = [
    "Engine", "Connection", "TLSConfig", "ProxyConfig", "Timeouts",
    "Interceptor", "RetrySignal", "TransportError", "ConnectError",
    "TLSError", "ProxyError", "ReadTimeout", "IncompleteResponseError",
]
```

Then add to `penpine/__init__.py` — add this import after the existing imports and extend `__all__`:

```python
from penpine.transport.engine import Engine
from penpine.transport.connection import Connection
```

Change the `__all__` list in `penpine/__init__.py` to include the two new names:

```python
__all__ = [
    "Request", "Response", "RequestBuilder", "Headers", "Body",
    "configure_logging", "get_logger",
    "Engine", "Connection",
]
```

- [ ] **Step 4: Run the FULL suite**

Run: `python -m pytest -q`
Expected: PASS — all L0 + L1 tests green (no failures, no errors).

- [ ] **Step 5: Commit**

```bash
git add penpine/transport/__init__.py penpine/__init__.py tests/transport/test_public_api.py tests/transport/test_integration.py
git commit -c commit.gpgsign=false -m "feat: expose L1 transport public API + integration tests"
```

---

## Self-Review Notes (against the spec)

- **§3 module layout** → Tasks 0–10 create every listed module.
- **§4 ByteStream** (read/readexactly/readline/write/drain/start_tls/close + Fake + Asyncio + opener) → Task 2.
- **§5 ResponseReader** (content-length, chunked w/ trailers, read-until-EOF, HEAD/204/304, delegates to L0 `parse_response`) → Task 3.
- **§6 TLSConfig** (verify off default, versions/ciphers/cert/alpn) → Task 4.
- **§7 ProxyConfig** (from_url, HTTP CONNECT, SOCKS5 incl. auth) → Task 5.
- **§8 Connection** (open direct/proxy/TLS, send/read/close, ctx mgr, plain-HTTP-via-HTTP-proxy no-CONNECT path) → Task 6.
- **§9 Engine** (meta resolution, before_send/after_receive ordering, RetrySignal loop, absolute-form rewrite, send_many bounded, sync facade) → Tasks 7, 8, 9.
- **§10 interceptors** (Interceptor base + RetrySignal) → Task 7.
- **§11 timeouts/errors** → Task 1 (Timeouts + TransportError hierarchy); timeouts applied in the opener (Task 2) and read path.
- **§12 logging** → modules use `get_logger`; covered as they're written (no separate task — add `get_logger(__name__)` usage where a module performs I/O: stream opener, proxy, connection, engine).
- **§13 testing** → unit tests in every task (FakeByteStream / stub connection_factory); integration tests in Task 10.
- **§14 dependencies** → `pytest-asyncio` added in Task 0.

**Deferred (per spec §2 Non-Goals):** connection pooling/keep-alive reuse, HTTP/2, auth/session logic.

**Timeout scope in this plan (honest note):** only `Timeouts.connect` is enforced in v1 (in `open_asyncio_stream` via `asyncio.wait_for`). `Timeouts.read` and `Timeouts.total` are carried on the dataclass and passed through, but the read path is NOT yet wrapped in `asyncio.timeout`, so `ReadTimeout` is defined but not raised by the core path yet. Wiring read/total enforcement (wrap `read_response` and the whole `send` in `asyncio.timeout`, mapping `TimeoutError`→`ReadTimeout`) is a small, self-contained follow-up task — flag it when L1 lands. This keeps the plan from over-claiming §8/§11.

**Logging note for implementers:** where the spec (§12) calls for logging, add `log = get_logger(__name__)` and emit DEBUG on connect/send/proxy-step and INFO on completed send in `engine.py` and `connection.py`. This is not given its own task; fold it into Tasks 6–7 as you write those modules.
```
