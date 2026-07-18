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
    raw = _build_handshake(
        "h:6363", "/chat", "KEY==", headers=[("X-A", "1")], subprotocols=["chat"]
    )
    text = raw.decode()
    assert text.startswith("GET /chat HTTP/1.1\r\n")
    for line in (
        "Host: h:6363",
        "Upgrade: websocket",
        "Connection: Upgrade",
        "Sec-WebSocket-Key: KEY==",
        "Sec-WebSocket-Version: 13",
        "Sec-WebSocket-Protocol: chat",
        "X-A: 1",
    ):
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
