"""HTTP/1.1 body framing: Content-Length and chunked decoding."""

from __future__ import annotations

from penpine.core.headers import Headers
from penpine.exceptions import ParseError


def body_length(headers: Headers) -> tuple[str, int | None]:
    te = headers.get("Transfer-Encoding")
    if te and "chunked" in te.lower():
        return ("chunked", None)
    cl = headers.get("Content-Length")
    if cl is not None:
        try:
            return ("length", int(cl.strip()))
        except ValueError as exc:
            raise ParseError(f"invalid Content-Length: {cl!r}") from exc
    return ("none", 0)


def decode_chunked(data: bytes) -> tuple[bytes, int]:
    """Return (decoded_body, bytes_consumed)."""
    out = bytearray()
    pos = 0
    while True:
        nl = data.find(b"\r\n", pos)
        if nl == -1:
            raise ParseError("incomplete chunk size line", offset=pos)
        size_line = data[pos:nl].split(b";", 1)[0].strip()
        try:
            size = int(size_line, 16)
        except ValueError as exc:
            raise ParseError(f"invalid chunk size {size_line!r}", offset=pos) from exc
        pos = nl + 2
        if size == 0:
            while True:
                end = data.find(b"\r\n", pos)
                if end == -1:
                    raise ParseError("missing final CRLF after last chunk", offset=pos)
                if end == pos:  # blank line terminates trailers
                    return bytes(out), end + 2
                pos = end + 2
        if pos + size + 2 > len(data):
            raise ParseError("incomplete chunk data", offset=pos)
        out += data[pos : pos + size]
        pos += size + 2
