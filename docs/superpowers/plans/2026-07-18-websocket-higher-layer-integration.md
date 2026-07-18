# WebSocket Higher-Layer Integration Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Integrate WebSocket into penpine's flow (L3.5), auth (L2), and data (L3) layers, plus a scaffold sample — reusing the existing message-as-request / reply-as-response modeling.

**Architecture:** A `render_text` string templater (L3), a `recv_reply` reply→Response helper (L1, shared by the attack sender and flow steps), `ws_connect_authed` (lift auth onto the handshake), and `ws_open`/`ws_send`/`ws_close` flow `action`-step factories (the live `WebSocketConnection` persists in the flow `Context`). A WS scaffold sample.

**Tech Stack:** Python 3.11+, stdlib (`asyncio`, `urllib`), pytest.

## Global Constraints

- Python 3.11+; new modules keep `from __future__ import annotations`.
- No new `Step` subclass — WS steps are `action=callable(FlowContext)` steps that return a synthetic `Response` (so the flow's `capture(ctx, response, step.capture)` and `{{ }}` templating are reused).
- Layering: the shared `recv_reply` lives in `penpine/transport/websocket.py` (L1) — imported *down* by `penpine/attack/websocket.py` (L4) and `penpine/flow/websocket.py` (L3.5). Flow MUST NOT import attack.
- Reuse `render`/`capture`/`Extract`/`build_mapping` (data L3), `SessionManager.apply`/`.session`/`ensure_fresh` (auth L2), `ws_connect`/`WebSocketConnection` (transport L1). No behavior change to existing HTTP flow/auth/data/attack code.
- Scaffold sample must run offline (guards on `WS_URL`) so `pytest` sample-run stays network-free.
- Ruff lint + format gating; mypy advisory. Commit with `git commit --no-gpg-sign`.

## File Structure
- MODIFY: `penpine/data/template.py`, `penpine/data/__init__.py` (Task 1).
- MODIFY: `penpine/transport/websocket.py`, `penpine/attack/websocket.py` (Task 2).
- CREATE: `penpine/flow/websocket.py` (Tasks 3-4); MODIFY `penpine/flow/__init__.py`, `penpine/__init__.py` (Task 4).
- CREATE: `penpine/cli/templates/project/samples/websocket.py.tmpl` (Task 5); MODIFY `tests/cli/test_samples_run.py`.
- Tests: `tests/data/test_template.py`, `tests/transport/test_ws_recv_reply.py`, `tests/flow/test_ws_flow.py`.

---

### Task 1: `render_text` (data L3)

**Files:**
- Modify: `penpine/data/template.py`, `penpine/data/__init__.py`
- Test: `tests/data/test_template.py`

**Interfaces:**
- Produces: `render_text(text: str, mapping, *, strict=True) -> str`; `render` refactored to call it (behavior unchanged).

- [ ] **Step 1: Write the failing test**

Append to `tests/data/test_template.py`:
```python
def test_render_text_substitutes_and_strict():
    import pytest

    from penpine.data.exceptions import TemplateError
    from penpine.data.template import render_text

    assert render_text("hi {{name}} #{{id}}", {"name": "al", "id": 7}) == "hi al #7"
    assert render_text("keep {{missing}}", {}, strict=False) == "keep {{missing}}"
    with pytest.raises(TemplateError):
        render_text("{{missing}}", {}, strict=True)


def test_render_request_still_works_via_render_text():
    from penpine.core.message import Request
    from penpine.data.template import render

    req = Request.from_url("http://h/p?q={{v}}")
    out = render(req, {"v": "X"})
    assert "q=X" in out.target
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/data/test_template.py -k "render_text or via_render_text" -q`
Expected: FAIL (`ImportError: render_text`).

- [ ] **Step 3: Add `render_text` and refactor `render`**

In `penpine/data/template.py`, add `render_text` (module-level) and make `render`'s inner `_replace` delegate to it:
```python
def render_text(text: str, mapping, *, strict: bool = True) -> str:
    def _sub(match):
        key = match.group(1)
        if key in mapping:
            return str(mapping[key])
        if strict:
            raise TemplateError(f"unknown placeholder: {{{{{key}}}}}")
        return match.group(0)

    return _PLACEHOLDER.sub(_sub, text)


def render(request, mapping, *, strict=True):
    def _replace(text: str) -> str:
        return render_text(text, mapping, strict=strict)

    new = request.with_target(_replace(request.target))
    new = new.with_headers(
        Headers([(name, _replace(value)) for name, value in new.headers.items()])
    )
    if request.body.raw:
        new = new.with_body(_replace(request.body.text()).encode())
    return new
```

- [ ] **Step 4: Export `render_text`**

In `penpine/data/__init__.py`: add `render_text` to the `from penpine.data.template import ...` line and to `__all__`.

- [ ] **Step 5: Run to verify it passes**

Run: `pytest tests/data/test_template.py -q`
Expected: PASS (existing render tests still pass).

- [ ] **Step 6: Lint + commit**

Run: `ruff check penpine/data/template.py penpine/data/__init__.py tests/data/test_template.py && ruff format <same>`
```bash
git add penpine/data/template.py penpine/data/__init__.py tests/data/test_template.py
git commit --no-gpg-sign -m "feat(data): add render_text; render() reuses it (DRY)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: `recv_reply` helper (transport L1) + refactor the attack sender

**Files:**
- Modify: `penpine/transport/websocket.py`, `penpine/attack/websocket.py`
- Test: `tests/transport/test_ws_recv_reply.py`

**Interfaces:**
- Produces: `recv_reply(ws, *, recv_count=1, recv_timeout=5.0, content_type="application/json") -> Response` — receive up to `recv_count` replies (joined), synthesize a `Response(200, body=…)`.
- `WebSocketSender.send` refactored to call it (no behavior change).

- [ ] **Step 1: Write the failing test**

Create `tests/transport/test_ws_recv_reply.py`:
```python
import base64
import hashlib
import socket
import struct
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
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/transport/test_ws_recv_reply.py -q`
Expected: FAIL (`ImportError: recv_reply`).

- [ ] **Step 3: Add `recv_reply` to `penpine/transport/websocket.py`**

Add imports near the top (with the other core imports):
```python
from penpine.core.body.base import Body
from penpine.core.headers import Headers
from penpine.core.message import Response
```
Add (after the `Message` dataclass or near `WebSocketConnection`):
```python
async def recv_reply(ws, *, recv_count=1, recv_timeout=5.0, content_type="application/json"):
    """Receive up to `recv_count` reply messages (stopping on timeout or a close),
    join their text, and return a synthetic Response(200) — the shape the attack
    validators and flow capture consume."""
    replies: list[str] = []
    for _ in range(recv_count):
        try:
            msg = await asyncio.wait_for(ws.recv(), recv_timeout)
        except TimeoutError:
            break
        if msg.kind == "close":
            break
        replies.append(
            msg.data if isinstance(msg.data, str) else msg.data.decode("utf-8", "replace")
        )
    return Response(
        status_code=200,
        reason="OK",
        headers=Headers([("Content-Type", content_type)]),
        body=Body("".join(replies).encode("utf-8")),
    )
```

- [ ] **Step 4: Refactor `WebSocketSender.send` to use it**

In `penpine/attack/websocket.py`: change the import to
`from penpine.transport.websocket import recv_reply, ws_connect` and replace the
recv loop + Response construction in `send` with:
```python
    async def send(self, request):
        ws = await ws_connect(self._url, **self._connect_kw)
        try:
            for m in self._prelude:
                await ws.send_text(m)
            message = request.body.text()
            if self._binary:
                await ws.send_bytes(message.encode("utf-8"))
            else:
                await ws.send_text(message)
            ctype = "application/octet-stream" if self._binary else "application/json"
            return await recv_reply(
                ws, recv_count=self._recv_count, recv_timeout=self._recv_timeout, content_type=ctype
            )
        finally:
            await ws.close()
```
Remove now-unused imports (`asyncio`, `Body`, `Headers`, `Response`) from `attack/websocket.py` if ruff flags them (they moved into `recv_reply`).

- [ ] **Step 5: Run to verify — new + existing attack WS tests pass**

Run: `pytest tests/transport/test_ws_recv_reply.py tests/attack/test_ws_attack.py -q`
Expected: PASS (recv_reply tests + the attack sender/e2e tests unchanged).

- [ ] **Step 6: Lint + commit**

Run: `ruff check penpine/transport/websocket.py penpine/attack/websocket.py tests/transport/test_ws_recv_reply.py && ruff format <same>`
```bash
git add penpine/transport/websocket.py penpine/attack/websocket.py tests/transport/test_ws_recv_reply.py
git commit --no-gpg-sign -m "refactor(transport): shared recv_reply(ws)->Response; attack sender reuses it

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: `ws_connect_authed` (auth L2 → handshake)

**Files:**
- Create: `penpine/flow/websocket.py`
- Test: `tests/flow/test_ws_flow.py`

**Interfaces:**
- Produces: `ws_connect_authed(url, *, identity=None, session=None, scheme=None, headers=None, **connect_kw) -> WebSocketConnection`.

- [ ] **Step 1: Write the failing test**

Create `tests/flow/test_ws_flow.py`:
```python
import base64
import hashlib
import socket
import struct
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
        key = next(l.split(":", 1)[1].strip() for l in lines if l.lower().startswith("sec-websocket-key:"))
        value = ""
        for l in lines:
            if l.lower().startswith(header_name.lower() + ":"):
                value = l.split(":", 1)[1].strip()
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

    host, port = _ws_serve_echo_header("X-Extra")
    ws = await ws_connect_authed(
        f"ws://{host}:{port}/x", identity=_FakeIdentity(), headers=[("X-Extra", "v1")]
    )
    msg = await ws.recv()
    await ws.close()
    assert msg.data == "v1"
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/flow/test_ws_flow.py -k connect_authed -q`
Expected: FAIL (`ModuleNotFoundError: penpine.flow.websocket`).

- [ ] **Step 3: Create `penpine/flow/websocket.py` with `ws_connect_authed`**

```python
"""WebSocket integration for the flow engine: authed connect + flow steps."""

from __future__ import annotations

from penpine.core.message import Request
from penpine.transport.websocket import _parse_ws_url, ws_connect


async def ws_connect_authed(
    url, *, identity=None, session=None, scheme=None, headers=None, **connect_kw
):
    """`ws_connect` with an auth session applied to the handshake. Lifts any
    header a scheme adds (Authorization/Cookie/custom) onto the WS handshake;
    explicit `headers` win over lifted ones."""
    ws_scheme, host, port, target = _parse_ws_url(url)
    http = "https" if ws_scheme == "wss" else "http"
    dummy = Request.from_url(f"{http}://{host}:{port}{target}")

    authed = dummy
    if identity is not None:
        manager = identity.manager
        await manager.ensure_fresh()
        authed = manager.apply(dummy)
    elif session is not None and scheme is not None:
        authed = scheme.apply(dummy, session)

    explicit = {n.lower() for n, _ in (headers or [])}
    before = {(n.lower(), v) for n, v in dummy.headers.items()}
    lifted = [
        (n, v)
        for n, v in authed.headers.items()
        if (n.lower(), v) not in before and n.lower() not in explicit
    ]
    merged = list(headers or []) + lifted
    return await ws_connect(url, headers=merged or None, **connect_kw)
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/flow/test_ws_flow.py -k connect_authed -q`
Expected: PASS (2 tests).

- [ ] **Step 5: Lint + commit**

Run: `ruff check penpine/flow/websocket.py tests/flow/test_ws_flow.py && ruff format <same>`
```bash
git add penpine/flow/websocket.py tests/flow/test_ws_flow.py
git commit --no-gpg-sign -m "feat(flow): ws_connect_authed — apply an auth session to the WS handshake

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 4: WS flow steps (`ws_open`/`ws_send`/`ws_close`) + exports

**Files:**
- Modify: `penpine/flow/websocket.py`, `penpine/flow/__init__.py`, `penpine/__init__.py`
- Test: `tests/flow/test_ws_flow.py`

**Interfaces:**
- Consumes: `ws_connect_authed` (Task 3), `recv_reply` (Task 2), `render_text`/`build_mapping` (Task 1), `Step`, `FlowError`.
- Produces: `ws_open(name, url, *, store="ws", identity=None, headers=None, guard=None, **connect_kw) -> Step`; `ws_send(name, message, *, store="ws", capture=None, recv=True, recv_timeout=5.0, recv_count=1, binary=False, guard=None) -> Step`; `ws_close(name, *, store="ws", guard=None) -> Step`.

- [ ] **Step 1: Write the failing end-to-end test**

Append to `tests/flow/test_ws_flow.py` (add a JSON echo server + the flow tests):
```python
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
            l.split(":", 1)[1].strip()
            for l in req.decode("latin-1").split("\r\n")
            if l.lower().startswith("sec-websocket-key:")
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
    flow = Flow([
        ws_open("connect", f"ws://{host}:{port}/x"),
        ws_send("get", '{"action":"getUser","id":"1"}', capture=[Extract("email", json="$.email")]),
        ws_close("bye"),
    ])
    result = await flow.run()
    assert result.context.get("email") == "a@b.co"
    assert [s.status for s in result.steps] == ["ok", "ok", "ok"]


async def test_ws_flow_reuses_connection_and_templates():
    from penpine.data import Extract
    from penpine.flow import Flow, ws_close, ws_open, ws_send

    # echo the message back so we can prove templating used a captured value
    host, port = _ws_serve_json(lambda m: m)
    flow = Flow([
        ws_open("c", f"ws://{host}:{port}/x"),
        ws_send("one", "hello", capture=[Extract("first", regex=r"(.+)")]),
        ws_send("two", "got:{{first}}", capture=[Extract("second", regex=r"(.+)")]),
        ws_close("bye"),
    ])
    result = await flow.run()
    assert result.context.get("second") == "got:hello"


async def test_ws_send_without_open_fails_cleanly():
    from penpine.flow import Flow, ws_send

    result = await Flow([ws_send("x", "hi")], continue_on_error=True).run()
    assert result.steps[0].status == "failed"
```
(Confirmed: `FlowResult.context` is a plain **dict** — `.get(...)` works; `FlowResult.steps` is a list of `StepResult` with `.status`.)

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/flow/test_ws_flow.py -q`
Expected: FAIL (`cannot import name 'ws_open'`).

- [ ] **Step 3: Add the step factories to `penpine/flow/websocket.py`**

Add imports:
```python
from penpine.data.template import build_mapping, render_text
from penpine.flow.exceptions import FlowError
from penpine.flow.step import Step
from penpine.transport.websocket import recv_reply
```
Append:
```python
def ws_open(name, url, *, store="ws", identity=None, headers=None, guard=None, **connect_kw) -> Step:
    async def _action(fc):
        ws = await ws_connect_authed(url, identity=identity, headers=headers, **connect_kw)
        fc.ctx.set(store, ws)
        return None

    return Step(name, action=_action, guard=guard)


def ws_send(
    name, message, *, store="ws", capture=None, recv=True, recv_timeout=5.0,
    recv_count=1, binary=False, guard=None,
) -> Step:
    async def _action(fc):
        ws = fc.ctx.get(store)
        if ws is None:
            raise FlowError(
                f"ws step {name!r}: no WebSocket connection in context[{store!r}] (add ws_open first)"
            )
        mapping = build_mapping(context=fc.ctx, data=getattr(fc.actor, "data", None))
        rendered = render_text(message, mapping, strict=False)
        if binary:
            await ws.send_bytes(rendered.encode("utf-8"))
        else:
            await ws.send_text(rendered)
        if not recv:
            return None
        ctype = "application/octet-stream" if binary else "application/json"
        return await recv_reply(ws, recv_count=recv_count, recv_timeout=recv_timeout, content_type=ctype)

    return Step(name, action=_action, capture=capture, guard=guard)


def ws_close(name, *, store="ws", guard=None) -> Step:
    async def _action(fc):
        ws = fc.ctx.get(store)
        if ws is not None:
            await ws.close()
            fc.ctx.set(store, None)
        return None

    return Step(name, action=_action, guard=guard)
```

- [ ] **Step 4: Export**

In `penpine/flow/__init__.py`: add
`from penpine.flow.websocket import ws_close, ws_connect_authed, ws_open, ws_send`
and add `"ws_open"`, `"ws_send"`, `"ws_close"`, `"ws_connect_authed"` to `__all__`.
In `penpine/__init__.py`: add `from penpine.flow.websocket import ws_close, ws_open, ws_send`
and add `"ws_open"`, `"ws_send"`, `"ws_close"` to `__all__` (correct isort order).

- [ ] **Step 5: Run to verify it passes**

Run: `pytest tests/flow/test_ws_flow.py -q`
Expected: PASS (all).

- [ ] **Step 6: Full suite + gates**

Run: `pytest -q && ruff check . && ruff format --check . && mypy penpine`
Expected: all pass; ruff clean; mypy Success.

- [ ] **Step 7: Commit**

```bash
git add penpine/flow/websocket.py penpine/flow/__init__.py penpine/__init__.py tests/flow/test_ws_flow.py
git commit --no-gpg-sign -m "feat(flow): ws_open/ws_send/ws_close steps (connection persists in Context)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 5: scaffold sample

**Files:**
- Create: `penpine/cli/templates/project/samples/websocket.py.tmpl`
- Modify: `tests/cli/test_samples_run.py`

**Interfaces:** none (a sample); must run offline (exit 0) with `WS_URL` unset.

- [ ] **Step 1: Create the sample**

`penpine/cli/templates/project/samples/websocket.py.tmpl`:
```python
"""WebSocket sample: client, attack, and a flow.

Offline-safe: set WS_URL to run against a real server, e.g.
    WS_URL=wss://target:6363/ws python -m samples.websocket
With WS_URL unset it prints usage and exits (so the offline test passes).
"""

import os

from penpine import AttackType, run_ws_attack_sync, ws_connect_sync
from penpine.data import Context, Extract
from penpine.flow import Flow, ws_close, ws_open, ws_send

WS_URL = os.environ.get("WS_URL")


def main():
    if not WS_URL:
        print("set WS_URL=wss://host/ws to run the WebSocket sample")
        return

    # 1) direct client
    ws = ws_connect_sync(WS_URL)
    try:
        ws.send_text_sync('{"action":"ping"}')
        print("reply:", ws.recv_sync().data)
    finally:
        ws.close_sync()

    # 2) attack (fuzz every JSON field of a message)
    report = run_ws_attack_sync(WS_URL, '{"action":"get","id":"1"}', AttackType.FUZZ)
    print("fuzz summary:", report.summary())

    # 3) flow: open -> send (templated) -> capture -> close
    result = Flow([
        ws_open("connect", WS_URL),
        ws_send("get", '{"action":"get","id":"{{id}}"}', capture=[Extract("reply", regex=r"(.+)")]),
        ws_close("bye"),
    ], context=Context({"id": "1"})).run_sync()
    print("flow steps:", [s.status for s in result.steps])


if __name__ == "__main__":
    main()
```
(`Flow(context=)` requires a `Context` object — `Context({"id":"1"})` — not a bare dict; confirm `Context` is exported from `penpine.data`.)

- [ ] **Step 2: Add to the sample-run test**

In `tests/cli/test_samples_run.py`, add `"websocket"` to the `SAMPLES` list (NOT to `FINDING_SAMPLES`).

- [ ] **Step 3: Run the scaffold sample test**

Run: `pytest tests/cli/test_samples_run.py -q`
Expected: PASS — the generated `samples/websocket.py` runs offline (WS_URL unset → prints usage, exit 0).

- [ ] **Step 4: Full suite + gates**

Run: `pytest -q && ruff check . && ruff format --check .`
Expected: all pass; ruff clean. (Templates are ruff-excluded; the test renders + runs the sample.)

- [ ] **Step 5: Commit**

```bash
git add penpine/cli/templates/project/samples/websocket.py.tmpl tests/cli/test_samples_run.py
git commit --no-gpg-sign -m "feat(cli): WebSocket scaffold sample (client + attack + flow)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Self-Review Notes

- **Spec coverage:** `render_text` (Component 1) → Task 1; `recv_reply` shared helper (Component 3 plumbing) → Task 2; `ws_connect_authed` (Component 2) → Task 3; WS flow steps (Component 1 steps) → Task 4; scaffold sample (Component 4) → Task 5. Data-over-WS (Component 3) is realized by Task 4 (templating via `render_text`, capture via the returned Response). Testing spec → each task.
- **Layering:** `recv_reply` in transport (L1) is imported down by attack (L4) and flow (L3.5); flow never imports attack. `flow/websocket.py` imports transport (L1), auth is reached via the passed `identity`/`SessionManager` (no direct auth import needed — duck-typed `.manager.apply/.ensure_fresh`).
- **Reuse:** WS steps are `action` steps returning a synthetic `Response`; the flow's existing `capture(ctx, response, step.capture)` extracts into the context — no new capture/extract code. Outgoing messages are `render_text`-templated from `build_mapping(context, data)`.
- **Behavior preserved:** `render` refactor is pure DRY; `WebSocketSender.send` refactor onto `recv_reply` keeps identical output (verified by the unchanged `tests/attack/test_ws_attack.py`).
- **Unknowns to confirm at implementation:** `FlowResult` attribute names (`.context`/`.steps`) in Task 4's test — check `penpine/flow/results.py`; `Flow(context=)` accepting a dict vs `Context` in Task 5 — check `flow.py`. Both are noted inline to match the real API.
