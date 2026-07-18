"""WebSocket client (RFC 6455) over penpine's transport."""

from __future__ import annotations

import base64
import contextlib
import hashlib
import os
from dataclasses import dataclass
from urllib.parse import urlsplit

from penpine.transport.exceptions import WebSocketError, WebSocketHandshakeError
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
                opcode=frame.opcode,
                payload=frame.payload,
                fin=frame.fin,
                mask=os.urandom(4),
                rsv1=frame.rsv1,
                rsv2=frame.rsv2,
                rsv3=frame.rsv3,
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
                reason = (
                    frame.payload[2:].decode("utf-8", "replace") if len(frame.payload) > 2 else ""
                )
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
        should_send = not self._closed
        self._closed = True
        if should_send:
            with contextlib.suppress(Exception):
                frame = Frame.close(code, reason)
                await self._conn.send_bytes(
                    Frame(
                        opcode=frame.opcode,
                        payload=frame.payload,
                        fin=frame.fin,
                        mask=os.urandom(4),
                    ).serialize()
                )
        await self._conn.close()
