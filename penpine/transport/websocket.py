"""WebSocket client (RFC 6455) over penpine's transport."""

from __future__ import annotations

import asyncio
import base64
import contextlib
import hashlib
import os
import threading
from dataclasses import dataclass
from urllib.parse import urlsplit

from penpine._sync import run_on_loop
from penpine.core.body.base import Body
from penpine.core.headers import Headers
from penpine.core.message import Response
from penpine.core.parse.http_parser import parse_response
from penpine.transport.connection import Connection
from penpine.transport.exceptions import WebSocketError, WebSocketHandshakeError
from penpine.transport.reader import _read_head
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


async def ws_connect(
    url, *, headers=None, subprotocols=None, tls=None, proxy=None, timeouts=None, auto_pong=True
) -> WebSocketConnection:
    scheme, host, port, target = _parse_ws_url(url)
    conn = Connection(
        host, port, use_tls=(scheme == "wss"), tls=tls, proxy=proxy, timeouts=timeouts
    )
    await conn.open()
    try:
        key = _new_key()
        hostport = f"{host}:{port}"
        await conn.send_bytes(
            _build_handshake(hostport, target, key, headers=headers, subprotocols=subprotocols)
        )
        read_head = _read_head(conn.stream)
        if conn.timeouts.read:
            head, remainder = await asyncio.wait_for(read_head, conn.timeouts.read)
        else:
            head, remainder = await read_head
        _validate_handshake(parse_response(head), key)
        return WebSocketConnection(conn, initial_buffer=remainder, auto_pong=auto_pong)
    except BaseException:
        await conn.close()
        raise


def ws_connect_sync(url, **kwargs) -> WebSocketConnection:
    loop = asyncio.new_event_loop()
    thread = threading.Thread(target=loop.run_forever, daemon=True)
    thread.start()
    try:
        ws = run_on_loop(loop, ws_connect(url, **kwargs))
    except BaseException:
        loop.call_soon_threadsafe(loop.stop)
        thread.join(timeout=2)
        loop.close()
        raise
    ws._bind_loop(loop, thread)
    return ws


@dataclass
class Message:
    kind: str  # "text" | "binary" | "close"
    data: bytes | str = b""
    code: int | None = None
    reason: str | None = None


async def recv_reply(ws, *, recv_count=1, recv_timeout=5.0, content_type="application/json"):
    """Receive up to `recv_count` reply messages (stopping on timeout or a close),
    join their text, and return a synthetic Response(200) — the shape the attack
    validators and flow capture consume."""
    replies: list[str] = []
    for _ in range(recv_count):
        try:
            msg = await asyncio.wait_for(ws.recv(), recv_timeout)
        except (TimeoutError, WebSocketError):
            break
        if msg.kind == "close":
            break
        replies.append(
            msg.data if isinstance(msg.data, str) else msg.data.decode("utf-8", "replace")
        )
    return Response(
        status_code=200,
        reason="OK",
        headers=Headers([("Content-Type", content_type)]),
        body=Body("".join(replies).encode("utf-8")),
    )


class WebSocketConnection:
    """Frames over a connection's byte stream. Masks outgoing client frames
    by default; pass ``send_frame(..., auto_mask=False)`` to send a
    genuinely unmasked (or otherwise caller-crafted) frame verbatim, e.g.
    for RFC 6455 client-violation testing.

    Note: a long-lived ``recv()`` call holds an executor thread (via the
    underlying stream read) for the duration of the wait.
    """

    def __init__(self, conn, *, initial_buffer: bytes = b"", auto_pong: bool = True):
        self._conn = conn
        self._buf = bytearray(initial_buffer)
        self._auto_pong = auto_pong
        self._closed = False
        self._loop: asyncio.AbstractEventLoop | None = None
        self._loop_thread: threading.Thread | None = None

    def _require_loop(self) -> asyncio.AbstractEventLoop:
        if self._loop is None:
            raise WebSocketError("the *_sync API requires a connection from ws_connect_sync")
        return self._loop

    @property
    def closed(self) -> bool:
        return self._closed

    async def send_frame(self, frame: Frame, *, auto_mask: bool = True) -> None:
        if self._closed:
            raise WebSocketError("send on a closed WebSocket")
        if auto_mask and frame.mask is None:
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

    def _bind_loop(self, loop, thread) -> None:
        self._loop = loop
        self._loop_thread = thread

    def send_text_sync(self, s: str) -> None:
        run_on_loop(self._require_loop(), self.send_text(s))

    def send_bytes_sync(self, b: bytes) -> None:
        run_on_loop(self._require_loop(), self.send_bytes(b))

    def send_frame_sync(self, frame, *, auto_mask: bool = True) -> None:
        run_on_loop(self._require_loop(), self.send_frame(frame, auto_mask=auto_mask))

    def ping_sync(self, payload: bytes = b"") -> None:
        run_on_loop(self._require_loop(), self.ping(payload))

    def recv_sync(self):
        return run_on_loop(self._require_loop(), self.recv())

    def recv_frame_sync(self):
        return run_on_loop(self._require_loop(), self.recv_frame())

    def close_sync(self, code: int = 1000, reason: str = "") -> None:
        loop = self._require_loop()
        run_on_loop(loop, self.close(code, reason))
        loop.call_soon_threadsafe(loop.stop)
        if self._loop_thread is not None:
            self._loop_thread.join(timeout=2)
        loop.close()
        self._loop = None
