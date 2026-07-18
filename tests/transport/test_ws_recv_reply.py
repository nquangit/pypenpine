import base64
import hashlib
import socket
import threading

from penpine.transport.websocket import recv_reply, ws_connect

_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


def _send_frame(conn, text):
    data = text.encode()
    conn.sendall(bytes([0x81, len(data)]) + data)


def _server(n_frames):
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
        # read the client's frame (masked) then reply with n frames
        b1 = conn.recv(2)[1] & 0x7F
        conn.recv(4 + b1)  # mask + payload
        for i in range(n_frames):
            _send_frame(conn, f"part{i}")
        srv.close()

    threading.Thread(target=serve, daemon=True).start()
    return host, port


async def test_recv_reply_joins_multiple_frames():
    host, port = _server(2)
    ws = await ws_connect(f"ws://{host}:{port}/x")
    await ws.send_text("go")
    resp = await recv_reply(ws, recv_count=2, recv_timeout=2.0)
    await ws.close()
    assert resp.status_code == 200 and resp.body.text() == "part0part1"
    assert resp.headers.get("Content-Type") == "application/json"


async def test_recv_reply_timeout_yields_empty():
    host, port = _server(0)
    ws = await ws_connect(f"ws://{host}:{port}/x")
    await ws.send_text("go")
    resp = await recv_reply(ws, recv_count=1, recv_timeout=0.3)
    await ws.close()
    assert resp.body.raw == b""
