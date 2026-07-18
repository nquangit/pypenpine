from penpine.transport.stream import FakeByteStream
from penpine.transport.websocket import Message, WebSocketConnection
from penpine.transport.ws_frame import OP_PING, Frame


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
