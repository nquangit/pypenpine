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


class _NoAuthIdentity:
    manager = None


async def test_ws_connect_authed_identity_without_manager_connects_plainly():
    from penpine.flow.websocket import ws_connect_authed

    host, port = _ws_serve_echo_header("Authorization")
    ws = await ws_connect_authed(f"ws://{host}:{port}/x", identity=_NoAuthIdentity())
    msg = await ws.recv()
    await ws.close()
    assert msg.data == ""  # no auth header lifted, no crash


def _ws_serve_json(reply_for):
    """WS server: for each received message, reply with reply_for(message_str).
    Accepts connections in a loop (one thread each)."""
    srv = socket.socket()
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", 0))
    srv.listen(5)
    host, port = srv.getsockname()
    guid = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

    def handle(conn):
        req = b""
        while b"\r\n\r\n" not in req:
            req += conn.recv(1024)
        key = next(
            line.split(":", 1)[1].strip()
            for line in req.decode("latin-1").split("\r\n")
            if line.lower().startswith("sec-websocket-key:")
        )
        accept = base64.b64encode(hashlib.sha1((key + guid).encode()).digest()).decode()
        conn.sendall(
            b"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\n"
            b"Connection: Upgrade\r\nSec-WebSocket-Accept: " + accept.encode() + b"\r\n\r\n"
        )
        while True:
            try:
                head = conn.recv(2)
                if len(head) < 2:
                    break
                n = head[1] & 0x7F
                key4 = conn.recv(4) if head[1] & 0x80 else b"\x00\x00\x00\x00"
                payload = bytearray(conn.recv(n))
                for i in range(len(payload)):
                    payload[i] ^= key4[i % 4]
            except OSError:
                break
            if head[0] & 0x0F == 0x8:
                break
            reply = reply_for(payload.decode("utf-8", "replace"))
            data = reply.encode()
            conn.sendall(bytes([0x81, len(data)]) + data)
        conn.close()

    def acceptor():
        while True:
            try:
                conn, _ = srv.accept()
            except OSError:
                break
            threading.Thread(target=handle, args=(conn,), daemon=True).start()

    threading.Thread(target=acceptor, daemon=True).start()
    return host, port


async def test_ws_flow_open_send_capture_close():
    from penpine.data import Extract
    from penpine.flow import Flow, ws_close, ws_open, ws_send

    host, port = _ws_serve_json(lambda m: '{"email":"a@b.co"}')
    flow = Flow(
        [
            ws_open("connect", f"ws://{host}:{port}/x"),
            ws_send(
                "get", '{"action":"getUser","id":"1"}', capture=[Extract("email", json="$.email")]
            ),
            ws_close("bye"),
        ]
    )
    result = await flow.run()
    assert result.context.get("email") == "a@b.co"
    assert [s.status for s in result.steps] == ["ok", "ok", "ok"]


async def test_ws_flow_reuses_connection_and_templates():
    from penpine.data import Extract
    from penpine.flow import Flow, ws_close, ws_open, ws_send

    # echo the message back so we can prove templating used a captured value
    host, port = _ws_serve_json(lambda m: m)
    flow = Flow(
        [
            ws_open("c", f"ws://{host}:{port}/x"),
            ws_send("one", "hello", capture=[Extract("first", regex=r"(.+)")]),
            ws_send("two", "got:{{first}}", capture=[Extract("second", regex=r"(.+)")]),
            ws_close("bye"),
        ]
    )
    result = await flow.run()
    assert result.context.get("second") == "got:hello"


async def test_ws_send_without_open_fails_cleanly():
    from penpine.flow import Flow, ws_send

    result = await Flow([ws_send("x", "hi")], continue_on_error=True).run()
    assert result.steps[0].status == "failed"
