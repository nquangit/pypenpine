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
