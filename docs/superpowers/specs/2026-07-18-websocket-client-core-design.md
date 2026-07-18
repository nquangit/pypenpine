# WebSocket Client Core — Design

**Date:** 2026-07-18
**Status:** Approved (design), pending implementation plan
**Sub-project:** 1 of 2 (the other: a general fuzzing/injection attack module — separate cycle)

## Problem

penpine speaks HTTP/1.1 only. Engagements increasingly involve WebSocket
endpoints, and there is currently no way to connect to one, send/receive
messages, or — importantly for a pentest tool — craft deliberately malformed
frames. This sub-project adds a **WebSocket client core**: the `Upgrade`
handshake, RFC 6455 frame encode/decode, and a connection object to drive the
protocol from code.

Attack/fuzzing over a live WS message stream is explicitly **out of scope** here;
it is a later cycle (the general fuzzing module will target WS messages once this
client exists).

## Decisions (locked during brainstorming)

1. **Scope = WS client core.** Handshake + framing + a connection you drive in
   code (send/receive text/binary/ping/pong/close). No attack integration yet.
2. **Byte-faithful, malformable frames** — matching penpine's HTTP ethos:
   `Frame.serialize()` returns the exact wire bytes; you can craft broken frames
   (bad opcode, wrong declared length, unmasked client frame, reserved bits).
3. **Build on the existing `Connection`** — reuse the transport stack (TLS for
   `wss://`, HTTP/SOCKS proxy CONNECT, timeouts, and the blocking-socket
   unclean-close tolerance) rather than re-implementing the open sequence.
4. **Async core + `_sync` facades**, consistent with the rest of the framework.

## Architecture

### Files
- `penpine/transport/ws_frame.py` — the `Frame` model + encode/decode (RFC 6455).
- `penpine/transport/websocket.py` — `WebSocketConnection`, `ws_connect(...)`,
  handshake helpers, and `_sync` facades.
- `penpine/transport/exceptions.py` — add `WebSocketError(TransportError)` and
  `WebSocketHandshakeError(WebSocketError)`.
- Export the public surface from `penpine/transport/__init__.py` and re-export the
  top-level names (`ws_connect`, `WebSocketConnection`, `Frame`) from
  `penpine/__init__.py`.

### Layering
WebSocket is an L1 (transport) capability. The handshake is an HTTP request built
with the existing L0 `Request`/`Headers`. Framing is a self-contained concern in
`ws_frame.py` (no HTTP dependency). The connection reuses `Connection` (socket,
TLS, proxy, timeouts) to obtain the byte stream, then owns it for frames.

## Component 1 — `Frame` (`ws_frame.py`)

RFC 6455 §5. Immutable, byte-faithful, malformable.

```python
# opcode constants
OP_CONTINUATION = 0x0
OP_TEXT = 0x1
OP_BINARY = 0x2
OP_CLOSE = 0x8
OP_PING = 0x9
OP_PONG = 0xA

@dataclass(frozen=True)
class Frame:
    opcode: int
    payload: bytes = b""
    fin: bool = True
    mask: bytes | None = None          # 4 bytes to mask with; None = unmasked on the wire
    rsv1: bool = False
    rsv2: bool = False
    rsv3: bool = False

    def serialize(self) -> bytes: ...   # exact wire bytes (does NOT auto-mask; see note)

    @classmethod
    def parse(cls, data: bytes) -> tuple[Frame, bytes]: ...
        # parse ONE frame from the front of `data`; return (frame, remaining_bytes).
        # raises IncompleteFrame if data is short (caller reads more and retries).

    # convenience constructors (do NOT mask by default — masking is applied at send time)
    @classmethod
    def text(cls, s: str, *, fin=True) -> Frame: ...
    @classmethod
    def binary(cls, b: bytes, *, fin=True) -> Frame: ...
    @classmethod
    def ping(cls, payload=b"") -> Frame: ...
    @classmethod
    def pong(cls, payload=b"") -> Frame: ...
    @classmethod
    def close(cls, code: int = 1000, reason: str = "") -> Frame: ...
```

