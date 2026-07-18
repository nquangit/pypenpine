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
