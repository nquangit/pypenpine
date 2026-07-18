# WebSocket Attack Integration — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run the existing six attack modules over WebSocket messages by (a) adding a general `body` locator, and (b) a duck-typed `WebSocketSender` + helpers so `Runner(sender=WebSocketSender(...)).run(msg_request, points=…)` works unchanged.

**Architecture:** A WS message is modeled as a `Request` (JSON body → `json:$.*` points; text → one `body` point). `WebSocketSender.send` opens `ws_connect`, sends the mutated message frame, receives the reply, and returns a synthetic `Response(200, body=reply)`. The Runner, analyzer, locators, validators, and all six modules stay untouched.

**Tech Stack:** Python 3.11+, stdlib (`asyncio`, `urllib.parse`), pytest.

## Global Constraints

- Python 3.11+; new modules keep `from __future__ import annotations`.
- Do NOT modify the Runner, analyzer engine, validators, or the six modules. Integration is: a new `body` locator (L0), a new `penpine/attack/websocket.py` (L4), exports.
- `body` locator is general (raw-body locate/replace) and is NOT auto-emitted by `enumerate_candidates` (so existing HTTP analyze/attack runs are unaffected).
- Explicit `points=` to `Runner.run` BYPASSES the `applies` filter (confirmed in the Runner docstring) — so a `body` point runs every chosen module. Rely on that.
- `WebSocketSender.send` must not abort the batch: connect failures propagate (recorded per attempt); a recv timeout yields an empty-body reply, not an error (Runner-never-raises).
- Reuse the existing WS client (`penpine.transport.websocket.ws_connect`, `WebSocketConnection`, `Message`). Fresh connection per attempt.
- Ruff lint + format gating; mypy advisory. Commit with `git commit --no-gpg-sign`.

## File Structure
- MODIFY: `penpine/core/locator.py` (Task 1) — `body` kind in `parse_expr`/`_read`/`_replace`.
- CREATE: `penpine/attack/websocket.py` (Tasks 2-3).
- MODIFY: `penpine/attack/__init__.py`, `penpine/__init__.py` (Task 3) — exports.
- Tests: `tests/core/test_locator.py` (Task 1), `tests/attack/test_ws_attack.py` (Tasks 2-3).

---

### Task 1: `body` locator (L0)

**Files:**
- Modify: `penpine/core/locator.py`
- Test: `tests/core/test_locator.py`

**Interfaces:**
- Produces: `request.locate("body")` → body text; `request.replace_at("body", value)` → request copy with the whole body replaced.

- [ ] **Step 1: Write the failing test**

Append to `tests/core/test_locator.py`:
```python
def test_body_locator_locate_and_replace():
    from penpine.core.message import Request

    req = Request.from_raw(
        b"POST /x HTTP/1.1\r\nHost: h\r\nContent-Type: text/plain\r\nContent-Length: 5\r\n\r\nhello",
        scheme="http", host="h", port=80,
    )
    assert req.locate("body").value == "hello"
    out = req.replace_at("body", "WORLD")
    assert out.body.text() == "WORLD"
    assert out.body.raw == b"WORLD"


def test_body_locator_replace_accepts_bytes():
    from penpine.core.message import Request

    req = Request.from_raw(b"POST /x HTTP/1.1\r\nHost: h\r\nContent-Length: 2\r\n\r\nhi",
                           scheme="http", host="h", port=80)
    assert req.replace_at("body", b"\x00\x01").body.raw == b"\x00\x01"
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/core/test_locator.py -k body -q`
Expected: FAIL (`LocatorError: invalid locator expression: 'body'`).

- [ ] **Step 3: Add `body` to the locator**

In `penpine/core/locator.py`:
1. `parse_expr` — add `body` to the bare-expression set:
```python
    if expr in ("method", "target", "version", "body"):
        return expr, ""
```
2. `_read` — before the final `raise`, add:
```python
    if kind == "body":
        return request.body.text()
```
3. `_replace` — before the final `raise`, add:
```python
    if kind == "body":
        return request.with_body(value.encode("utf-8") if isinstance(value, str) else value)
```
(Do NOT touch `enumerate_candidates` — `body` stays non-auto-emitted.)

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/core/test_locator.py -q`
Expected: PASS.

- [ ] **Step 5: Lint + commit**

Run: `ruff check penpine/core/locator.py tests/core/test_locator.py && ruff format penpine/core/locator.py tests/core/test_locator.py`
```bash
git add penpine/core/locator.py tests/core/test_locator.py
git commit --no-gpg-sign -m "feat(core): add 'body' locator (locate/replace the whole raw body)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: message modeling + `WebSocketSender`

**Files:**
- Create: `penpine/attack/websocket.py`
- Test: `tests/attack/test_ws_attack.py`

