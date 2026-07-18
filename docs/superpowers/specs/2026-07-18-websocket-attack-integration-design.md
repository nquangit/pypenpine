# WebSocket Attack Integration — Design

**Date:** 2026-07-18
**Status:** Approved (design), pending implementation plan
**Follows:** `2026-07-18-websocket-client-core-design.md` (the WS client core, merged) and
`2026-07-18-generic-fuzzing-modules-design.md` (the six modules, merged).

## Problem

penpine has a working WebSocket client (`ws_connect`) and six generic attack
modules, but the two are unconnected: the attack pipeline (analyze → generate →
send → validate → Report) is HTTP request/response-oriented, so there is no way
to run the modules against WebSocket **messages**. This adds that integration.

## Key insight (verified)

The Runner is **sender-agnostic** — anything exposing `async send(request)`
qualifies (Engine, SessionManager, Identity). And a WS message modeled as a
request body reuses the whole locator/analyzer/validator stack:

- A JSON-body `Request` yields `json:$.field` injection points, each tagged for
  `fuzz/ssti/cmdi/nosqli/sqli/…`; `replace_at("json:$.id", payload)` mutates the
  message body byte-for-byte.
- Validators only read `response.body` / `.status_code` / `.headers`, so a
  synthetic `Response(status_code=200, body=Body(reply))` drives them.

So WebSocket integration is two small adapters + one tiny core addition — the
pipeline and all six modules stay **unchanged**.

## Decisions (locked during brainstorming)

1. **Reuse the Runner via a duck-typed `WebSocketSender`** — no parallel runner.
2. **Cover JSON messages (per-field injection) AND whole-message text** — the
   latter needs a small, general new `body` locator in L0.
3. **Fresh WS connection per attempt** (open → prelude → send → recv → close),
   mirroring the HTTP one-shot model; avoids frame-correlation under concurrency.
4. **Content oracles only** — every module's body-based oracle fires over the WS
   reply; status-based anomalies don't (WS replies have no status → synthetic
   200), and `crlf` (HTTP header injection) is N/A to message bodies. Expected.

## Architecture

### Component 1 — `body` locator (L0, `penpine/core/locator.py`)

Add a `body` kind to the locator DSL:
- `resolve(request, "body")` → a `ResolvedLocator` over the raw request body.
- `request.locate("body")` → the body bytes/text.
- `request.replace_at("body", value)` → a copy with the entire body replaced.

This is general (also enables raw-body HTTP fuzzing), not WS-specific. It does NOT
need an analyzer rule — `body` points are constructed explicitly by
`ws_injection_points` (below), and the Runner accepts explicit `points=`.
`request.injection_candidates()` is NOT required to enumerate `body` (kept
conservative; a `body` candidate everywhere would over-fuzz normal HTTP runs).

### Component 2 — `penpine/attack/websocket.py`

Bridges attack (L4) and the WS client (L1). Imports `ws_connect` from transport
and attack/core models (L4→L1/L0 allowed).

```python
def ws_message_request(url: str, message: str, *, json: bool = True) -> Request:
    """Model a WS message as an attackable Request: the message is the body
    (Content-Type application/json when json=True, else text/plain). The url
    supplies scheme/host/port/target for display; WebSocketSender uses the url."""

def ws_injection_points(request) -> list[InjectionPoint]:
    """The message's own injection points: the json:* points when the body is
    JSON, otherwise a single `body` point. Excludes synthetic HTTP
    header/path-seg points."""

class WebSocketSender:
    def __init__(self, url, *, headers=None, subprotocols=None, tls=None,
                 proxy=None, timeouts=None, prelude=(), recv_count=1,
                 recv_timeout=5.0, binary=False): ...
    async def send(self, request):   # duck-typed Runner sender
        ...  # ws_connect -> send prelude -> send request body frame ->
             # recv up to recv_count replies (joined) -> close -> synthetic Response

def run_ws_attack(url, message, attack, *, json=True, points=None,
                  sender=None, **sender_kw) -> Report:
    """Convenience: build the message-request + points + WebSocketSender, run the
    Runner, return the Report. `attack` is an AttackType (or list)."""

def run_ws_attack_sync(url, message, attack, **kw) -> Report:
    """Sync facade (Runner.run_sync under the hood)."""
```

### Component 3 — `WebSocketSender.send` behavior

Per call (each Runner attempt runs concurrently, one connection each):
1. `ws = await ws_connect(url, headers=, subprotocols=, tls=, proxy=, timeouts=)`.
2. For each message in `prelude`: `await ws.send_text(m)` (setup/auth/subscribe).
3. Extract the payload message from `request.body` (`.text()`); send it —
   `ws.send_bytes(...)` if `binary` else `ws.send_text(...)`.