Details:
- **Serialization** writes: FIN+RSV+opcode byte; MASK bit + 7/16/64-bit length
  (7 for ≤125, 126+u16 for ≤65535, 127+u64 otherwise); the 4-byte masking key if
  `mask` is set; then the payload (XOR-masked with `mask` when `mask` is set,
  raw otherwise). `serialize()` is literal — if you set a `mask` that is not 4
  bytes, or `fin`/`rsv`/`opcode` to nonsense, it writes exactly that (malformable).
- **`parse`** decodes one frame, unmasking if the MASK bit is set, and returns the
  remaining bytes so a stream decoder can loop. A dedicated `IncompleteFrame`
  exception (internal) signals "need more bytes".
- **Masking policy:** the `Frame` itself does not force masking. The *connection*
  masks outgoing client frames with a fresh random key at send time (RFC 6455
  requires client→server frames be masked) unless the caller supplies a frame
  that already carries a `mask` (so malformed/unmasked frames can be sent
  deliberately). This keeps `Frame` a pure data object and puts the "correct by
  default, breakable on purpose" policy in the connection.

## Component 2 — handshake (`websocket.py`)

- `_handshake_request(url, key, *, headers, subprotocols) -> Request`: a `GET` to
  the URL's path with `Host`, `Upgrade: websocket`, `Connection: Upgrade`,
  `Sec-WebSocket-Key: <b64(16 random bytes)>`, `Sec-WebSocket-Version: 13`, plus
  optional `Sec-WebSocket-Protocol` and user headers.
- `_accept_for(key) -> str`: `b64(sha1(key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"))`.
- On response: require status `101`, `Upgrade: websocket` (case-insensitive),
  `Connection: Upgrade`, and `Sec-WebSocket-Accept == _accept_for(key)`. Any
  mismatch → `WebSocketHandshakeError` carrying the `Response` for inspection.

## Component 3 — `WebSocketConnection` (`websocket.py`)

Owns the upgraded byte stream (from a `Connection`) and a read buffer.

```python
class WebSocketConnection:
    def __init__(self, conn: Connection, *, auto_pong: bool = True): ...

    # sending
    async def send_text(self, s: str) -> None
    async def send_bytes(self, b: bytes) -> None
    async def send_frame(self, frame: Frame) -> None   # low-level; used as-is

    # receiving
    async def recv(self) -> Message                    # reassembled text/binary message
    async def recv_frame(self) -> Frame                # exactly one frame, no reassembly

    # control
    async def ping(self, payload: bytes = b"") -> None
    async def close(self, code: int = 1000, reason: str = "") -> None

    @property
    def closed(self) -> bool

    # every async method above has a *_sync twin
```

Behavior:
- **Send**: `send_text`/`send_bytes` build a `Frame` and pass to `send_frame`.
  `send_frame` masks the frame with a fresh random 4-byte key **if the frame has
  no `mask` set** (correct client behavior), then writes `serialize()` to the
  stream and drains. A frame that already carries a `mask` (incl. an intentionally
  wrong one) is sent verbatim — malformed-frame testing.
- **recv_frame**: pulls one frame from the buffer, reading more bytes from the
  stream (`stream.read`) and retrying on `IncompleteFrame` until a full frame
  decodes; returns it raw. On stream EOF mid-frame → `WebSocketError`.
- **recv** (high level): loops `recv_frame`; on `ping` auto-sends `pong` (when
  `auto_pong`) and continues; on `pong` continues; on `close` records the close
  and returns a close `Message` (and marks `closed`); reassembles
  `text`/`binary` + `continuation` frames until `fin`, decoding text as UTF-8,
  and returns a `Message(kind, data)`. A `Message` is a small dataclass
  `Message(kind: str, data: bytes|str, code: int|None=None, reason: str|None=None)`.
- **close**: send a masked close frame (code+reason), mark closed, and close the
  underlying `Connection`. Idempotent.
- **auto_pong** can be disabled to observe raw control frames via `recv_frame`.

