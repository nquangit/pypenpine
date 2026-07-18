import base64
import hashlib
import socket
import threading


def _ws_serve_echo_header(header_name):
    """WS server that, after the handshake, sends the value of `header_name`
    from the handshake request as the first message. One connection."""
    srv = socket.socket()
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    host, port = srv.getsockname()
    guid = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

    def serve():
        conn, _ = srv.accept()
        req = b""
        while b"\r\n\r\n" not in req:
            req += conn.recv(1024)
        lines = req.decode("latin-1").split("\r\n")
        key = next(
            line.split(":", 1)[1].strip()
            for line in lines
            if line.lower().startswith("sec-websocket-key:")
        )
        value = ""
        for line in lines:
            if line.lower().startswith(header_name.lower() + ":"):
                value = line.split(":", 1)[1].strip()
        accept = base64.b64encode(hashlib.sha1((key + guid).encode()).digest()).decode()
        conn.sendall(
            b"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\n"
            b"Connection: Upgrade\r\nSec-WebSocket-Accept: " + accept.encode() + b"\r\n\r\n"
        )
        data = value.encode()
        conn.sendall(bytes([0x81, len(data)]) + data)
        srv.close()

    threading.Thread(target=serve, daemon=True).start()
    return host, port


class _FakeManager:
    async def ensure_fresh(self):
        return None

    def apply(self, request):
        return request.set_header("Authorization", "Bearer TESTTOKEN")


class _FakeIdentity:
    manager = _FakeManager()


async def test_ws_connect_authed_lifts_auth_header():
    from penpine.flow.websocket import ws_connect_authed

    host, port = _ws_serve_echo_header("Authorization")
    ws = await ws_connect_authed(f"ws://{host}:{port}/x", identity=_FakeIdentity())
    msg = await ws.recv()
    await ws.close()
    assert msg.data == "Bearer TESTTOKEN"


async def test_ws_connect_authed_explicit_header_wins():
    from penpine.flow.websocket import ws_connect_authed

    host, port = _ws_serve_echo_header("Authorization")
    ws = await ws_connect_authed(
        f"ws://{host}:{port}/x",
        identity=_FakeIdentity(),
        headers=[("Authorization", "explicit-value")],
    )
    msg = await ws.recv()
    await ws.close()
    assert msg.data == "explicit-value"