4. Receive up to `recv_count` reply messages via `ws.recv()`, each guarded by
   `asyncio.wait_for(..., recv_timeout)`; join their text data. On timeout or a
   `close` message, stop early with what was collected (possibly empty).
5. `await ws.close()`.
6. Return `Response(status_code=200, reason="OK",
   headers=Headers([("Content-Type","application/json" if json else "text/plain")]),
   body=Body(reply_bytes))`.

Errors: connect/handshake failures propagate (the Runner records them on the
`Attempt.error`, never aborting the batch). A recv timeout is NOT an error — it
yields an empty-body reply (a "no reply to this payload" signal the size-delta
oracle can flag against the baseline).

### Data flow

```
run_ws_attack(url, message, attack=FUZZ)
  ├─ req   = ws_message_request(url, message)          # JSON body -> json points
  ├─ points= ws_injection_points(req)                  # json:$.* (or one `body` point)
  ├─ Runner(sender=WebSocketSender(url, ...))
  │     ├─ baseline = send(req)                         # reply to the un-mutated message
  │     └─ for each point×payload: send(req.replace_at(expr, payload))
  │            WebSocketSender.send -> ws_connect -> prelude -> frame -> recv -> Response
  │            validator.evaluate(tc, reply_response, baseline) -> Finding
  └─ Report(findings, ...)
```

## Public surface & exports
Export from `penpine/attack/__init__.py`: `WebSocketSender`, `ws_message_request`,
`ws_injection_points`, `run_ws_attack`, `run_ws_attack_sync`. Re-export the
convenience names (`run_ws_attack`, `run_ws_attack_sync`, `WebSocketSender`) from
the root `penpine/__init__.py`. The `body` locator needs no new export (it is a
string expression like the other locators).

## Which modules apply
- **Fires over the WS reply body:** `fuzz` (error signatures + size delta vs
  baseline), `ssti` (eval product), `cmdi` (marker reflection), `nosqli` (NoSQL
  error signature), `ssrf` (metadata/file reflection).
- **Does not fire (expected):** status-class anomalies (WS reply is synthetic 200)
  and `crlf` (HTTP response-header injection, N/A to a message body).

## Error handling
- Runner-never-raises preserved: `WebSocketSender.send` may raise on connect
  failure → captured per attempt; recv timeout → empty reply, not an error.
- Malformed-frame testing is still available directly via the client
  (`ws.send_frame`) — out of scope for the module-driven path here.

## Testing
- **`body` locator** (`tests/core/`): `locate("body")` returns the body;
  `replace_at("body", v)` replaces the whole body; round-trips via `serialize()`.
- **`ws_message_request` / `ws_injection_points`** (`tests/attack/`): JSON body →
  `json:$.*` points (no header/path points); text body → one `body` point.
- **End-to-end** (`tests/attack/` or `tests/transport/`): an in-process WS server
  (extending the Task-4 echo server) that, per attack, produces a detectable
  reply — e.g. an SSTI server that returns the evaluated product for `{{a*b}}` in
  a JSON field, a fuzz server that returns an error signature for a fuzz payload,
  and a cmdi server that reflects the marker. Assert `run_ws_attack(...)` returns
  a `Report` with `findings`.
- **Whole-message text**: a text server that errors on a fuzz payload →
  `run_ws_attack(url, "PING", AttackType.FUZZ, json=False)` finds it via the
  `body` point.
- **Baseline + timeout**: baseline captured; a payload that gets no reply →
  empty-body Response, no crash.
- **`_sync`**: `run_ws_attack_sync` round-trip against the echo server.

## Non-goals / YAGNI
- No stateful multi-message attack sequences beyond a static `prelude` (a full
  WS "flow" is a later cycle — the Flow-engine integration).
- No auto-auth from `AuthProfile`/session into the handshake (later cycle) —
  users pass `headers=` for now.
- No reply-correlation across a shared connection (fresh connection per attempt).
- No binary-message field injection (binary passthrough only; JSON/text injection
  is v1).
- No new attack modules (reuses the six).

## Backward-compatibility notes
- Additive: a new `body` locator kind, a new `penpine/attack/websocket.py`, new
  exports. No change to existing HTTP attack behavior, the Runner, or the modules.
- `injection_candidates()` is intentionally NOT extended to emit `body`, so
  existing HTTP analyze/attack runs are unaffected.
