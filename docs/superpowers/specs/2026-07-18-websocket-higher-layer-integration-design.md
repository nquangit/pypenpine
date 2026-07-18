# WebSocket Higher-Layer Integration — Design

**Date:** 2026-07-18
**Status:** Approved (design), pending implementation plan
**Follows:** the WS client core, the six modules, and WS attack integration (all merged).

## Problem

WebSocket is integrated into the transport (client) and the attack pipeline
(`run_ws_attack`), but not into penpine's higher layers: there is no WS **flow**
step, no way to apply an **auth** session to the handshake, no `{{ }}` templating
of outgoing messages or **capture** from replies, and no **scaffold sample**. This
closes those four seams in one cohesive cycle.

## Key insight (verified against the contracts)

Everything reuses the message-as-request / reply-as-response modeling already
built for the attack path:

- `render(request, mapping)` templates a Request body/headers/target; the `{{ }}`
  engine's inner substitution can be exposed as `render_text(text, mapping)`.
- `capture(context, response, specs)` extracts from a Response into a Context via
  `Extract(json=/header=/regex=/status=/cookie=)` — a synthetic WS reply Response
  feeds it unchanged.
- `SessionManager` exposes `.session`, `.apply(request)` (= `scheme.apply(request,
  session)`), and `ensure_fresh()` — so auth headers can be lifted onto the
  handshake without sending.
- `Step(action=callable(FlowContext) -> response)` already exists and the flow
  runs `capture(ctx, response, step.capture)` on the returned response — so WS
  steps are plain `action` steps returning a synthetic Response.

## Decisions (locked during brainstorming)

1. **WS steps are `action` steps** (no new `Step` subclass); the live
   `WebSocketConnection` **persists across steps in the flow's shared `Context`**
   under a key (default `"ws"`).
2. **Reuse render/capture/extract** by returning a synthetic `Response(200,
   body=reply)` from `ws_send` and rendering outgoing messages with a new small
   `render_text`.
3. **Auth → handshake** lifts `Authorization`/`Cookie` from an
   `Identity`/`SessionManager` onto the WS handshake headers.
4. **Explicit `ws_close`** for cleanup (flows have no implicit finally).

## Architecture

### Files
- `penpine/data/template.py` — add `render_text(text, mapping, *, strict=True)`.
- `penpine/flow/websocket.py` — NEW: `ws_connect_authed`, `ws_open`, `ws_send`,
  `ws_close` (step factories). Exported from `penpine/flow/__init__.py` and root.
- `penpine/cli/templates/project/samples/websocket.py.tmpl` — NEW scaffold sample;
  added to `tests/cli/test_samples_run.py`'s `SAMPLES`.

### Layering
`penpine/flow/websocket.py` is L3.5 (flow) and may import L1 (`ws_connect`,
`WebSocketConnection`), L2 (`SessionManager`/auth), and L3 (`render_text`,
`build_mapping`, `capture`, `Extract`) — all strictly below it. No cycle.

## Component 1 — `render_text` (`penpine/data/template.py`)

Expose the existing `{{ }}` substitution for plain strings:
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
```
`render(request, mapping)` is refactored to call `render_text` internally (same
behavior; DRY). Exported from `penpine/data/__init__.py`.

## Component 2 — `ws_connect_authed` (`penpine/flow/websocket.py`)

```python
async def ws_connect_authed(url, *, identity=None, session=None, scheme=None,
                            headers=None, **connect_kw) -> WebSocketConnection:
    """ws_connect with an auth session applied to the handshake. When `identity`
    (or a SessionManager) is given, ensure it is fresh, apply its scheme to a
    dummy request for `url`, and lift the resulting Authorization/Cookie headers
    into the WS handshake (merged with `headers`)."""
