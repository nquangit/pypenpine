# Penpine — L2: Session & Auth (Design Spec)

**Date:** 2026-06-13
**Status:** Approved for implementation planning
**Scope:** This spec covers **L2 only** — session & auth. L0 (HTTP message core) and L1 (transport engine) are complete and merged. L3–L4 are out of scope and each get their own spec→plan→build cycle.

---

## 1. Context

L2 builds on L1's `Engine` and L0's message model. It manages authenticated sessions: it logs in, applies the session's credentials to outgoing requests, refreshes proactively (scheduler) and reactively (on auth failure), and serializes refreshes against in-flight sends so no new request grabs a session mid-swap.

What L0/L1 already provide:
- L0: `Request`/`Response`, `RequestBuilder`, `cookies.parse_set_cookie`, `get_logger`, `PenpineError`.
- L1: `Engine` (`async send` / `send_many` / sync facade), `Interceptor`/`RetrySignal` seam.

**Foundational decisions (locked across project):** async core + sync facade; HTTP/1.1; raw socket + stdlib ssl.

**L2 decisions (this round):**
- Provider model: an abstract `AuthProvider` **plus** ready-made `JsonLoginProvider` / `FormLoginProvider`.
- Validity model: local `expires_at` hint (proactive lazy refresh) **+** 401/403 trigger (reactive) **+** optional `validate()` probe.
- Gating: **barrier** — refresh blocks new sends AND drains in-flight sends before swapping the session.
- The proactive `RefreshScheduler` is **in v1**.

## 2. Goals & Non-Goals

**Goals**
- Define login/refresh/validate flows via a subclassable `AuthProvider`, with batteries-included JSON and form providers.
- Apply a session to a request via pluggable `AuthScheme`s (bearer/basic/cookie/custom header), composable.
- A `SessionManager` that owns session lifecycle and offers a **gated `send`**: ensure-fresh → apply → network (under an in-flight lease) → auth-failure retry.
- A `RefreshGate` barrier: shared send-leases vs. exclusive refresh that drains in-flight to zero.
- A `RefreshScheduler` for periodic/ahead-of-expiry gated refresh.
- A lightweight `AuthInterceptor` (L1 seam) as a secondary reactive option.
- `AuthProfile` bundling identity + provider + scheme.
- Typed errors, shared logging, fully unit-testable with no sockets.

**Non-Goals (deferred)**
- Data profiles & runtime data sharing (L3).
- Attack framework (L4).
- Multi-identity orchestration machinery — running multiple identities is simply multiple managers/profiles.
- Persistent session storage across process runs.

## 3. Module Layout

```
penpine/auth/
  __init__.py
  exceptions.py    # AuthError hierarchy
  session.py       # Session
  scheme.py        # AuthScheme + BearerAuth, BasicAuth, CookieAuth, HeaderAuth, MultiScheme
  provider.py      # AuthProvider + JsonLoginProvider, FormLoginProvider
  gate.py          # RefreshGate
  manager.py       # SessionManager
  scheduler.py     # RefreshScheduler
  interceptor.py   # AuthInterceptor
  profile.py       # AuthProfile
```

## 4. Session & AuthScheme

### 4.1 `Session`
```
@dataclass
class Session:
    token: str | None = None
    cookies: list[tuple[str, str]] = field(default_factory=list)
    headers: list[tuple[str, str]] = field(default_factory=list)
    data: dict = field(default_factory=dict)          # provider-specific (e.g. refresh_token)
    issued_at: float = field(default_factory=time.time)
    expires_at: float | None = None

    def is_expired(self, skew: float = 0.0) -> bool:
        return self.expires_at is not None and time.time() >= self.expires_at - skew
```

### 4.2 `AuthScheme`
```
class AuthScheme:
    def apply(self, request: Request, session: Session) -> Request: ...
```
Built-ins:
- `BearerAuth(token_source=None)` — sets `Authorization: Bearer <token>`; token from `session.token` or `session.data[token_source]`.
- `BasicAuth(username, password)` — static `Authorization: Basic <b64>` (degenerate provider with a no-op login is valid).
- `CookieAuth()` — merges `session.cookies` into the request `Cookie` header (preserving any existing cookies).
- `HeaderAuth(name, value_source=None)` — sets a custom header (`name`) from `session.token` or `session.data[value_source]`.
- `MultiScheme(schemes)` — applies each in order.

