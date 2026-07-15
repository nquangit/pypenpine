"""Async byte-stream abstraction over asyncio, plus a socket-free fake."""

from __future__ import annotations

import asyncio
import contextlib
import socket
import ssl

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
        chunk = bytes(self._buf[self._pos : self._pos + n])
        self._pos += len(chunk)
        return chunk

    async def readexactly(self, n: int) -> bytes:
        end = self._pos + n
        if end > len(self._buf):
            raise IncompleteResponseError(f"expected {n} bytes, got {len(self._buf) - self._pos}")
        chunk = bytes(self._buf[self._pos : end])
        self._pos = end
        return chunk

    async def readline(self) -> bytes:
        idx = self._buf.find(b"\n", self._pos)
        if idx == -1:
            chunk = bytes(self._buf[self._pos :])
            self._pos = len(self._buf)
            return chunk
        chunk = bytes(self._buf[self._pos : idx + 1])
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
            raise IncompleteResponseError(f"expected {n} bytes, got {len(exc.partial)}") from exc

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
        transport = getattr(self._writer, "transport", None)
        if transport is not None and transport.get_extra_info("ssl_object") is not None:
            # TLS one-shot connection: abort instead of a graceful close. A
            # graceful close() — and wait_closed() — drives asyncio's SSL shutdown
            # *flush that reads* (sslproto _start_shutdown -> _do_flush -> _do_read
            # -> sslobj.read), which raises SSLEOFError on OpenSSL 3.x whenever the
            # peer skips a close_notify alert (Burp, Cloudflare, TLS 1.3 session
            # tickets left in the pipe). We already have the full response and
            # never reuse the connection, so a graceful close_notify handshake buys
            # nothing. abort() force-closes with the SSL state set to UNWRAPPED and
            # performs no read; we deliberately do NOT await wait_closed(), because
            # its shutdown read is exactly what raises.
            with contextlib.suppress(Exception):
                transport.abort()
            return
        with contextlib.suppress(Exception):
            self._writer.close()
        with contextlib.suppress(Exception):
            await self._writer.wait_closed()

    @property
    def closed(self) -> bool:
        return self._closed


async def open_asyncio_stream(
    host: str, port: int, timeouts: Timeouts | None = None
) -> AsyncioByteStream:
    """Stream opener over asyncio's memory-BIO SSL. Kept for non-TLS use and as an
    opt-in; NOT the default, because asyncio's SSL read loses an already-received
    response when a peer closes a TLS connection uncleanly (see BlockingByteStream)."""
    timeouts = timeouts or Timeouts()
    try:
        coro = asyncio.open_connection(host, port)
        if timeouts.connect:
            reader, writer = await asyncio.wait_for(coro, timeouts.connect)
        else:
            reader, writer = await coro
    except (TimeoutError, OSError) as exc:
        raise ConnectError(f"failed to connect to {host}:{port}: {exc}") from exc
    return AsyncioByteStream(reader, writer)


class BlockingByteStream(ByteStream):
    """ByteStream over a blocking socket (a *socket* BIO for TLS), driven through
    the event loop's default executor.

    Why not asyncio's SSL: asyncio wraps TLS over a *memory* BIO and, in
    ``sslproto._do_read__copied``, accumulates every record read in one pass and
    only delivers them afterward — so if a later read in that pass raises
    (OpenSSL 3.x raises ``SSLEOFError`` when a peer closes without close_notify),
    the already-decrypted response is discarded with the exception. A socket BIO
    (what curl/browsers use) reads record-by-record: the response is returned,
    and the unclean EOF simply ends the stream. This stream reproduces that
    tolerant behavior and also treats a stray ``SSLEOFError`` on recv as EOF."""

    def __init__(self, sock: socket.socket, *, loop: asyncio.AbstractEventLoop | None = None):
        self._sock = sock
        self._loop = loop or asyncio.get_event_loop()
        self._rbuf = bytearray()
        self._wbuf = bytearray()
        self._eof = False
        self._closed = False

    async def _fill(self) -> bool:
        """Read one chunk into the buffer; return False at end of stream."""
        if self._eof:
            return False
        try:
            chunk = await self._loop.run_in_executor(None, self._sock.recv, 65536)
        except ssl.SSLEOFError:
            chunk = b""  # peer closed TLS without close_notify -> treat as EOF (like curl)
        if not chunk:
            self._eof = True
            return False
        self._rbuf.extend(chunk)
        return True

    async def read(self, n: int) -> bytes:
        while not self._rbuf and await self._fill():
            pass
        chunk = bytes(self._rbuf[:n])
        del self._rbuf[:n]
        return chunk

    async def readexactly(self, n: int) -> bytes:
        while len(self._rbuf) < n and await self._fill():
            pass
        if len(self._rbuf) < n:
            raise IncompleteResponseError(f"expected {n} bytes, got {len(self._rbuf)}")
        chunk = bytes(self._rbuf[:n])
        del self._rbuf[:n]
        return chunk

    async def readline(self) -> bytes:
        while b"\n" not in self._rbuf and await self._fill():
            pass
        idx = self._rbuf.find(b"\n")
        if idx == -1:
            chunk = bytes(self._rbuf)
            self._rbuf.clear()
            return chunk
        chunk = bytes(self._rbuf[: idx + 1])
        del self._rbuf[: idx + 1]
        return chunk

    def write(self, data: bytes) -> None:
        self._wbuf.extend(data)

    async def drain(self) -> None:
        if not self._wbuf:
            return
        data = bytes(self._wbuf)
        self._wbuf.clear()
        await self._loop.run_in_executor(None, self._sock.sendall, data)

    async def start_tls(self, ctx, server_hostname) -> None:
        def _wrap() -> ssl.SSLSocket:
            return ctx.wrap_socket(self._sock, server_hostname=server_hostname)

        self._sock = await self._loop.run_in_executor(None, _wrap)

    async def close(self) -> None:
        self._closed = True
        with contextlib.suppress(Exception):
            await self._loop.run_in_executor(None, self._sock.close)

    @property
    def closed(self) -> bool:
        return self._closed


async def open_blocking_stream(
    host: str, port: int, timeouts: Timeouts | None = None
) -> BlockingByteStream:
    """Default stream opener: a blocking socket driven via the loop's executor.

    Uses a socket BIO for TLS so an unclean close (peer skips close_notify, common
    through proxies like Burp / via Cloudflare / with TLS 1.3 tickets) does not
    discard an already-received response — matching curl. Concurrency stays bounded
    by the Engine's `max_concurrency`; each in-flight request uses executor threads."""
    timeouts = timeouts or Timeouts()
    loop = asyncio.get_event_loop()
    try:
        sock = await loop.run_in_executor(
            None, socket.create_connection, (host, port), timeouts.connect
        )
    except (TimeoutError, OSError) as exc:
        raise ConnectError(f"failed to connect to {host}:{port}: {exc}") from exc
    sock.settimeout(None)  # blocking recv/send; read timeout is applied by Connection
    return BlockingByteStream(sock, loop=loop)