**Interfaces:**
- Consumes: `ws_connect` (transport), `body` locator (Task 1), `InjectionPoint`, `Request`/`Response`/`Body`/`Headers`.
- Produces: `ws_message_request(url, message, *, json=True) -> Request`; `ws_injection_points(request) -> list[InjectionPoint]`; `WebSocketSender(url, *, headers, subprotocols, tls, proxy, timeouts, prelude, recv_count, recv_timeout, binary)` with `async send(request) -> Response`.

- [ ] **Step 1: Write the failing test**

Create `tests/attack/test_ws_attack.py`:
```python
import base64
import hashlib
import socket
import struct
import threading

from penpine.attack.websocket import (
    WebSocketSender,
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
    """handler(message_str) -> reply_str (or None to send nothing). One connection."""
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
        conn.close()
        srv.close()

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
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/attack/test_ws_attack.py -q`
Expected: FAIL (`ModuleNotFoundError: penpine.attack.websocket`).

- [ ] **Step 3: Create `penpine/attack/websocket.py`**

```python
"""Run the attack pipeline over WebSocket messages.

A WS message is modeled as a Request (JSON body -> json:$.* injection points, or
text -> a single `body` point). `WebSocketSender` is a duck-typed Runner sender:
it opens a WebSocket, sends the (mutated) message as a frame, reads the reply, and
returns a synthetic Response so the existing validators/modules work unchanged.
"""

from __future__ import annotations

import asyncio
from urllib.parse import urlsplit

from penpine.attack.models import InjectionPoint
from penpine.core.body.base import Body
from penpine.core.headers import Headers
from penpine.core.message import Request, Response
from penpine.transport.websocket import ws_connect


def ws_message_request(url: str, message: str, *, json: bool = True) -> Request:
    parts = urlsplit(url)
    host = parts.hostname or "ws-target"
    port = parts.port or (443 if parts.scheme == "wss" else 80)
    target = (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
    ctype = "application/json" if json else "text/plain"
    body = message.encode("utf-8")
    raw = (
        f"POST {target} HTTP/1.1\r\nHost: {host}:{port}\r\n"
        f"Content-Type: {ctype}\r\nContent-Length: {len(body)}\r\n\r\n"
    ).encode("latin-1") + body
    scheme = "https" if parts.scheme == "wss" else "http"
    return Request.from_raw(raw, scheme=scheme, host=host, port=port)


def ws_injection_points(request) -> list[InjectionPoint]:
    cands = request.injection_candidates(kinds=("json",))
    if cands:
        return [InjectionPoint.from_locator(c) for c in cands]
    return [InjectionPoint(expr="body", kind="body", name="", value=request.body.text())]


class WebSocketSender:
    """Duck-typed Runner sender that delivers each (mutated) message over a fresh
    WebSocket connection and returns the reply as a synthetic Response."""

    def __init__(
        self, url, *, headers=None, subprotocols=None, tls=None, proxy=None,
        timeouts=None, prelude=(), recv_count=1, recv_timeout=5.0, binary=False,
    ):
        self._url = url
        self._connect_kw = {
            "headers": headers, "subprotocols": subprotocols,
            "tls": tls, "proxy": proxy, "timeouts": timeouts,
        }
        self._prelude = list(prelude)
        self._recv_count = recv_count
        self._recv_timeout = recv_timeout
        self._binary = binary

    async def send(self, request):
        ws = await ws_connect(self._url, **self._connect_kw)
        replies: list[str] = []
        try:
            for m in self._prelude:
                await ws.send_text(m)
            message = request.body.text()
            if self._binary:
                await ws.send_bytes(message.encode("utf-8"))
            else:
                await ws.send_text(message)
            for _ in range(self._recv_count):
                try:
                    msg = await asyncio.wait_for(ws.recv(), self._recv_timeout)
                except TimeoutError:
                    break
                if msg.kind == "close":
                    break
                replies.append(
                    msg.data if isinstance(msg.data, str) else msg.data.decode("utf-8", "replace")
                )
        finally:
            await ws.close()
        ctype = "application/octet-stream" if self._binary else "application/json"
        return Response(
            status_code=200, reason="OK",
            headers=Headers([("Content-Type", ctype)]),
            body=Body("".join(replies).encode("utf-8")),
        )
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/attack/test_ws_attack.py -q`
Expected: PASS (4 tests).

- [ ] **Step 5: Lint + commit**

Run: `ruff check penpine/attack/websocket.py tests/attack/test_ws_attack.py && ruff format penpine/attack/websocket.py tests/attack/test_ws_attack.py`
```bash
git add penpine/attack/websocket.py tests/attack/test_ws_attack.py
git commit --no-gpg-sign -m "feat(attack): WebSocketSender + WS message-as-request modeling

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: `run_ws_attack` convenience + exports + end-to-end

**Files:**
- Modify: `penpine/attack/websocket.py`, `penpine/attack/__init__.py`, `penpine/__init__.py`
- Test: `tests/attack/test_ws_attack.py`

**Interfaces:**
- Consumes: `Runner`, `register_builtins`, Task-2 helpers.
- Produces: `run_ws_attack(url, message, attack, *, json=True, points=None, sender=None, max_concurrency=10, **sender_kw)` (async) + `run_ws_attack_sync(...)`; exports.

- [ ] **Step 1: Write the failing end-to-end tests**

Append to `tests/attack/test_ws_attack.py` (reuse `ws_server` from Task 2):
```python
import re