All return a new `Request` (L0 immutability).

## 5. AuthProvider

```
class AuthProvider:
    async def login(self, engine) -> Session:           # required (NotImplementedError)
    async def refresh(self, engine, session) -> Session: # default: return await self.login(engine)
    async def validate(self, engine, session) -> bool:   # default: return not session.is_expired()
```

Ready-made (use L0 `RequestBuilder` + the passed engine):
- **`JsonLoginProvider(url, payload, *, method="POST", token_path="$.access_token", expires_path=None, headers=None)`** — POSTs JSON, extracts token via JSONPath from the response body (`response.body.json.get(token_path)`); if `expires_path` given, reads a TTL/absolute and sets `expires_at`. Returns `Session(token=...)`. Raises `LoginError` on non-2xx or missing token.
- **`FormLoginProvider(url, fields, *, method="POST", headers=None)`** — POSTs urlencoded fields, captures every `Set-Cookie` from the response (via `cookies.parse_set_cookie`) into `session.cookies`. Returns `Session(cookies=...)`. Raises `LoginError` on non-2xx.

**Auth-flow engine:** the `engine` argument is a plain `Engine` with **no `AuthInterceptor`**, so login/refresh requests never recurse into auth handling. The `SessionManager` owns this engine (see §6).

## 6. RefreshGate & SessionManager

### 6.1 `RefreshGate` (barrier)
Async barrier coordinating shared sends vs. exclusive refresh.

- `async with gate.access():` — shared lease for one send. Waits while a refresh is pending/active; otherwise increments the in-flight counter for its duration.
- `async with gate.exclusive():` — refresh. Blocks new `access` leases, waits until in-flight drains to zero, runs the body, then re-admits. Serialized via an internal lock (one exclusive at a time).

Correctness requirements (the implementation must guarantee these, verified by tests):
1. While an `exclusive` body runs, the in-flight count is zero and no new `access` lease is granted.
2. An `exclusive` waiter does not start its body until every `access` lease taken before it has been released.
3. The check-"open" and increment-in-flight steps in `access` are atomic with respect to `exclusive` flipping the gate closed (no lost-wakeup / race admitting a late lease). Use an internal `asyncio.Lock` guarding the open-flag + counter transitions, plus events to wake waiters.
4. Leases release on exceptions (context-manager `finally`).

### 6.2 `SessionManager`
```
SessionManager(provider, scheme, *, auth_engine=None, send_engine=None,
               expiry_skew=30.0, auth_failure=lambda resp: resp.status_code in (401, 403))
```
- `auth_engine`: plain `Engine` used to run provider flows (defaults to a new `Engine()`); never carries an `AuthInterceptor`.
- `send_engine`: `Engine` used to send user requests (defaults to `auth_engine`).
- Holds the current `Session | None` and a `RefreshGate`.

Methods:
- `async ensure_fresh()` — if session is `None` or `is_expired(expiry_skew)`, run `refresh_now()`. Called *outside* any access lease.
- `async refresh_now()` — `async with gate.exclusive():` then double-check (another refresher may have just refreshed); if still stale, `login()` when no session else `refresh()`. Stores the new session.
- `apply(request) -> Request` — `scheme.apply(request, session)`.
- `is_auth_failure(response) -> bool` — the configured auth-failure predicate (default `status_code in (401, 403)`); used by both `send` and `AuthInterceptor`.
- `invalidate()` — drop the current session.
- `async send(request, *, max_auth_retries=1) -> Response`:
  ```
  for attempt in range(max_auth_retries + 1):
      await self.ensure_fresh()
      async with self._gate.access():
          req = self.apply(request)
          resp = await self._send_engine.send(req)
      if attempt < max_auth_retries and self.is_auth_failure(resp):
          self.invalidate(); continue
      return resp
  ```
- `async send_many(requests, *, return_exceptions=False)` — `asyncio.gather` over `send`, mirroring L1 semantics.
- **Sync facade:** `send_sync` / `send_many_sync` — reuse L1's background-loop pattern (a private loop thread), so `SessionManager` is usable from sync code too. `close()` stops the loop and the engines it owns.

This `send`-centric design is the crux: the in-flight drain barrier wraps the whole network call, which L1's separate `before_send`/`after_receive` hooks cannot span. Refresh always happens outside the access lease, so there is no deadlock.

## 7. RefreshScheduler