### `ws_connect`
```python
async def ws_connect(
    url: str, *, headers=None, subprotocols=None,
    tls: TLSConfig | None = None, proxy: ProxyConfig | None = None,
    timeouts: Timeouts | None = None, auto_pong: bool = True,
) -> WebSocketConnection
```
- Parse `url`: scheme `ws`→plain (`use_tls=False`), `wss`→TLS; host/port
  (defaults 80/443); path+query for the request target.
- Open a `Connection(host, port, use_tls=<scheme>, tls=tls, proxy=proxy,
  timeouts=timeouts)`; send the handshake request bytes via the connection's
  stream; read the HTTP response with the existing response reader; validate the
  handshake; wrap the connection in `WebSocketConnection`.
- Requires exposing the connection's stream for raw frame I/O. **Add
  `Connection.stream` (read-only property returning the underlying `ByteStream`)**
  and reuse `Connection.send_bytes` for writes; frames are read via
  `self._conn.stream.read(n)`. (Small, additive change to `Connection`.)

### Sync facades
`ws_connect_sync(...)` and `WebSocketConnection.*_sync` spin/manage a loop exactly
like `Engine.send_sync`/`Runner.run_sync` (reuse `penpine._sync.run_on_loop` and
the loop-management pattern). The connection holds its own loop for the `_sync`
path so a single connection can be driven synchronously across calls.

## Data flow

```
ws_connect(url)
  ├─ Connection(host, port, use_tls=wss, proxy, tls, timeouts).open()   # socket/TLS/proxy CONNECT
  ├─ conn.send_bytes(handshake_request.serialize())
  ├─ resp = ResponseReader.read(conn.stream)  -> require 101 + valid Accept
  └─ WebSocketConnection(conn)
        send_text("hi") -> Frame.text -> mask -> serialize -> conn.send_bytes
        recv() -> recv_frame (read stream, parse) -> reassemble/auto-pong -> Message
        close() -> send close frame -> conn.close()
```

## Error handling
- `WebSocketHandshakeError` — non-101 / missing/incorrect Upgrade/Accept headers;
  carries the `Response`.
- `WebSocketError` — framing errors, EOF mid-frame, use-after-close.
- Malformed frames the *caller* crafts are NOT validated (that is the feature);
  only protocol-integrity errors on the *receive* path raise.
- Reuse existing transport errors (`ConnectError`, `ReadTimeout`, TLS/proxy) from
  the underlying `Connection` unchanged.

## Testing
- **Frame unit tests** (`tests/transport/test_ws_frame.py`): serialize→parse
  round-trip for text/binary/ping/pong/close; 7-bit, 16-bit (>125), and 64-bit
  (>65535) length encodings; masked and unmasked; `fin=False` continuation;
  reserved bits; `IncompleteFrame` on short input; a deliberately malformed frame
  serializes to the exact expected bytes.
- **Handshake tests**: `_accept_for` matches the RFC 6455 example
  (`dGhlIHNhbXBsZSBub25jZQ==` → `s3pPLMBiTxaQ9kYGzzhZRbK+xOo=`); request carries
  the required headers; a non-101 response raises `WebSocketHandshakeError`.
- **End-to-end** (`tests/transport/test_websocket.py`): an in-process WS echo
  server (stdlib `socket` in a thread implementing the handshake + framing) to
  test `ws_connect → send_text → recv → ping/pong (auto) → close` over the real
  blocking transport; a `recv_frame` test with `auto_pong=False` observing a raw
  ping; EOF/close handling.
- **`wss://`** variant against a self-signed TLS echo server (reuses the openssl
  cert pattern already used in transport tests) to confirm the TLS path.
- **`_sync` facades**: a `_sync` round-trip against the echo server.

## Non-goals / YAGNI
- No attack/fuzzing over WS (next cycle).
- No `permessage-deflate` / compression extensions (v1).
- No server-side WS. Client only.
- No automatic reconnect / backpressure tuning.
- No fragmentation-on-send helper (callers can send `fin=False` frames manually);
  reassembly-on-receive IS supported.

## Backward-compatibility notes
- Additive only: new modules + new exceptions + a new `Connection.stream`
  read-only property. No changes to existing HTTP behavior.