from penpine.attack.types import AttackType
from penpine.attack.websocket import run_ws_attack, run_ws_attack_sync


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
    assert any(f.attack_type == AttackType.SSTI and f.confidence.name == "HIGH" for f in report.findings)


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
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/attack/test_ws_attack.py -q`
Expected: FAIL (`cannot import name 'run_ws_attack'`).

- [ ] **Step 3: Add `run_ws_attack` + `run_ws_attack_sync`**

Append to `penpine/attack/websocket.py`:
```python
def _ws_run(url, message, attack, json, points, sender, max_concurrency, sender_kw, *, sync):
    from penpine.attack.modules import register_builtins
    from penpine.attack.runner import Runner

    register_builtins()  # idempotent; ensures the chosen attack resolves to a module
    request = ws_message_request(url, message, json=json)
    pts = points if points is not None else ws_injection_points(request)
    active = sender if sender is not None else WebSocketSender(url, **sender_kw)
    runner = Runner(sender=active, max_concurrency=max_concurrency)
    if sync:
        return runner.run_sync(request, attack=attack, points=pts)
    return runner.run(request, attack=attack, points=pts)


async def run_ws_attack(
    url, message, attack, *, json=True, points=None, sender=None, max_concurrency=10, **sender_kw
):
    return await _ws_run(url, message, attack, json, points, sender, max_concurrency, sender_kw, sync=False)


def run_ws_attack_sync(
    url, message, attack, *, json=True, points=None, sender=None, max_concurrency=10, **sender_kw
):
    return _ws_run(url, message, attack, json, points, sender, max_concurrency, sender_kw, sync=True)
```

- [ ] **Step 4: Export the public surface**

In `penpine/attack/__init__.py`: add
```python
from penpine.attack.websocket import (
    WebSocketSender,
    run_ws_attack,
    run_ws_attack_sync,
    ws_injection_points,
    ws_message_request,
)
```
and add those five names to `__all__`.
In `penpine/__init__.py`: add `from penpine.attack.websocket import WebSocketSender, run_ws_attack, run_ws_attack_sync` and add the three names to `__all__` (correct isort order).

- [ ] **Step 5: Run to verify it passes**

Run: `pytest tests/attack/test_ws_attack.py -q`
Expected: PASS (all, incl. the 4 e2e).

- [ ] **Step 6: Full suite + gates**

Run: `pytest -q && ruff check . && ruff format --check . && mypy penpine`
Expected: all pass; ruff clean; mypy Success.

- [ ] **Step 7: Commit**

```bash
git add penpine/attack/websocket.py penpine/attack/__init__.py penpine/__init__.py tests/attack/test_ws_attack.py
git commit --no-gpg-sign -m "feat(attack): run_ws_attack convenience + exports (WebSocket attack integration)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Self-Review Notes

- **Spec coverage:** `body` locator (Component 1) → Task 1; `ws_message_request`/`ws_injection_points`/`WebSocketSender` (Component 2/3) → Task 2; `run_ws_attack`(+sync) + exports + data flow → Task 3. Testing spec (locator, modeling, e2e fuzz/ssti/text, timeout, sync) → each task's tests.
- **Pipeline untouched:** no Runner/analyzer/validator/module changes; integration is a locator + a sender + a convenience wrapper. Explicit `points=` bypasses `applies` (verified in the Runner docstring), so text `body` points run every module.
- **Runner-never-raises:** `WebSocketSender.send` lets connect errors propagate (recorded per attempt); recv timeout → empty reply (not an error). The `finally: ws.close()` always runs.
- **Type/name consistency:** `ws_message_request` builds a JSON/text-body `Request`; `ws_injection_points` returns `InjectionPoint`s (`json:$.*` or one `body`); `WebSocketSender.send(request)` returns `Response(200, body=reply)`; `run_ws_attack` wires `Runner(sender=…).run(request, attack=…, points=…)`.
- **Reply/oracle:** synthetic 200 means status anomalies don't fire and `crlf` is N/A (expected); content oracles (fuzz error-sig/size, ssti eval, cmdi reflect, nosqli sig, ssrf metadata) fire over the reply body vs the baseline reply.
- **`recv` timeout:** `asyncio.wait_for(ws.recv(), recv_timeout)` catches `TimeoutError` (3.11+: `asyncio.TimeoutError is TimeoutError`).