```
RefreshScheduler(manager, *, every=None, before_expiry=30.0)
```
- `async start()` — launches a background task; `async stop()` — cancels and awaits it.
- Loop: compute the next delay as the minimum of `every` (if set) and `(session.expires_at - before_expiry - now)` (if a session with `expires_at` exists); sleep; then `await manager.refresh_now()` (gated exclusive → suspends sends, drains, re-logs-in, swaps).
- `AuthError` during a scheduled refresh is logged; the loop continues to the next tick (does not crash the task).
- At least one of `every` or a session `expires_at` must be available to schedule; otherwise the scheduler idles until a session with expiry exists.

## 8. AuthInterceptor (secondary)

```
class AuthInterceptor(Interceptor):       # implements L1 Interceptor
    def __init__(self, manager): ...
    async def before_send(self, request):
        await self._manager.ensure_fresh()
        return self._manager.apply(request)
    async def after_receive(self, request, response):
        if self._manager.is_auth_failure(response):
            self._manager.invalidate()
            raise RetrySignal
        return response
```
For users who attach auth to their own `Engine` via L1's seam. **Documented tradeoff:** provides apply + reactive 401→re-login (via `RetrySignal`, needs `Engine(max_retries>=1)`) but **not** the in-flight drain barrier — the hooks can't span the network call. `SessionManager.send` is the full gated path; the interceptor is the lightweight reactive option.

## 9. AuthProfile

```
@dataclass
class AuthProfile:
    name: str
    provider: AuthProvider
    scheme: AuthScheme

    def manager(self, *, auth_engine=None, send_engine=None, **kw) -> SessionManager:
        return SessionManager(self.provider, self.scheme,
                              auth_engine=auth_engine, send_engine=send_engine, **kw)
```
The identity unit. L3's data profiles will attach to a profile.

## 10. Errors & Logging

```
AuthError(PenpineError)
├── LoginError        # login flow failed (non-2xx, missing token, etc.)
├── RefreshError      # refresh flow failed
└── AuthConfigError   # invalid provider/scheme/manager configuration
```
Each module logs via `get_logger(__name__)`: DEBUG on login/refresh start, gate open/close, drain waits; INFO on successful (re)login with identity name and (if known) expiry.

## 11. Testing Strategy (TDD)

All unit-level, no sockets. A `FakeEngine` test helper exposes `async send(request) -> Response` returning scripted `Response`s and recording sent requests.

- **Schemes:** each built-in applies correctly to a `Request` (header/cookie set, existing cookies preserved); `MultiScheme` ordering; immutability.
- **Session:** `is_expired` with/without `expires_at` and skew.
- **Providers:** `JsonLoginProvider` extracts token + expiry from a canned JSON response, raises `LoginError` on non-2xx / missing token; `FormLoginProvider` captures `Set-Cookie` into `session.cookies`.
- **RefreshGate:** in-flight leases drain before an exclusive body runs; new `access` blocks while exclusive is active and proceeds after; two exclusives serialize; leases release on exception. Asserted with ordered `asyncio` tasks + sentinels.
- **SessionManager:** lazy login on first send; proactive refresh when expired (skew); `send` applies the scheme and calls the engine; auth-failure → invalidate → re-login → retry (assert two login calls, second response returned); concurrent `send`s during a `refresh_now` are correctly gated; sync facade returns results.
- **AuthInterceptor:** `before_send` ensures+applies; `after_receive` raises `RetrySignal` on 401 and invalidates.
- **RefreshScheduler:** fires `refresh_now` on a short `every` interval; `stop()` cancels cleanly; a `LoginError` on one tick is logged and the loop survives to the next.
- **Integration:** a fake JSON login endpoint (via L1 `Engine` + stub connection factory or `FakeEngine`) end-to-end: first `send` logs in and applies bearer token; a 401 forces re-login.

## 12. Dependencies

- Runtime: none beyond L0/L1 (stdlib `asyncio`/`time`).
- Dev/test: `pytest`, `pytest-asyncio` (already configured). Python 3.11+.

## 13. Forward Hooks

- `AuthProfile` is the attachment point for L3 data profiles ("data profiles follow the auth profile").
- `SessionManager.send` / `send_many` are where L4's attack runner will route authenticated requests.
- The `auth_engine` vs `send_engine` split lets L4/observers wrap the send path without disturbing auth flows.
```
