# WebSocket Client Core — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A WebSocket client core for penpine — RFC 6455 frame model, the Upgrade handshake, and a `WebSocketConnection` (send/receive/ping/close, async + `_sync`) built on the existing transport (`wss://`, proxy, timeouts).

**Architecture:** `ws_frame.py` holds a byte-faithful, malformable `Frame`. `websocket.py` holds handshake helpers, `WebSocketConnection` (framing over a `Connection`'s byte stream), and `ws_connect(...)`. Reuses `Connection` for socket/TLS/proxy; the handshake reads head-only (a `101` has no body) and seeds the frame buffer with leftover bytes.

**Tech Stack:** Python 3.11+, stdlib (`struct`, `hashlib`, `base64`, `os`, `asyncio`, `urllib.parse`), pytest.

## Global Constraints

- Python 3.11+; new modules keep `from __future__ import annotations`.
- Stdlib only for WS (no third-party ws library) — consistent with penpine's hand-rolled protocol ethos.
- `Frame` is immutable (`@dataclass(frozen=True)`), byte-faithful, and **malformable**: `serialize()` writes exactly the field values; only the receive path validates protocol integrity. Correct client masking is applied by the *connection* at send time, not by `Frame`.
- Reuse the existing `Connection`/blocking-stream transport (do NOT re-implement socket/TLS/proxy). The handshake reads **head-only** (`_read_head`), never `conn.read_response` (which would block reading a bodyless 101 to EOF).
- Every async public method gets a `_sync` twin (reuse `penpine._sync.run_on_loop` + the Engine's loop-management pattern).
- Additive only — no changes to existing HTTP behavior. New `Connection.stream` is a read-only property.
- Ruff lint + format gating; mypy advisory. Commit with `git commit --no-gpg-sign`.

## File Structure

- `penpine/transport/ws_frame.py` — NEW. `Frame`, opcode constants, `IncompleteFrame`.
- `penpine/transport/websocket.py` — NEW. exceptions import, handshake helpers, `Message`, `WebSocketConnection`, `ws_connect`, `_sync` facades.
- `penpine/transport/exceptions.py` — MODIFY. Add `WebSocketError`, `WebSocketHandshakeError`.
- `penpine/transport/connection.py` — MODIFY. Add `stream` read-only property.
- `penpine/transport/__init__.py` + `penpine/__init__.py` — MODIFY. Export the public surface.
- Tests: `tests/transport/test_ws_frame.py`, `tests/transport/test_ws_handshake.py`, `tests/transport/test_ws_connection.py`, `tests/transport/test_websocket.py` (NEW).

---

### Task 1: `Frame` model (`ws_frame.py`)

**Files:**
- Create: `penpine/transport/ws_frame.py`
- Test: `tests/transport/test_ws_frame.py`

**Interfaces:**
- Produces: opcode constants (`OP_TEXT` … `OP_PONG`); `IncompleteFrame(Exception)`; `Frame(opcode, payload=b"", fin=True, mask=None, rsv1/2/3=False)` with `serialize() -> bytes`, `Frame.parse(data) -> tuple[Frame, bytes]`, and `text/binary/ping/pong/close` classmethods.

- [ ] **Step 1: Write the failing test**

Create `tests/transport/test_ws_frame.py`:
```python
import pytest

from penpine.transport.ws_frame import (
    OP_BINARY,
    OP_CLOSE,
    OP_PING,
    OP_TEXT,
    Frame,
    IncompleteFrame,
)


def _roundtrip(frame: Frame) -> Frame:
    parsed, rest = Frame.parse(frame.serialize())
    assert rest == b""
    return parsed


def test_text_frame_roundtrip_unmasked():
    f = Frame.text("hello")
    assert f.opcode == OP_TEXT and f.fin is True and f.payload == b"hello"
    out = _roundtrip(f)
    assert out.opcode == OP_TEXT and out.payload == b"hello" and out.fin is True


def test_masked_frame_roundtrips_to_plaintext_payload():
    f = Frame(opcode=OP_TEXT, payload=b"secret", mask=b"\x01\x02\x03\x04")
    wire = f.serialize()
    assert wire[1] & 0x80  # MASK bit set
    assert b"secret" not in wire  # payload is masked on the wire
    out, rest = Frame.parse(wire)
    assert rest == b"" and out.payload == b"secret"  # parse unmasks


def test_16bit_and_64bit_length_encodings():
    mid = Frame.binary(b"a" * 200)  # >125 -> 16-bit
    assert mid.serialize()[1] & 0x7F == 126
    assert _roundtrip(mid).payload == b"a" * 200
    big = Frame.binary(b"b" * 70000)  # >65535 -> 64-bit
    assert big.serialize()[1] & 0x7F == 127
    assert _roundtrip(big).payload == b"b" * 70000


def test_control_frames():
    assert _roundtrip(Frame.ping(b"pi")).opcode == OP_PING
    c = _roundtrip(Frame.close(1000, "bye"))
    assert c.opcode == OP_CLOSE and c.payload[:2] == (1000).to_bytes(2, "big")


def test_continuation_and_reserved_bits_are_faithful():
    f = Frame(opcode=OP_BINARY, payload=b"x", fin=False, rsv1=True)
    out = _roundtrip(f)
    assert out.fin is False and out.rsv1 is True and out.opcode == OP_BINARY


def test_parse_incomplete_raises():
    full = Frame.text("abcdef").serialize()
    with pytest.raises(IncompleteFrame):
        Frame.parse(full[:1])  # too short for even the header
    with pytest.raises(IncompleteFrame):
        Frame.parse(full[:-2])  # header present, payload truncated


def test_parse_returns_trailing_bytes():
    two = Frame.text("a").serialize() + Frame.text("b").serialize()
    first, rest = Frame.parse(two)
    assert first.payload == b"a"
    second, rest2 = Frame.parse(rest)
    assert second.payload == b"b" and rest2 == b""
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/transport/test_ws_frame.py -q`
Expected: FAIL (`ModuleNotFoundError: penpine.transport.ws_frame`).

- [ ] **Step 3: Create `penpine/transport/ws_frame.py`**

```python
"""RFC 6455 WebSocket frames: byte-faithful and deliberately malformable."""

from __future__ import annotations

import struct
from dataclasses import dataclass

OP_CONTINUATION = 0x0
OP_TEXT = 0x1
OP_BINARY = 0x2
OP_CLOSE = 0x8
OP_PING = 0x9
OP_PONG = 0xA


class IncompleteFrame(Exception):
    """Not enough bytes to parse a full frame yet; read more and retry."""


@dataclass(frozen=True)
class Frame:
    opcode: int
    payload: bytes = b""
    fin: bool = True
    mask: bytes | None = None  # None = unmasked on the wire; 4 bytes = masked
    rsv1: bool = False
    rsv2: bool = False
    rsv3: bool = False

    def serialize(self) -> bytes:
        b0 = (
            (0x80 if self.fin else 0)
            | (0x40 if self.rsv1 else 0)
            | (0x20 if self.rsv2 else 0)
            | (0x10 if self.rsv3 else 0)
            | (self.opcode & 0x0F)
        )
        n = len(self.payload)
        mask_bit = 0x80 if self.mask is not None else 0
        if n <= 125:
            header = bytes([b0, mask_bit | n])
        elif n <= 0xFFFF:
            header = bytes([b0, mask_bit | 126]) + struct.pack("!H", n)
        else:
            header = bytes([b0, mask_bit | 127]) + struct.pack("!Q", n)
        if self.mask is not None:
            key = self.mask
            masked = bytes(b ^ key[i % 4] for i, b in enumerate(self.payload))
            return header + key + masked
        return header + self.payload

    @classmethod
    def parse(cls, data: bytes) -> tuple[Frame, bytes]:
        if len(data) < 2:
            raise IncompleteFrame
        b0, b1 = data[0], data[1]
        fin = bool(b0 & 0x80)
        rsv1, rsv2, rsv3 = bool(b0 & 0x40), bool(b0 & 0x20), bool(b0 & 0x10)
        opcode = b0 & 0x0F
        masked = bool(b1 & 0x80)
        n = b1 & 0x7F
        off = 2
        if n == 126:
            if len(data) < off + 2:
                raise IncompleteFrame
            n = struct.unpack("!H", data[off : off + 2])[0]
            off += 2
        elif n == 127:
            if len(data) < off + 8:
                raise IncompleteFrame
            n = struct.unpack("!Q", data[off : off + 8])[0]
            off += 8
        key = None
        if masked:
            if len(data) < off + 4:
                raise IncompleteFrame
            key = data[off : off + 4]
            off += 4
        if len(data) < off + n:
            raise IncompleteFrame
        payload = data[off : off + n]
        if key is not None:
            payload = bytes(b ^ key[i % 4] for i, b in enumerate(payload))
        frame = cls(
            opcode=opcode, payload=payload, fin=fin, mask=key, rsv1=rsv1, rsv2=rsv2, rsv3=rsv3
        )
        return frame, data[off + n :]

    @classmethod
    def text(cls, s: str, *, fin: bool = True) -> Frame:
        return cls(opcode=OP_TEXT, payload=s.encode("utf-8"), fin=fin)

    @classmethod
    def binary(cls, b: bytes, *, fin: bool = True) -> Frame:
        return cls(opcode=OP_BINARY, payload=b, fin=fin)

    @classmethod
    def ping(cls, payload: bytes = b"") -> Frame:
        return cls(opcode=OP_PING, payload=payload)

    @classmethod
    def pong(cls, payload: bytes = b"") -> Frame:
        return cls(opcode=OP_PONG, payload=payload)

    @classmethod
    def close(cls, code: int = 1000, reason: str = "") -> Frame:
        return cls(opcode=OP_CLOSE, payload=struct.pack("!H", code) + reason.encode("utf-8"))
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/transport/test_ws_frame.py -q`
Expected: PASS (7 tests).

- [ ] **Step 5: Lint + format**

Run: `ruff check penpine/transport/ws_frame.py tests/transport/test_ws_frame.py && ruff format penpine/transport/ws_frame.py tests/transport/test_ws_frame.py`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add penpine/transport/ws_frame.py tests/transport/test_ws_frame.py
git commit --no-gpg-sign -m "feat(transport): add RFC 6455 WebSocket Frame (byte-faithful, malformable)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: WS exceptions + handshake helpers

**Files:**
- Modify: `penpine/transport/exceptions.py`
- Create: `penpine/transport/websocket.py` (handshake helpers only in this task)
- Test: `tests/transport/test_ws_handshake.py`

**Interfaces:**
- Produces: `WebSocketError(TransportError)`, `WebSocketHandshakeError(WebSocketError)`; and in `websocket.py`: `_new_key() -> str`, `_accept_for(key: str) -> str`, `_parse_ws_url(url) -> tuple[str, str, int, str]` (scheme, host, port, target), `_build_handshake(host, target, key, *, headers, subprotocols) -> bytes`, `_validate_handshake(response, key) -> None`.

- [ ] **Step 1: Add the exceptions**

In `penpine/transport/exceptions.py`, after `IncompleteResponseError`:
```python
class WebSocketError(TransportError):
    """WebSocket protocol error."""


class WebSocketHandshakeError(WebSocketError):
    """The WebSocket upgrade handshake was rejected or invalid."""

    def __init__(self, message: str, response=None):
        super().__init__(message)
        self.response = response
```

- [ ] **Step 2: Write the failing test**

Create `tests/transport/test_ws_handshake.py`:
```python
import pytest

from penpine.core.parse.http_parser import parse_response
from penpine.transport.exceptions import WebSocketHandshakeError
from penpine.transport.websocket import (
    _accept_for,
    _build_handshake,
    _parse_ws_url,
    _validate_handshake,
)


def test_accept_for_matches_rfc6455_example():
    # RFC 6455 §1.3 worked example
    assert _accept_for("dGhlIHNhbXBsZSBub25jZQ==") == "s3pPLMBiTxaQ9kYGzzhZRbK+xOo="


def test_parse_ws_url():
    assert _parse_ws_url("ws://h/chat") == ("ws", "h", 80, "/chat")
    assert _parse_ws_url("wss://h:6363/a?b=1") == ("wss", "h", 6363, "/a?b=1")
    assert _parse_ws_url("wss://h") == ("wss", "h", 443, "/")


def test_build_handshake_has_required_headers():
    raw = _build_handshake("h:6363", "/chat", "KEY==", headers=[("X-A", "1")], subprotocols=["chat"])
    text = raw.decode()
    assert text.startswith("GET /chat HTTP/1.1\r\n")
    for line in ("Host: h:6363", "Upgrade: websocket", "Connection: Upgrade",
                 "Sec-WebSocket-Key: KEY==", "Sec-WebSocket-Version: 13",
                 "Sec-WebSocket-Protocol: chat", "X-A: 1"):
        assert f"{line}\r\n" in text
    assert text.endswith("\r\n\r\n")


def test_validate_handshake_accepts_valid_101():
    key = "dGhlIHNhbXBsZSBub25jZQ=="
    resp = parse_response(
        b"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\n"
        b"Connection: Upgrade\r\nSec-WebSocket-Accept: s3pPLMBiTxaQ9kYGzzhZRbK+xOo=\r\n\r\n"
    )
    _validate_handshake(resp, key)  # does not raise


def test_validate_handshake_rejects_non_101():
    resp = parse_response(b"HTTP/1.1 400 Bad Request\r\nContent-Length: 0\r\n\r\n")
    with pytest.raises(WebSocketHandshakeError):
        _validate_handshake(resp, "k")


def test_validate_handshake_rejects_bad_accept():
    resp = parse_response(
        b"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\n"
        b"Connection: Upgrade\r\nSec-WebSocket-Accept: WRONG\r\n\r\n"
    )
    with pytest.raises(WebSocketHandshakeError):
        _validate_handshake(resp, "dGhlIHNhbXBsZSBub25jZQ==")
```

- [ ] **Step 3: Run to verify it fails**

Run: `pytest tests/transport/test_ws_handshake.py -q`
Expected: FAIL (`ModuleNotFoundError: penpine.transport.websocket`).

- [ ] **Step 4: Create `penpine/transport/websocket.py` with the handshake helpers**

```python
"""WebSocket client (RFC 6455) over penpine's transport."""

from __future__ import annotations

import base64
import hashlib
import os
from urllib.parse import urlsplit

from penpine.transport.exceptions import WebSocketHandshakeError

_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


def _new_key() -> str:
    return base64.b64encode(os.urandom(16)).decode("ascii")


def _accept_for(key: str) -> str:
    digest = hashlib.sha1((key + _GUID).encode("ascii")).digest()
    return base64.b64encode(digest).decode("ascii")


def _parse_ws_url(url: str) -> tuple[str, str, int, str]:
    parts = urlsplit(url)
    scheme = parts.scheme.lower()
    host = parts.hostname or ""
    port = parts.port or (443 if scheme == "wss" else 80)
    target = parts.path or "/"
    if parts.query:
        target += "?" + parts.query
    return scheme, host, port, target


def _build_handshake(host, target, key, *, headers=None, subprotocols=None) -> bytes:
    lines = [
        f"GET {target} HTTP/1.1",
        f"Host: {host}",
        "Upgrade: websocket",
        "Connection: Upgrade",
        f"Sec-WebSocket-Key: {key}",
        "Sec-WebSocket-Version: 13",
    ]
    if subprotocols:
        lines.append("Sec-WebSocket-Protocol: " + ", ".join(subprotocols))
    for name, value in headers or []:
        lines.append(f"{name}: {value}")
    return ("\r\n".join(lines) + "\r\n\r\n").encode("latin-1")


def _validate_handshake(response, key: str) -> None:
    status = getattr(response, "status_code", None)
    if status != 101:
        raise WebSocketHandshakeError(f"expected 101, got {status}", response)
    headers = response.headers
    if (headers.get("Upgrade", "") or "").lower() != "websocket":
        raise WebSocketHandshakeError("missing/invalid Upgrade header", response)
    if "upgrade" not in (headers.get("Connection", "") or "").lower():
        raise WebSocketHandshakeError("missing/invalid Connection header", response)
    if headers.get("Sec-WebSocket-Accept") != _accept_for(key):
        raise WebSocketHandshakeError("Sec-WebSocket-Accept mismatch", response)
```

- [ ] **Step 5: Run to verify it passes**

Run: `pytest tests/transport/test_ws_handshake.py -q`
Expected: PASS (6 tests).

- [ ] **Step 6: Lint + format**

Run: `ruff check penpine/transport/exceptions.py penpine/transport/websocket.py tests/transport/test_ws_handshake.py && ruff format penpine/transport/exceptions.py penpine/transport/websocket.py tests/transport/test_ws_handshake.py`
Expected: clean.

- [ ] **Step 7: Commit**

```bash
git add penpine/transport/exceptions.py penpine/transport/websocket.py tests/transport/test_ws_handshake.py
git commit --no-gpg-sign -m "feat(transport): WebSocket handshake helpers + exceptions

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: `WebSocketConnection` (framing over a byte stream)

**Files:**
- Modify: `penpine/transport/websocket.py`
- Test: `tests/transport/test_ws_connection.py`

**Interfaces:**
- Consumes: `Frame` (Task 1); a duck-typed connection exposing `stream.read(n)`, `send_bytes(data)`, `close()`, `closed`.
- Produces: `Message(kind, data, code=None, reason=None)`; `WebSocketConnection(conn, *, initial_buffer=b"", auto_pong=True)` with `send_text/send_bytes/send_frame/recv/recv_frame/ping/close` and `closed`.

- [ ] **Step 1: Write the failing test**

Create `tests/transport/test_ws_connection.py`:
```python
from penpine.transport.stream import FakeByteStream
from penpine.transport.ws_frame import OP_PING, Frame
from penpine.transport.websocket import Message, WebSocketConnection


class _Conn:
    """Duck-typed connection over a FakeByteStream; captures sent bytes."""

    def __init__(self, incoming: bytes = b""):
        self.stream = FakeByteStream(incoming)
        self.sent = bytearray()
        self._closed = False

    async def send_bytes(self, data: bytes) -> None:
        self.sent.extend(data)

    async def close(self) -> None:
        self._closed = True

    @property
    def closed(self) -> bool:
        return self._closed


async def test_send_text_masks_the_frame():
    conn = _Conn()
    ws = WebSocketConnection(conn)
    await ws.send_text("hello")
    frame, rest = Frame.parse(bytes(conn.sent))
    assert bytes(conn.sent)[1] & 0x80  # client frame is masked
    assert frame.payload == b"hello" and rest == b""


async def test_send_frame_with_explicit_mask_is_sent_verbatim():
    conn = _Conn()
    ws = WebSocketConnection(conn)
    # a caller-supplied UNMASKED frame (malformed client frame) is sent as-is
    await ws.send_frame(Frame.text("raw"))  # no mask set -> connection masks it
    assert bytes(conn.sent)[1] & 0x80
    conn.sent.clear()
    await ws.send_frame(Frame(opcode=1, payload=b"raw", mask=b"\x00\x00\x00\x00"))
    assert bytes(conn.sent)[1] & 0x80  # verbatim (already had a mask)


async def test_recv_reassembles_continuation_frames():
    server = (
        Frame(opcode=1, payload=b"he", fin=False).serialize()
        + Frame(opcode=0, payload=b"llo", fin=True).serialize()
    )
    ws = WebSocketConnection(_Conn(server))
    msg = await ws.recv()
    assert msg == Message(kind="text", data="hello")


async def test_recv_auto_pongs_ping_then_returns_message():
    server = Frame.ping(b"pi").serialize() + Frame.text("hi").serialize()
    conn = _Conn(server)
    ws = WebSocketConnection(conn)
    msg = await ws.recv()
    assert msg.kind == "text" and msg.data == "hi"
    pong, _ = Frame.parse(bytes(conn.sent))  # auto-pong was sent
    assert pong.opcode == 0xA and pong.payload == b"pi"


async def test_recv_frame_returns_raw_ping_when_auto_pong_disabled():
    ws = WebSocketConnection(_Conn(Frame.ping(b"x").serialize()), auto_pong=False)
    f = await ws.recv_frame()
    assert f.opcode == OP_PING and f.payload == b"x"


async def test_recv_close_marks_closed_and_returns_close_message():
    ws = WebSocketConnection(_Conn(Frame.close(1001, "bye").serialize()))
    msg = await ws.recv()
    assert msg.kind == "close" and msg.code == 1001 and msg.reason == "bye"
    assert ws.closed is True


async def test_recv_frame_reads_across_partial_stream_chunks():
    # FakeByteStream returns up to n bytes; a frame split across reads still parses
    ws = WebSocketConnection(_Conn(Frame.text("abcdefgh").serialize()))
    f = await ws.recv_frame()
    assert f.payload == b"abcdefgh"
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/transport/test_ws_connection.py -q`
Expected: FAIL (`cannot import name 'Message'` / `WebSocketConnection`).

- [ ] **Step 3: Add `Message` + `WebSocketConnection` to `websocket.py`**

Add imports at the top of `websocket.py`:
```python
import os  # already imported
import struct
from dataclasses import dataclass

from penpine.transport.exceptions import WebSocketError
from penpine.transport.ws_frame import (
    OP_BINARY,
    OP_CLOSE,
    OP_CONTINUATION,
    OP_PING,
    OP_PONG,
    OP_TEXT,
    Frame,
    IncompleteFrame,
)
```
Append:
```python
@dataclass
class Message:
    kind: str  # "text" | "binary" | "close"
    data: bytes | str = b""
    code: int | None = None
    reason: str | None = None


class WebSocketConnection:
    """Frames over a connection's byte stream. Masks outgoing client frames
    (unless the caller supplied a mask, for malformed-frame testing)."""

    def __init__(self, conn, *, initial_buffer: bytes = b"", auto_pong: bool = True):
        self._conn = conn
        self._buf = bytearray(initial_buffer)
        self._auto_pong = auto_pong
        self._closed = False

    @property
    def closed(self) -> bool:
        return self._closed

    async def send_frame(self, frame: Frame) -> None:
        if self._closed:
            raise WebSocketError("send on a closed WebSocket")
        if frame.mask is None:
            frame = Frame(
                opcode=frame.opcode, payload=frame.payload, fin=frame.fin,
                mask=os.urandom(4), rsv1=frame.rsv1, rsv2=frame.rsv2, rsv3=frame.rsv3,
            )
        await self._conn.send_bytes(frame.serialize())

    async def send_text(self, s: str) -> None:
        await self.send_frame(Frame.text(s))

    async def send_bytes(self, b: bytes) -> None:
        await self.send_frame(Frame.binary(b))

    async def ping(self, payload: bytes = b"") -> None:
        await self.send_frame(Frame.ping(payload))

    async def recv_frame(self) -> Frame:
        while True:
            try:
                frame, rest = Frame.parse(bytes(self._buf))
            except IncompleteFrame:
                chunk = await self._conn.stream.read(65536)
                if not chunk:
                    raise WebSocketError("connection closed mid-frame") from None
                self._buf.extend(chunk)
                continue
            del self._buf[: len(self._buf) - len(rest)]
            return frame

    async def recv(self) -> Message:
        data = bytearray()
        msg_op = None
        while True:
            frame = await self.recv_frame()
            if frame.opcode == OP_PING:
                if self._auto_pong:
                    await self.send_frame(Frame.pong(frame.payload))
                continue
            if frame.opcode == OP_PONG:
                continue
            if frame.opcode == OP_CLOSE:
                code = int.from_bytes(frame.payload[:2], "big") if len(frame.payload) >= 2 else None
                reason = frame.payload[2:].decode("utf-8", "replace") if len(frame.payload) > 2 else ""
                self._closed = True
                return Message(kind="close", data=b"", code=code, reason=reason)
            if frame.opcode in (OP_TEXT, OP_BINARY):
                msg_op = frame.opcode
                data.extend(frame.payload)
            elif frame.opcode == OP_CONTINUATION:
                data.extend(frame.payload)
            if frame.fin:
                if msg_op == OP_TEXT:
                    return Message(kind="text", data=bytes(data).decode("utf-8", "replace"))
                return Message(kind="binary", data=bytes(data))

    async def close(self, code: int = 1000, reason: str = "") -> None:
        if not self._closed:
            self._closed = True
            try:
                await self.send_frame(Frame.close(code, reason))
            finally:
                await self._conn.close()
```
Note: `recv_frame`'s buffer trim uses `len(self._buf) - len(rest)` (bytes consumed) so it works whether or not `_buf` was a copy. `struct` import may be unused here — remove it if ruff flags F401 (close-code packing is in `Frame.close`).

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/transport/test_ws_connection.py -q`
Expected: PASS (7 tests).

- [ ] **Step 5: Lint + format**

Run: `ruff check penpine/transport/websocket.py tests/transport/test_ws_connection.py && ruff format penpine/transport/websocket.py tests/transport/test_ws_connection.py`
Expected: clean (remove any unused import ruff flags).

- [ ] **Step 6: Commit**

```bash
git add penpine/transport/websocket.py tests/transport/test_ws_connection.py
git commit --no-gpg-sign -m "feat(transport): WebSocketConnection framing (send/recv/reassembly/auto-pong)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 4: `ws_connect`, `Connection.stream`, sync facades, exports, end-to-end

**Files:**
- Modify: `penpine/transport/connection.py`, `penpine/transport/websocket.py`, `penpine/transport/__init__.py`, `penpine/__init__.py`
- Test: `tests/transport/test_websocket.py`

**Interfaces:**
- Consumes: `Connection`, `_read_head`, `parse_response`, handshake helpers, `WebSocketConnection`, `run_on_loop`.
- Produces: `Connection.stream` property; `ws_connect(...)` (async) + `ws_connect_sync(...)`; `WebSocketConnection` `_sync` twins; public exports.

- [ ] **Step 1: Add `Connection.stream`**

In `penpine/transport/connection.py`, add after the `closed` property:
```python
    @property
    def stream(self):
        """The underlying ByteStream (available after open()). For WebSocket frame I/O."""
        return self._stream
```

- [ ] **Step 2: Write the failing end-to-end test**

Create `tests/transport/test_websocket.py`:
```python
import base64
import hashlib
import socket
import struct
import threading

from penpine.transport.websocket import ws_connect, ws_connect_sync

_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


def _server_read_frame(conn):
    b0 = conn.recv(1)[0]
    b1 = conn.recv(1)[0]
    opcode = b0 & 0x0F
    masked = bool(b1 & 0x80)
    n = b1 & 0x7F
    if n == 126:
        n = struct.unpack("!H", conn.recv(2))[0]
    elif n == 127:
        n = struct.unpack("!Q", conn.recv(8))[0]
    key = conn.recv(4) if masked else b"\x00\x00\x00\x00"
    payload = bytearray(conn.recv(n))
    for i in range(len(payload)):
        payload[i] ^= key[i % 4]
    return opcode, bytes(payload)


def _server_send(conn, opcode, payload):
    header = bytes([0x80 | opcode])
    n = len(payload)
    if n <= 125:
        header += bytes([n])
    elif n <= 0xFFFF:
        header += bytes([126]) + struct.pack("!H", n)
    else:
        header += bytes([127]) + struct.pack("!Q", n)
    conn.sendall(header + payload)  # server frames are unmasked


def _echo_server():
    """A minimal WS echo server; returns (host, port). One connection, echoes text."""
    srv = socket.socket()
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    host, port = srv.getsockname()

    def serve():
        conn, _ = srv.accept()
        req = b""
        while b"\r\n\r\n" not in req:
            req += conn.recv(1024)
        key = ""
        for line in req.decode("latin-1").split("\r\n"):
            if line.lower().startswith("sec-websocket-key:"):
                key = line.split(":", 1)[1].strip()
        accept = base64.b64encode(hashlib.sha1((key + _GUID).encode()).digest()).decode()
        conn.sendall(
            b"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\n"
            b"Connection: Upgrade\r\nSec-WebSocket-Accept: " + accept.encode() + b"\r\n\r\n"
        )
        opcode, payload = _server_read_frame(conn)  # the client's message
        _server_send(conn, 0x9, b"png")  # a ping (client should auto-pong)
        _server_send(conn, opcode, payload)  # echo it back
        _server_read_frame(conn)  # the client's auto-pong (drain)
        srv.close()

    threading.Thread(target=serve, daemon=True).start()
    return host, port


async def test_ws_connect_send_recv_echo():
    host, port = _echo_server()
    ws = await ws_connect(f"ws://{host}:{port}/chat")
    try:
        await ws.send_text("hello-ws")
        msg = await ws.recv()  # auto-pongs the server ping, then returns the echo
        assert msg.kind == "text" and msg.data == "hello-ws"
    finally:
        await ws.close()


def test_ws_connect_sync_round_trip():
    host, port = _echo_server()
    ws = ws_connect_sync(f"ws://{host}:{port}/chat")
    try:
        ws.send_text_sync("sync-hi")
        msg = ws.recv_sync()
        assert msg.kind == "text" and msg.data == "sync-hi"
    finally:
        ws.close_sync()
```

- [ ] **Step 3: Run to verify it fails**

Run: `pytest tests/transport/test_websocket.py -q`
Expected: FAIL (`cannot import name 'ws_connect'`).

- [ ] **Step 4: Add `ws_connect` + sync facades to `websocket.py`**

Add imports:
```python
import asyncio
import threading

from penpine.core.parse.http_parser import parse_response
from penpine.transport.connection import Connection
from penpine.transport.reader import _read_head
from penpine._sync import run_on_loop
```
Add `ws_connect` (after `_validate_handshake`):
```python
async def ws_connect(
    url, *, headers=None, subprotocols=None, tls=None, proxy=None, timeouts=None, auto_pong=True
) -> WebSocketConnection:
    scheme, host, port, target = _parse_ws_url(url)
    conn = Connection(host, port, use_tls=(scheme == "wss"), tls=tls, proxy=proxy, timeouts=timeouts)
    await conn.open()
    key = _new_key()
    hostport = f"{host}:{port}"
    await conn.send_bytes(_build_handshake(hostport, target, key, headers=headers, subprotocols=subprotocols))
    read_head = _read_head(conn.stream)
    if conn.timeouts.read:
        head, remainder = await asyncio.wait_for(read_head, conn.timeouts.read)
    else:
        head, remainder = await read_head
    _validate_handshake(parse_response(head), key)
    return WebSocketConnection(conn, initial_buffer=remainder, auto_pong=auto_pong)
```
Add loop-managed `_sync` support. Give `WebSocketConnection` an optional owned loop and `_sync` twins:
```python
    # --- inside WebSocketConnection ---
    def _bind_loop(self, loop, thread) -> None:
        self._loop = loop
        self._loop_thread = thread

    def send_text_sync(self, s: str) -> None:
        run_on_loop(self._loop, self.send_text(s))

    def send_bytes_sync(self, b: bytes) -> None:
        run_on_loop(self._loop, self.send_bytes(b))

    def send_frame_sync(self, frame) -> None:
        run_on_loop(self._loop, self.send_frame(frame))

    def ping_sync(self, payload: bytes = b"") -> None:
        run_on_loop(self._loop, self.ping(payload))

    def recv_sync(self):
        return run_on_loop(self._loop, self.recv())

    def recv_frame_sync(self):
        return run_on_loop(self._loop, self.recv_frame())

    def close_sync(self, code: int = 1000, reason: str = "") -> None:
        run_on_loop(self._loop, self.close(code, reason))
        loop, thread = getattr(self, "_loop", None), getattr(self, "_loop_thread", None)
        if loop is not None:
            loop.call_soon_threadsafe(loop.stop)
            thread.join(timeout=2)
            loop.close()
            self._loop = None
```
(Set `self._loop = None` / `self._loop_thread = None` in `__init__`.)

Add the sync opener:
```python
def ws_connect_sync(url, **kwargs) -> WebSocketConnection:
    loop = asyncio.new_event_loop()
    thread = threading.Thread(target=loop.run_forever, daemon=True)
    thread.start()
    ws = run_on_loop(loop, ws_connect(url, **kwargs))
    ws._bind_loop(loop, thread)
    return ws
```

- [ ] **Step 5: Export the public surface**

In `penpine/transport/__init__.py`: add
```python
from penpine.transport.websocket import Message, WebSocketConnection, ws_connect, ws_connect_sync
from penpine.transport.ws_frame import Frame
from penpine.transport.exceptions import WebSocketError, WebSocketHandshakeError
```
and add `"Frame"`, `"Message"`, `"WebSocketConnection"`, `"ws_connect"`, `"ws_connect_sync"`, `"WebSocketError"`, `"WebSocketHandshakeError"` to `__all__`.
In `penpine/__init__.py`: add `from penpine.transport.websocket import WebSocketConnection, ws_connect, ws_connect_sync` and `from penpine.transport.ws_frame import Frame`; add `"Frame"`, `"WebSocketConnection"`, `"ws_connect"`, `"ws_connect_sync"` to `__all__` (correct import order for ruff/isort).

- [ ] **Step 6: Run to verify it passes**

Run: `pytest tests/transport/test_websocket.py -q`
Expected: PASS (2 tests).

- [ ] **Step 7: Full suite + gates**

Run: `pytest -q && ruff check . && ruff format --check .`
Expected: all pass; ruff clean.

- [ ] **Step 8: Commit**

```bash
git add penpine/transport/connection.py penpine/transport/websocket.py penpine/transport/__init__.py penpine/__init__.py tests/transport/test_websocket.py
git commit --no-gpg-sign -m "feat(transport): ws_connect + sync facades + exports (WebSocket client core)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Self-Review Notes

- **Spec coverage:** Frame model (Component 1) → Task 1; handshake (Component 2) → Task 2; WebSocketConnection (Component 3) → Task 3; transport reuse + `ws_connect` + sync facades + exports (Components C/D) → Task 4. Testing spec → each task's tests + the e2e echo server in Task 4.
- **101-has-no-body:** Task 4 reads head-only via `_read_head` (never `conn.read_response`) and seeds the frame buffer with the leftover bytes — matches the design's key constraint.
- **Malformable frames:** `Frame.serialize` writes field values verbatim; the *connection* masks outgoing frames only when the caller left `mask=None` (Task 3 test `test_send_frame_with_explicit_mask_is_sent_verbatim`).
- **Type/name consistency:** `Frame.parse -> (Frame, bytes)`, `IncompleteFrame` used by `recv_frame`; `WebSocketConnection(conn, initial_buffer=, auto_pong=)` constructed by `ws_connect` (Task 4) exactly as Task 3 defines; `Message(kind, data, code, reason)` returned by `recv` and asserted in tests.
- **Sync facades:** reuse `run_on_loop` + a per-connection owned loop (mirrors `Engine.send_sync`/`close`); `ws_connect_sync` binds the loop into the returned connection.
- **wss:// note:** the plan's e2e test covers `ws://`; a `wss://` self-signed variant is described in the spec — add it in Task 4 if time permits (reuse the openssl-cert pattern from `test_tls.py`). Not gating for the core.
