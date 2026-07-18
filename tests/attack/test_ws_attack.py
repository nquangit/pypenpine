import base64
import hashlib
import re
import socket
import struct
import threading

from penpine.attack.types import AttackType
from penpine.attack.websocket import (
    WebSocketSender,
    run_ws_attack,
    run_ws_attack_sync,
    ws_injection_points,
    ws_message_request,
)

_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


def test_ws_message_request_json_yields_json_points():
    req = ws_message_request("ws://h:9/chat", '{"action":"get","id":"1"}')
    exprs = {p.expr for p in ws_injection_points(req)}
    assert exprs == {"json:$.action", "json:$.id"}
    assert all(p.kind == "json" for p in ws_injection_points(req))


def test_ws_message_request_text_yields_body_point():
    req = ws_message_request("ws://h/chat", "PING 1", json=False)
    pts = ws_injection_points(req)
    assert len(pts) == 1 and pts[0].expr == "body" and pts[0].kind == "body"
    assert req.replace_at("body", "X").body.text() == "X"


# ---- minimal in-process WS server: handshake, read one frame, reply via handler ----
def _ws_frame_read(conn):
    b0 = conn.recv(1)[0]
    b1 = conn.recv(1)[0]
    n = b1 & 0x7F
    if n == 126:
        n = struct.unpack("!H", conn.recv(2))[0]
    elif n == 127:
        n = struct.unpack("!Q", conn.recv(8))[0]
    key = conn.recv(4) if b1 & 0x80 else b"\x00\x00\x00\x00"
    payload = bytearray(conn.recv(n))
    for i in range(len(payload)):
        payload[i] ^= key[i % 4]
    return b0 & 0x0F, bytes(payload)


def _ws_frame_send(conn, text):
    data = text.encode()
    header = bytes([0x81])
    n = len(data)
    if n <= 125:
        header += bytes([n])
    elif n <= 0xFFFF:
        header += bytes([126]) + struct.pack("!H", n)
    else:
        header += bytes([127]) + struct.pack("!Q", n)
    conn.sendall(header + data)


def ws_server(handler):
    """handler(message_str) -> reply_str (or None to send nothing). Serves each accepted
    connection on its own thread, so attack runs that open many WebSocket connections
    concurrently (baseline + N mutated payloads) all succeed."""
    srv = socket.socket()
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", 0))
    srv.listen(128)
    host, port = srv.getsockname()

    def handle(conn):
        try:
            req = b""
            while b"\r\n\r\n" not in req:
                chunk = conn.recv(1024)
                if not chunk:
                    return
                req += chunk
            key = ""
            for line in req.decode("latin-1").split("\r\n"):
                if line.lower().startswith("sec-websocket-key:"):
                    key = line.split(":", 1)[1].strip()
            accept = base64.b64encode(hashlib.sha1((key + _GUID).encode()).digest()).decode()
            conn.sendall(
                b"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\n"
                b"Connection: Upgrade\r\nSec-WebSocket-Accept: " + accept.encode() + b"\r\n\r\n"
            )
            while True:
                try:
                    op, payload = _ws_frame_read(conn)
                except (IndexError, ConnectionError, OSError):
                    break
                if op == 0x8:  # close
                    break
                reply = handler(payload.decode("utf-8", "replace"))
                if reply is not None:
                    _ws_frame_send(conn, reply)
        finally:
            conn.close()

    def serve():
        while True:
            try:
                conn, _ = srv.accept()
            except OSError:
                break
            threading.Thread(target=handle, args=(conn,), daemon=True).start()

    threading.Thread(target=serve, daemon=True).start()
    return host, port


async def test_ws_sender_sends_message_and_returns_reply_response():
    host, port = ws_server(lambda m: f"echo:{m}")
    sender = WebSocketSender(f"ws://{host}:{port}/chat")
    req = ws_message_request(f"ws://{host}:{port}/chat", '{"id":"1"}')
    resp = await sender.send(req)
    assert resp.status_code == 200 and resp.body.text() == 'echo:{"id":"1"}'


async def test_ws_sender_recv_timeout_returns_empty_body():
    host, port = ws_server(lambda m: None)  # never replies
    sender = WebSocketSender(f"ws://{host}:{port}/chat", recv_timeout=0.3)
    resp = await sender.send(ws_message_request(f"ws://{host}:{port}/chat", "hi", json=False))
    assert resp.status_code == 200 and resp.body.raw == b""


async def test_run_ws_attack_json_fuzz_finds_error_reply():
    # server returns a stack trace when a message differs from the benign baseline
    def handler(msg):
        return "ok" if msg == '{"id":"1"}' else "Traceback (most recent call last): boom"

    host, port = ws_server(handler)
    report = await run_ws_attack(f"ws://{host}:{port}/x", '{"id":"1"}', AttackType.FUZZ)
    assert report.findings
    assert any(f.attack_type == AttackType.FUZZ for f in report.findings)


async def test_run_ws_attack_ssti_evaluates_product():
    # a template-evaluating server: replace {{a*b}} with the product
    def handler(msg):
        m = re.search(r"\{\{(\d+)\*(\d+)\}\}", msg)
        if m:
            return f"result: {int(m.group(1)) * int(m.group(2))}"
        return "no template"

    host, port = ws_server(handler)
    report = await run_ws_attack(f"ws://{host}:{port}/x", '{"q":"hi"}', AttackType.SSTI)
    assert any(
        f.attack_type == AttackType.SSTI and f.confidence.name == "HIGH" for f in report.findings
    )


async def test_run_ws_attack_text_message_via_body_point():
    def handler(msg):
        return "Fatal error: bad" if msg != "PING" else "pong"

    host, port = ws_server(handler)
    report = await run_ws_attack(f"ws://{host}:{port}/x", "PING", AttackType.FUZZ, json=False)
    assert report.findings  # whole-message fuzz via the `body` locator


def test_run_ws_attack_sync_round_trip():
    def handler(msg):
        return "ok" if msg == '{"id":"1"}' else "Internal Server Error"

    host, port = ws_server(handler)
    report = run_ws_attack_sync(f"ws://{host}:{port}/x", '{"id":"1"}', AttackType.FUZZ)
    assert report.findings
