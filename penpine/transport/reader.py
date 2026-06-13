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
