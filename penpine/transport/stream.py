"""Async byte-stream abstraction over asyncio, plus a socket-free fake."""

from __future__ import annotations

import asyncio
import contextlib

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
        # For a TLS connection, abort() instead of a graceful close(): close()
        # drives asyncio's SSL shutdown *flush that reads* (sslproto _do_flush ->
        # _do_read), which raises SSLEOFError on OpenSSL 3.x when the peer skips
        # close_notify (common through proxies like Burp, and with TLS 1.3 session
        # tickets left in the pipe). We have already read the full response and
        # never reuse a one-shot connection, so a graceful close_notify handshake
        # buys nothing — aborting skips the shutdown read entirely.
        transport = getattr(self._writer, "transport", None)
        with contextlib.suppress(Exception):
            if transport is not None and transport.get_extra_info("ssl_object") is not None:
                transport.abort()
            else:
                self._writer.close()
        with contextlib.suppress(Exception):
            await self._writer.wait_closed()

    @property
    def closed(self) -> bool:
        return self._closed


async def open_asyncio_stream(
    host: str, port: int, timeouts: Timeouts | None = None
) -> AsyncioByteStream:
    """Default stream opener: connect a TCP socket and wrap it."""
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