```
Behavior:
- Resolve `manager` from `identity` (`identity.manager`) or accept a
  `SessionManager` directly; if only `session`+`scheme` given, use those.
- `await manager.ensure_fresh()` (login/refresh) when a manager is present.
- Build a dummy `Request.from_url(http(s)://host[:port]/path)` for the ws URL,
  `authed = manager.apply(dummy)` (or `scheme.apply(dummy, session)`), and collect
  the auth headers that changed/appeared: `Authorization`, `Cookie` (and any the
  scheme added). Merge with explicit `headers` (explicit wins).
- `return await ws_connect(url, headers=merged, **connect_kw)`.
- No identity/session → plain `ws_connect(url, headers=headers, **connect_kw)`.

## Component 3 — WS flow steps (`penpine/flow/websocket.py`)

Each returns a `Step` with an `action` callable receiving `FlowContext` (which
exposes `.ctx` and `.actor`).

```python
def ws_open(name, url, *, store="ws", identity=None, headers=None,
            guard=None, **connect_kw) -> Step: ...
def ws_send(name, message, *, store="ws", capture=None, recv=True,
            recv_timeout=5.0, recv_count=1, binary=False, guard=None) -> Step: ...
def ws_close(name, *, store="ws", guard=None) -> Step: ...
```

- **`ws_open`** action: `ws = await ws_connect_authed(url, identity=identity,
  headers=headers, **connect_kw)`; `fc.ctx.set(store, ws)`; returns `None` (no
  response; nothing to capture).
- **`ws_send`** action: `ws = fc.ctx.get(store)` (raise `FlowError` if missing);
  `mapping = build_mapping(context=fc.ctx, data=getattr(fc.actor, "data", None))`;
  `rendered = render_text(message, mapping, strict=False)`; send
  (`send_bytes` if `binary` else `send_text`); if `recv`, receive up to
  `recv_count` replies (each `asyncio.wait_for(ws.recv(), recv_timeout)`, stop on
  timeout/close), join, and return `Response(200, headers=[Content-Type],
  body=Body(reply))`. The Step is constructed with `capture=capture`, so the flow
  extracts into `fc.ctx` from that reply automatically.
- **`ws_close`** action: `ws = fc.ctx.get(store)`; if present, `await ws.close()`
  and `fc.ctx.set(store, None)`.

`ws_send` reuses `WebSocketSender`'s reply-collection logic. To avoid a layering
violation (flow L3.5 must not import attack L4), factor the recv-and-synthesize
into `recv_reply(ws, *, recv_count=1, recv_timeout=5.0, content_type="application/json")
-> Response` in **`penpine/transport/websocket.py` (L1)** — below both consumers.
`penpine/attack/websocket.py`'s `WebSocketSender.send` and
`penpine/flow/websocket.py`'s `ws_send` both import it (down-imports, no cycle);
the attack sender is refactored to call it with no behavior change.

## Component 4 — scaffold sample (`samples/websocket.py.tmpl`)

Demonstrates all three usages, **offline-safe** (guarded by a `WS_URL` config/env
so `pytest -m` sample-run stays network-free — matching how other samples avoid
network; if unset, it prints usage and exits 0):
1. Direct client: `ws = ws_connect_sync(WS_URL); ws.send_text_sync(...);
   ws.recv_sync(); ws.close_sync()`.
2. Attack: `run_ws_attack_sync(WS_URL, '{"action":"get","id":"1"}', AttackType.FUZZ)`.
3. Flow: `Flow([ws_open(...), ws_send(..., capture=[Extract(...)]), ws_close(...)])
   .run_sync()`.

Add `"websocket"` to `tests/cli/test_samples_run.py`'s `SAMPLES` (not in
`FINDING_SAMPLES`); the sample must return 0 offline.

## Data flow (a WS flow)
```
Flow([...]).run_sync()
  ws_open   -> ws_connect_authed(url, identity)      -> ctx["ws"] = WebSocketConnection
  ws_send   -> render_text(msg, ctx+data) -> ws.send -> recv reply -> Response(200)
               -> capture(ctx, reply, [Extract(...)])  -> ctx["email"] = ...
  ws_send   -> reuses ctx["ws"] (same connection), templated with captured values
  ws_close  -> ctx["ws"].close()
```

## Error handling
- Flow already records step errors on `StepResult` without leaking mid-step; a WS
  action that raises (send on a closed socket, connect failure) fails that step
  and is captured — never crashes the flow.
- `ws_send` with no stored connection → `FlowError` (recorded on the step).
- recv timeout → empty reply (not an error), consistent with the attack sender.
- No implicit connection cleanup — an unclosed connection is dropped when the
  flow's `Context`/loop is discarded; the sample uses an explicit `ws_close`.

## Testing
- **`render_text`** (`tests/data/`): renders `{{k}}` from a mapping; strict vs
  non-strict on unknown keys; `render(request, …)` still behaves identically.
- **`ws_connect_authed`** (`tests/flow/` or `tests/attack/`): with a fake
  identity/session whose scheme adds `Authorization: Bearer X`, the WS handshake
  request carries that header (assert via an in-process server that echoes the
  request headers back; no real auth provider needed) and explicit `headers`
  merge/override.
- **WS flow e2e** (`tests/flow/`): against the in-process WS server (reuse the
  Task-from-attack-integration `ws_server`), a `Flow([ws_open, ws_send(capture=…),
  ws_close])` captures a JSON field from the reply into the context; a second
  `ws_send` reuses the same connection and templates a previously-captured value;
  a `ws_send` before `ws_open` fails cleanly.
- **Scaffold sample**: runs offline (returns 0) with `WS_URL` unset.

## Non-goals / YAGNI
- No auto-close of the WS connection at flow end (explicit `ws_close`).
- No WS-specific recovery/reconnect logic (standard `Recovery` applies).
- No binary-message templating/extraction (text/JSON only; binary passthrough).
- No new attack modules or transport changes.
- No stateful multi-message *attack* sequences (the attack path stays one
  message per attempt; multi-step is the flow's job).

## Backward-compatibility notes
- Additive: `render_text` (render refactored to use it, same behavior), a new
  `penpine/flow/websocket.py`, a `_recv_reply` helper shared with the attack
  sender (no behavior change), a new sample, new exports. No change to existing
  flow/auth/data/attack behavior.
