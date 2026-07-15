"""BlockingByteStream: socket-BIO stream that tolerates an unclean TLS close.

asyncio's memory-BIO SSL discards an already-received response when a peer closes
a TLS connection without close_notify (OpenSSL 3.x raises SSLEOFError mid-read).
A socket BIO — what curl uses — returns the buffered data and ends the stream.
This stream reproduces that, and also treats a stray SSLEOFError on recv as EOF.
"""

import socket
import ssl

import pytest

from penpine.transport.exceptions import IncompleteResponseError
from penpine.transport.stream import BlockingByteStream, open_blocking_stream


async def test_readline_readexactly_read_over_socketpair():
    a, b = socket.socketpair()
    try:
        b.sendall(b"line1\r\nHELLOWORLD")
        b.close()  # EOF after the data
        s = BlockingByteStream(a)
        assert await s.readline() == b"line1\r\n"
        assert await s.readexactly(5) == b"HELLO"
        assert await s.read(100) == b"WORLD"
        assert await s.read(100) == b""  # end of stream
    finally:
        a.close()


async def test_readexactly_short_read_raises_incomplete():
    a, b = socket.socketpair()
    try:
        b.sendall(b"abc")
        b.close()
        s = BlockingByteStream(a)
        with pytest.raises(IncompleteResponseError):
            await s.readexactly(10)
    finally:
        a.close()


async def test_write_then_drain_sends():
    a, b = socket.socketpair()
    try:
        s = BlockingByteStream(a)
        s.write(b"hel")
        s.write(b"lo")
        await s.drain()
        assert b.recv(100) == b"hello"
    finally:
        a.close()
        b.close()


async def test_ssleof_on_recv_is_treated_as_eof():
    class _Sock:
        def recv(self, n):
            raise ssl.SSLEOFError("EOF occurred in violation of protocol")

        def close(self):
            pass

    s = BlockingByteStream(_Sock())  # type: ignore[arg-type]
    assert await s.read(100) == b""  # tolerated as a clean end of stream
    assert await s.readline() == b""


async def test_close_marks_closed():
    a, b = socket.socketpair()
    try:
        s = BlockingByteStream(a)
        assert s.closed is False
        await s.close()
        assert s.closed is True
    finally:
        b.close()


async def test_open_blocking_stream_connects_and_reads():
    srv = socket.socket()
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port = srv.getsockname()[1]

    import threading

    def serve():
        conn, _ = srv.accept()
        conn.recv(1024)
        conn.sendall(b"pong")
        conn.close()

    threading.Thread(target=serve, daemon=True).start()

    stream = await open_blocking_stream("127.0.0.1", port)
    try:
        stream.write(b"ping")
        await stream.drain()
        assert await stream.read(100) == b"pong"
    finally:
        await stream.close()
        srv.close()
