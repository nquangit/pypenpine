# Penpine L2 — Session & Auth Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build L2 of Penpine — authenticated session management: pluggable login providers and auth schemes, a barrier-gated `SessionManager.send` (ensure-fresh → apply → gated network → 401 re-login), a proactive `RefreshScheduler`, and an L1 interceptor option.

**Architecture:** Sits on L0 (message model) and L1 (`Engine`). `AuthScheme` applies a `Session` to a `Request`; `AuthProvider` runs login/refresh/validate flows via an engine; `RefreshGate` is an async barrier serializing refreshes against in-flight sends; `SessionManager.send` ties it together with a 401-retry loop; `RefreshScheduler` does proactive gated refresh. All unit-testable with a `FakeEngine` (no sockets).

**Tech Stack:** Python 3.11+, stdlib `asyncio`/`time`, `pytest`, `pytest-asyncio` (already configured). Depends on L0 + L1 (on `main`).

---

## File Structure

```
penpine/auth/
  __init__.py      # public exports
  exceptions.py    # AuthError hierarchy
  session.py       # Session
  scheme.py        # AuthScheme + BearerAuth/BasicAuth/CookieAuth/HeaderAuth/MultiScheme
  provider.py      # AuthProvider + JsonLoginProvider/FormLoginProvider
  gate.py          # RefreshGate
  manager.py       # SessionManager
  scheduler.py     # RefreshScheduler
  interceptor.py   # AuthInterceptor
  profile.py       # AuthProfile
tests/auth/
  _fakes.py        # FakeEngine test helper
  ... mirrors the above
```

Build order: scaffolding → exceptions → session → scheme → provider(+FakeEngine) → gate → manager core → manager send_many/sync → interceptor → scheduler → profile/public API/integration.

---

## Task 0: Scaffolding

**Files:**
- Create: `penpine/auth/__init__.py`, `tests/auth/__init__.py`

- [ ] **Step 1: Create empty package inits**

Create empty files: `penpine/auth/__init__.py`, `tests/auth/__init__.py`.

- [ ] **Step 2: Verify suite still green**

Run: `python -m pytest -q`
Expected: `120 passed` (L0+L1 unaffected).

- [ ] **Step 3: Commit**

```bash
git add penpine/auth tests/auth
git commit -c commit.gpgsign=false -m "chore: scaffold L2 auth package"
```

---

## Task 1: Exceptions

**Files:**
- Create: `penpine/auth/exceptions.py`
- Test: `tests/auth/test_exceptions.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/auth/test_exceptions.py
from penpine.exceptions import PenpineError
from penpine.auth.exceptions import AuthError, LoginError, RefreshError, AuthConfigError


def test_hierarchy():
    for cls in (LoginError, RefreshError, AuthConfigError):
        assert issubclass(cls, AuthError)
    assert issubclass(AuthError, PenpineError)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/auth/test_exceptions.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Write minimal implementation**

```python
# penpine/auth/exceptions.py
"""Auth-layer exceptions."""
from __future__ import annotations

from penpine.exceptions import PenpineError


class AuthError(PenpineError):
    """Base class for auth failures."""


class LoginError(AuthError):
    """A login flow failed."""


class RefreshError(AuthError):
    """A refresh flow failed."""


class AuthConfigError(AuthError):
    """Invalid auth configuration."""
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/auth/test_exceptions.py -v`
Expected: PASS (1 passed).

- [ ] **Step 5: Commit**

```bash
git add penpine/auth/exceptions.py tests/auth/test_exceptions.py
git commit -c commit.gpgsign=false -m "feat: add auth exception hierarchy"
```

---

## Task 2: Session

**Files:**
- Create: `penpine/auth/session.py`
- Test: `tests/auth/test_session.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/auth/test_session.py
import time
from penpine.auth.session import Session


def test_defaults():
    s = Session()
    assert s.token is None
    assert s.cookies == []
    assert s.headers == []
    assert s.data == {}
    assert s.expires_at is None
    assert s.issued_at <= time.time()


def test_is_expired_without_expiry_is_false():
    assert Session().is_expired() is False


def test_is_expired_true_and_skew():
    past = Session(expires_at=time.time() - 1)
    assert past.is_expired() is True
    future = Session(expires_at=time.time() + 100)
    assert future.is_expired() is False
    # skew makes a soon-to-expire session count as expired
    assert future.is_expired(skew=200) is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/auth/test_session.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Write minimal implementation**

```python
# penpine/auth/session.py
"""Session: auth material produced by a login/refresh, plus expiry metadata."""
from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class Session:
    token: str | None = None
    cookies: list[tuple[str, str]] = field(default_factory=list)
    headers: list[tuple[str, str]] = field(default_factory=list)
    data: dict = field(default_factory=dict)
    issued_at: float = field(default_factory=time.time)
    expires_at: float | None = None

    def is_expired(self, skew: float = 0.0) -> bool:
        return self.expires_at is not None and time.time() >= self.expires_at - skew
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/auth/test_session.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add penpine/auth/session.py tests/auth/test_session.py
git commit -c commit.gpgsign=false -m "feat: add Session with expiry"
```

---

## Task 3: AuthScheme + built-ins

**Files:**
- Create: `penpine/auth/scheme.py`
- Test: `tests/auth/test_scheme.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/auth/test_scheme.py
from penpine.core.message import Request
from penpine.core.headers import Headers
from penpine.auth.session import Session
from penpine.auth.scheme import (
    BearerAuth, BasicAuth, CookieAuth, HeaderAuth, MultiScheme,
)


def base_request(headers=None):
    return Request(method="GET", target="/", version="HTTP/1.1",
                   headers=Headers(headers or []))


def test_bearer_from_token():
    r = BearerAuth().apply(base_request(), Session(token="abc"))
    assert r.headers["Authorization"] == "Bearer abc"


def test_bearer_from_data_source():
    s = Session(data={"access": "xyz"})
    r = BearerAuth(token_source="access").apply(base_request(), s)
    assert r.headers["Authorization"] == "Bearer xyz"


def test_basic_static():
    r = BasicAuth("user", "pass").apply(base_request(), Session())
    # base64("user:pass") == dXNlcjpwYXNz
    assert r.headers["Authorization"] == "Basic dXNlcjpwYXNz"


def test_header_auth_custom():
    r = HeaderAuth("X-API-Key").apply(base_request(), Session(token="k1"))
    assert r.headers["X-API-Key"] == "k1"


def test_cookie_merges_and_overrides():
    req = base_request([("Cookie", "a=1; b=2")])
    s = Session(cookies=[("b", "9"), ("c", "3")])
    r = CookieAuth().apply(req, s)
    assert r.headers["Cookie"] == "a=1; b=9; c=3"


def test_multi_scheme_applies_in_order():
    s = Session(token="t", cookies=[("sid", "x")])
    r = MultiScheme([BearerAuth(), CookieAuth()]).apply(base_request(), s)
    assert r.headers["Authorization"] == "Bearer t"
    assert r.headers["Cookie"] == "sid=x"


def test_apply_returns_new_request():
    req = base_request()
    r = BearerAuth().apply(req, Session(token="t"))
    assert "Authorization" not in req.headers
    assert r is not req
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/auth/test_scheme.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Write minimal implementation**

```python
# penpine/auth/scheme.py
"""AuthScheme: how a Session is applied to a Request."""
from __future__ import annotations

import base64

from penpine.core.cookies import parse_cookie_header
from penpine.core.message import Request
from penpine.auth.session import Session


class AuthScheme:
    def apply(self, request: Request, session: Session) -> Request:
        raise NotImplementedError


class BearerAuth(AuthScheme):
    def __init__(self, token_source: str | None = None):
        self._source = token_source

    def apply(self, request: Request, session: Session) -> Request:
        token = session.data[self._source] if self._source else session.token
        return request.set_header("Authorization", f"Bearer {token}")


class BasicAuth(AuthScheme):
    def __init__(self, username: str, password: str):
        self._username = username
        self._password = password

    def apply(self, request: Request, session: Session) -> Request:
        token = base64.b64encode(f"{self._username}:{self._password}".encode()).decode()
        return request.set_header("Authorization", f"Basic {token}")


class HeaderAuth(AuthScheme):
    def __init__(self, name: str, value_source: str | None = None):
        self._name = name
        self._source = value_source

    def apply(self, request: Request, session: Session) -> Request:
        value = session.data[self._source] if self._source else session.token
        return request.set_header(self._name, value)


class CookieAuth(AuthScheme):
    def apply(self, request: Request, session: Session) -> Request:
        merged: list[list[str]] = []
        index: dict[str, int] = {}
        for name, value in parse_cookie_header(request.headers.get("Cookie", "")):
            index[name] = len(merged)
            merged.append([name, value])
        for name, value in session.cookies:
            if name in index:
                merged[index[name]][1] = value
            else:
                index[name] = len(merged)
                merged.append([name, value])
        cookie = "; ".join(f"{name}={value}" for name, value in merged)
        return request.set_header("Cookie", cookie)


class MultiScheme(AuthScheme):
    def __init__(self, schemes):
        self._schemes = list(schemes)

    def apply(self, request: Request, session: Session) -> Request:
        for scheme in self._schemes:
            request = scheme.apply(request, session)
        return request
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/auth/test_scheme.py -v`
Expected: PASS (7 passed).

- [ ] **Step 5: Commit**

```bash
git add penpine/auth/scheme.py tests/auth/test_scheme.py
git commit -c commit.gpgsign=false -m "feat: add auth schemes (bearer/basic/cookie/header/multi)"
```

---

## Task 4: FakeEngine helper + AuthProvider + ready-made providers

**Files:**
- Create: `tests/auth/_fakes.py`, `penpine/auth/provider.py`
- Test: `tests/auth/test_provider.py`

- [ ] **Step 1: Create the FakeEngine test helper**

```python
# tests/auth/_fakes.py
"""Async engine stub for auth tests (no sockets)."""
import asyncio

from penpine.core.parse.http_parser import parse_response


class FakeEngine:
    """`script` is a list of raw response bytes, or callables taking the request
    and returning raw bytes. The last entry repeats once exhausted."""

    def __init__(self, script):
        self._script = list(script)
        self._i = 0
        self.sent = []

    async def send(self, request):
        self.sent.append(request)
        idx = min(self._i, len(self._script) - 1)
        self._i += 1
        item = self._script[idx]
        raw = item(request) if callable(item) else item
        return parse_response(raw)

    async def send_many(self, requests, *, return_exceptions=False):
        return await asyncio.gather(
            *(self.send(r) for r in requests), return_exceptions=return_exceptions)
```

- [ ] **Step 2: Write the failing test**

```python
# tests/auth/test_provider.py
import pytest

from penpine.auth.provider import AuthProvider, JsonLoginProvider, FormLoginProvider
from penpine.auth.exceptions import LoginError
from tests.auth._fakes import FakeEngine


async def test_json_provider_extracts_token():
    engine = FakeEngine([b'HTTP/1.1 200 OK\r\nContent-Length: 21\r\n\r\n{"access_token":"T1"}'])
    p = JsonLoginProvider("http://h/login", {"u": "a", "p": "b"})
    session = await p.login(engine)
    assert session.token == "T1"
    # the login request carried the JSON payload
    assert engine.sent[0].method == "POST"
    assert b'"u": "a"' in engine.sent[0].body.raw


async def test_json_provider_reads_expiry_ttl():
    import time
    raw = b'HTTP/1.1 200 OK\r\nContent-Length: 36\r\n\r\n{"access_token":"T","expires_in":60}'
    engine = FakeEngine([raw])
    p = JsonLoginProvider("http://h/login", {}, expires_path="$.expires_in")
    session = await p.login(engine)
    assert session.expires_at is not None
    assert abs(session.expires_at - (time.time() + 60)) < 5


async def test_json_provider_non_2xx_raises():
    engine = FakeEngine([b"HTTP/1.1 401 Unauthorized\r\nContent-Length: 0\r\n\r\n"])
    p = JsonLoginProvider("http://h/login", {})
    with pytest.raises(LoginError):
        await p.login(engine)


async def test_json_provider_missing_token_raises():
    engine = FakeEngine([b'HTTP/1.1 200 OK\r\nContent-Length: 11\r\n\r\n{"nope":1}\n'])
    p = JsonLoginProvider("http://h/login", {})
    with pytest.raises(LoginError):
        await p.login(engine)


async def test_form_provider_captures_cookies():
    raw = (b"HTTP/1.1 200 OK\r\nSet-Cookie: sid=abc; Path=/\r\n"
           b"Set-Cookie: csrf=xyz\r\nContent-Length: 0\r\n\r\n")
    engine = FakeEngine([raw])
    p = FormLoginProvider("http://h/login", {"user": "a", "pass": "b"})
    session = await p.login(engine)
    assert ("sid", "abc") in session.cookies
    assert ("csrf", "xyz") in session.cookies


async def test_default_refresh_calls_login():
    engine = FakeEngine([b'HTTP/1.1 200 OK\r\nContent-Length: 21\r\n\r\n{"access_token":"T2"}'])
    p = JsonLoginProvider("http://h/login", {})
    session = await p.refresh(engine, None)
    assert session.token == "T2"


async def test_base_login_not_implemented():
    with pytest.raises(NotImplementedError):
        await AuthProvider().login(FakeEngine([]))
```

- [ ] **Step 3: Run test to verify it fails**

Run: `python -m pytest tests/auth/test_provider.py -v`
Expected: FAIL — module missing.

- [ ] **Step 4: Write minimal implementation**

```python
# penpine/auth/provider.py
"""AuthProvider: login/refresh/validate flows, plus ready-made providers."""
from __future__ import annotations

import time

from penpine.auth.exceptions import LoginError
from penpine.auth.session import Session
from penpine.core.builder import RequestBuilder
from penpine.core.cookies import parse_set_cookie


class AuthProvider:
    async def login(self, engine) -> Session:
        raise NotImplementedError

    async def refresh(self, engine, session) -> Session:
        return await self.login(engine)

    async def validate(self, engine, session) -> bool:
        return not session.is_expired()


def _check_2xx(resp) -> None:
    if not (200 <= resp.status_code < 300):
        raise LoginError(f"login failed: HTTP {resp.status_code}")


class JsonLoginProvider(AuthProvider):
    def __init__(self, url, payload, *, method="POST", token_path="$.access_token",
                 expires_path=None, headers=None):
        self._url = url
        self._payload = payload
        self._method = method
        self._token_path = token_path
        self._expires_path = expires_path
        self._headers = headers or {}

    async def login(self, engine) -> Session:
        builder = RequestBuilder().method(self._method).url(self._url).json(self._payload)
        for name, value in self._headers.items():
            builder = builder.header(name, value)
        resp = await engine.send(builder.build())
        _check_2xx(resp)
        try:
            token = resp.body.json.get(self._token_path)
        except Exception as exc:
            raise LoginError(f"token not found at {self._token_path}") from exc
        expires_at = None
        if self._expires_path:
            try:
                expires_at = time.time() + float(resp.body.json.get(self._expires_path))
            except Exception:
                expires_at = None
        return Session(token=token, expires_at=expires_at)


class FormLoginProvider(AuthProvider):
    def __init__(self, url, fields, *, method="POST", headers=None):
        self._url = url
        self._fields = fields
        self._method = method
        self._headers = headers or {}

    async def login(self, engine) -> Session:
        builder = RequestBuilder().method(self._method).url(self._url).form(self._fields)
        for name, value in self._headers.items():
            builder = builder.header(name, value)
        resp = await engine.send(builder.build())
        _check_2xx(resp)
        cookies = []
        for name, value in resp.headers.items():
            if name.lower() == "set-cookie":
                parsed = parse_set_cookie(value)
                cookies.append((parsed.name, parsed.value))
        return Session(cookies=cookies)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest tests/auth/test_provider.py -v`
Expected: PASS (7 passed).

- [ ] **Step 6: Commit**

```bash
git add tests/auth/_fakes.py penpine/auth/provider.py tests/auth/test_provider.py
git commit -c commit.gpgsign=false -m "feat: add AuthProvider with JSON and form login providers"
```

---

## Task 5: RefreshGate (barrier)

**Files:**
- Create: `penpine/auth/gate.py`
- Test: `tests/auth/test_gate.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/auth/test_gate.py
import asyncio
import pytest

from penpine.auth.gate import RefreshGate


async def test_exclusive_waits_for_inflight_to_drain():
    gate = RefreshGate()
    order = []
    started = asyncio.Event()
    release = asyncio.Event()

    async def worker():
        async with gate.access():
            started.set()
            order.append("access-in")
            await release.wait()
        order.append("access-out")

    async def refresher():
        async with gate.exclusive():
            order.append("exclusive-body")

    w = asyncio.create_task(worker())
    await started.wait()
    r = asyncio.create_task(refresher())
    await asyncio.sleep(0.02)
    assert "exclusive-body" not in order      # blocked while in-flight lease held
    release.set()
    await asyncio.gather(w, r)
    assert order == ["access-in", "access-out", "exclusive-body"]


async def test_new_access_blocked_during_exclusive():
    gate = RefreshGate()
    order = []
    in_exclusive = asyncio.Event()
    finish_exclusive = asyncio.Event()

    async def refresher():
        async with gate.exclusive():
            in_exclusive.set()
            order.append("exclusive-in")
            await finish_exclusive.wait()
        order.append("exclusive-out")

    async def worker():
        async with gate.access():
            order.append("access-body")

    r = asyncio.create_task(refresher())
    await in_exclusive.wait()
    w = asyncio.create_task(worker())
    await asyncio.sleep(0.02)
    assert "access-body" not in order         # access waits during exclusive
    finish_exclusive.set()
    await asyncio.gather(r, w)
    assert order == ["exclusive-in", "exclusive-out", "access-body"]


async def test_two_exclusives_serialize():
    gate = RefreshGate()
    order = []

    async def refresher(tag):
        async with gate.exclusive():
            order.append(f"{tag}-in")
            await asyncio.sleep(0.01)
            order.append(f"{tag}-out")

    await asyncio.gather(refresher("a"), refresher("b"))
    # one fully completes before the other starts
    assert order in (
        ["a-in", "a-out", "b-in", "b-out"],
        ["b-in", "b-out", "a-in", "a-out"],
    )


async def test_lease_releases_on_exception():
    gate = RefreshGate()
    with pytest.raises(ValueError):
        async with gate.access():
            raise ValueError("boom")
    # a subsequent exclusive must not hang (in-flight properly decremented)
    async with gate.exclusive():
        pass
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/auth/test_gate.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Write minimal implementation**

```python
# penpine/auth/gate.py
"""RefreshGate: an async barrier coordinating shared sends vs. exclusive refresh.

Correctness is guarded by a single asyncio.Condition: all transitions of the
open-flag and in-flight counter happen under its lock, and waiters re-check
their predicate after every wake.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager


class RefreshGate:
    def __init__(self):
        self._cond = asyncio.Condition()
        self._open = True
        self._in_flight = 0

    @asynccontextmanager
    async def access(self):
        async with self._cond:
            while not self._open:
                await self._cond.wait()
            self._in_flight += 1
        try:
            yield
        finally:
            async with self._cond:
                self._in_flight -= 1
                if self._in_flight == 0:
                    self._cond.notify_all()

    @asynccontextmanager
    async def exclusive(self):
        async with self._cond:
            while not self._open:          # serialize against other exclusives
                await self._cond.wait()
            self._open = False             # stop admitting new access leases
            while self._in_flight > 0:      # drain in-flight sends
                await self._cond.wait()
        try:
            yield
        finally:
            async with self._cond:
                self._open = True
                self._cond.notify_all()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/auth/test_gate.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add penpine/auth/gate.py tests/auth/test_gate.py
git commit -c commit.gpgsign=false -m "feat: add RefreshGate barrier"
```

---

## Task 6: SessionManager core

**Files:**
- Create: `penpine/auth/manager.py`
- Test: `tests/auth/test_manager.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/auth/test_manager.py
import asyncio

from penpine.core.message import Request
from penpine.auth.manager import SessionManager
from penpine.auth.provider import AuthProvider
from penpine.auth.scheme import BearerAuth
from penpine.auth.session import Session
from tests.auth._fakes import FakeEngine


class StubProvider(AuthProvider):
    def __init__(self):
        self.logins = 0

    async def login(self, engine):
        self.logins += 1
        return Session(token=f"tok{self.logins}")


def req():
    return Request.from_url("http://h:8080/resource")


def ok():
    return b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nok"


def unauthorized():
    return b"HTTP/1.1 401 Unauthorized\r\nContent-Length: 0\r\n\r\n"


async def test_first_send_logs_in_and_applies_scheme():
    provider = StubProvider()
    engine = FakeEngine([ok()])
    mgr = SessionManager(provider, BearerAuth(), auth_engine=FakeEngine([]),
                         send_engine=engine)
    resp = await mgr.send(req())
    assert resp.status_code == 200
    assert provider.logins == 1
    assert engine.sent[0].headers["Authorization"] == "Bearer tok1"


async def test_expired_session_triggers_refresh():
    provider = StubProvider()
    engine = FakeEngine([ok()])
    mgr = SessionManager(provider, BearerAuth(), auth_engine=FakeEngine([]),
                         send_engine=engine, expiry_skew=0)
    # seed an already-expired session
    import time
    mgr._session = Session(token="old", expires_at=time.time() - 1)
    await mgr.send(req())
    assert provider.logins == 1   # refresh (default = login) ran
    assert engine.sent[0].headers["Authorization"] == "Bearer tok1"


async def test_401_triggers_relogin_and_retry():
    provider = StubProvider()
    engine = FakeEngine([unauthorized(), ok()])
    mgr = SessionManager(provider, BearerAuth(), auth_engine=FakeEngine([]),
                         send_engine=engine)
    resp = await mgr.send(req())
    assert resp.status_code == 200
    assert provider.logins == 2                      # logged in, then re-logged in
    assert engine.sent[1].headers["Authorization"] == "Bearer tok2"


async def test_concurrent_first_sends_log_in_once():
    provider = StubProvider()
    engine = FakeEngine([ok()])
    mgr = SessionManager(provider, BearerAuth(), auth_engine=FakeEngine([]),
                         send_engine=engine)
    await asyncio.gather(*(mgr.send(req()) for _ in range(5)))
    assert provider.logins == 1                      # the gate de-duplicated the herd


async def test_is_auth_failure_default():
    mgr = SessionManager(StubProvider(), BearerAuth())
    from penpine.core.parse.http_parser import parse_response
    assert mgr.is_auth_failure(parse_response(unauthorized())) is True
    assert mgr.is_auth_failure(parse_response(ok())) is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/auth/test_manager.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Write minimal implementation**

```python
# penpine/auth/manager.py
"""SessionManager: session lifecycle + gated send with auth retry."""
from __future__ import annotations

from penpine.auth.gate import RefreshGate
from penpine.transport.engine import Engine


def _default_auth_failure(response) -> bool:
    return response.status_code in (401, 403)


class SessionManager:
    def __init__(self, provider, scheme, *, auth_engine=None, send_engine=None,
                 expiry_skew=30.0, auth_failure=None):
        self._provider = provider
        self._scheme = scheme
        self._auth_engine = auth_engine if auth_engine is not None else Engine()
        self._send_engine = send_engine if send_engine is not None else self._auth_engine
        self._skew = expiry_skew
        self._auth_failure = auth_failure or _default_auth_failure
        self._session = None
        self._gate = RefreshGate()

    @property
    def session(self):
        return self._session

    def is_auth_failure(self, response) -> bool:
        return self._auth_failure(response)

    def apply(self, request):
        return self._scheme.apply(request, self._session)

    def invalidate(self) -> None:
        self._session = None

    async def ensure_fresh(self) -> None:
        if self._session is None or self._session.is_expired(self._skew):
            await self.refresh_now()

    async def refresh_now(self, *, force=False) -> None:
        async with self._gate.exclusive():
            if self._session is None:
                self._session = await self._provider.login(self._auth_engine)
            elif force or self._session.is_expired(self._skew):
                self._session = await self._provider.refresh(self._auth_engine, self._session)

    async def send(self, request, *, max_auth_retries=1):
        resp = None
        for attempt in range(max_auth_retries + 1):
            await self.ensure_fresh()
            async with self._gate.access():
                req = self.apply(request)
                resp = await self._send_engine.send(req)
            if attempt < max_auth_retries and self.is_auth_failure(resp):
                self.invalidate()
                continue
            return resp
        return resp
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/auth/test_manager.py -v`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add penpine/auth/manager.py tests/auth/test_manager.py
git commit -c commit.gpgsign=false -m "feat: add SessionManager with gated send and auth retry"
```

---

## Task 7: SessionManager.send_many + sync facade

**Files:**
- Modify: `penpine/auth/manager.py`
- Test: `tests/auth/test_manager_sync.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/auth/test_manager_sync.py
from penpine.core.message import Request
from penpine.auth.manager import SessionManager
from penpine.auth.provider import AuthProvider
from penpine.auth.scheme import BearerAuth
from penpine.auth.session import Session
from tests.auth._fakes import FakeEngine


class StubProvider(AuthProvider):
    async def login(self, engine):
        return Session(token="t")


def req():
    return Request.from_url("http://h:8080/r")


def ok():
    return b"HTTP/1.1 200 OK\r\nContent-Length: 0\r\n\r\n"


async def test_send_many_preserves_order():
    mgr = SessionManager(StubProvider(), BearerAuth(),
                         auth_engine=FakeEngine([]), send_engine=FakeEngine([ok()]))
    resps = await mgr.send_many([req(), req(), req()])
    assert [r.status_code for r in resps] == [200, 200, 200]


def test_send_sync_and_context_manager():
    with SessionManager(StubProvider(), BearerAuth(),
                        auth_engine=FakeEngine([]),
                        send_engine=FakeEngine([ok()])) as mgr:
        resp = mgr.send_sync(req())
        assert resp.status_code == 200
        resps = mgr.send_many_sync([req(), req()])
        assert [r.status_code for r in resps] == [200, 200]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/auth/test_manager_sync.py -v`
Expected: FAIL — `send_many`/`send_sync` missing.

- [ ] **Step 3: Write minimal implementation**

Add `import asyncio` and `import threading` at the top of `penpine/auth/manager.py` (below `from __future__ import annotations`). In `SessionManager.__init__`, add at the end:

```python
        self._loop = None
        self._loop_thread = None
```

Add these methods to `class SessionManager` (after `send`):

```python
    async def send_many(self, requests, *, return_exceptions=False):
        return await asyncio.gather(
            *(self.send(r) for r in requests), return_exceptions=return_exceptions)

    def _ensure_loop(self):
        if self._loop is None:
            self._loop = asyncio.new_event_loop()
            self._loop_thread = threading.Thread(
                target=self._loop.run_forever, daemon=True)
            self._loop_thread.start()

    def send_sync(self, request, **kwargs):
        self._ensure_loop()
        return asyncio.run_coroutine_threadsafe(
            self.send(request, **kwargs), self._loop).result()

    def send_many_sync(self, requests, **kwargs):
        self._ensure_loop()
        return asyncio.run_coroutine_threadsafe(
            self.send_many(requests, **kwargs), self._loop).result()

    def close(self):
        if self._loop is not None:
            self._loop.call_soon_threadsafe(self._loop.stop)
            self._loop_thread.join(timeout=2)
            self._loop.close()
            self._loop = None
            self._loop_thread = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/auth/test_manager_sync.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add penpine/auth/manager.py tests/auth/test_manager_sync.py
git commit -c commit.gpgsign=false -m "feat: add SessionManager.send_many and sync facade"
```

---

## Task 8: AuthInterceptor

**Files:**
- Create: `penpine/auth/interceptor.py`
- Test: `tests/auth/test_interceptor.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/auth/test_interceptor.py
import pytest

from penpine.core.message import Request
from penpine.core.parse.http_parser import parse_response
from penpine.auth.interceptor import AuthInterceptor
from penpine.auth.manager import SessionManager
from penpine.auth.provider import AuthProvider
from penpine.auth.scheme import BearerAuth
from penpine.auth.session import Session
from penpine.transport.interceptor import RetrySignal
from tests.auth._fakes import FakeEngine


class StubProvider(AuthProvider):
    async def login(self, engine):
        return Session(token="t")


def manager():
    return SessionManager(StubProvider(), BearerAuth(), auth_engine=FakeEngine([]))


async def test_before_send_ensures_and_applies():
    ic = AuthInterceptor(manager())
    out = await ic.before_send(Request.from_url("http://h/r"))
    assert out.headers["Authorization"] == "Bearer t"


async def test_after_receive_raises_retry_on_401():
    mgr = manager()
    await mgr.ensure_fresh()
    assert mgr.session is not None
    ic = AuthInterceptor(mgr)
    resp = parse_response(b"HTTP/1.1 401 Unauthorized\r\nContent-Length: 0\r\n\r\n")
    with pytest.raises(RetrySignal):
        await ic.after_receive(Request.from_url("http://h/r"), resp)
    assert mgr.session is None      # invalidated


async def test_after_receive_passes_through_on_200():
    ic = AuthInterceptor(manager())
    resp = parse_response(b"HTTP/1.1 200 OK\r\nContent-Length: 0\r\n\r\n")
    out = await ic.after_receive(Request.from_url("http://h/r"), resp)
    assert out is resp
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/auth/test_interceptor.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Write minimal implementation**

```python
# penpine/auth/interceptor.py
"""AuthInterceptor: lightweight L1-seam auth (apply + reactive 401 retry).

Does NOT provide the in-flight drain barrier (the L1 hooks cannot span the
network call). Use SessionManager.send for the full gated path.
"""
from __future__ import annotations

from penpine.transport.interceptor import Interceptor, RetrySignal


class AuthInterceptor(Interceptor):
    def __init__(self, manager):
        self._manager = manager

    async def before_send(self, request):
        await self._manager.ensure_fresh()
        return self._manager.apply(request)

    async def after_receive(self, request, response):
        if self._manager.is_auth_failure(response):
            self._manager.invalidate()
            raise RetrySignal
        return response
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/auth/test_interceptor.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add penpine/auth/interceptor.py tests/auth/test_interceptor.py
git commit -c commit.gpgsign=false -m "feat: add AuthInterceptor (L1-seam reactive auth)"
```

---

## Task 9: RefreshScheduler

**Files:**
- Create: `penpine/auth/scheduler.py`
- Test: `tests/auth/test_scheduler.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/auth/test_scheduler.py
import asyncio

from penpine.auth.scheduler import RefreshScheduler
from penpine.auth.manager import SessionManager
from penpine.auth.provider import AuthProvider
from penpine.auth.scheme import BearerAuth
from penpine.auth.session import Session
from penpine.auth.exceptions import LoginError
from tests.auth._fakes import FakeEngine


class CountingProvider(AuthProvider):
    def __init__(self, fail_on=None):
        self.logins = 0
        self.fail_on = fail_on

    async def login(self, engine):
        self.logins += 1
        if self.fail_on is not None and self.logins == self.fail_on:
            raise LoginError("boom")
        return Session(token=f"t{self.logins}")


def manager(provider):
    return SessionManager(provider, BearerAuth(), auth_engine=FakeEngine([]))


async def test_scheduler_fires_periodically():
    provider = CountingProvider()
    mgr = manager(provider)
    sched = RefreshScheduler(mgr, every=0.02)
    await sched.start()
    await asyncio.sleep(0.09)
    await sched.stop()
    assert provider.logins >= 2          # fired multiple times


async def test_stop_halts_refreshes():
    provider = CountingProvider()
    mgr = manager(provider)
    sched = RefreshScheduler(mgr, every=0.02)
    await sched.start()
    await asyncio.sleep(0.05)
    await sched.stop()
    count = provider.logins
    await asyncio.sleep(0.05)
    assert provider.logins == count       # no more refreshes after stop


async def test_scheduler_survives_login_error():
    provider = CountingProvider(fail_on=2)
    mgr = manager(provider)
    sched = RefreshScheduler(mgr, every=0.02)
    await sched.start()
    await asyncio.sleep(0.09)
    running = not sched._task.done()
    await sched.stop()
    assert running                        # one failing tick did not kill the loop
    assert provider.logins >= 3
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/auth/test_scheduler.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Write minimal implementation**

```python
# penpine/auth/scheduler.py
"""RefreshScheduler: periodic / ahead-of-expiry gated session refresh."""
from __future__ import annotations

import asyncio
import time

from penpine.auth.exceptions import AuthError
from penpine.logging import get_logger

log = get_logger(__name__)


class RefreshScheduler:
    def __init__(self, manager, *, every=None, before_expiry=30.0):
        self._manager = manager
        self._every = every
        self._before_expiry = before_expiry
        self._task = None

    def _next_delay(self) -> float:
        delays = []
        if self._every is not None:
            delays.append(self._every)
        session = self._manager.session
        if session is not None and session.expires_at is not None:
            delays.append(max(0.0, session.expires_at - self._before_expiry - time.time()))
        if not delays:
            return self._every if self._every is not None else 1.0
        return max(0.0, min(delays))

    async def _run(self):
        while True:
            await asyncio.sleep(self._next_delay())
            try:
                await self._manager.refresh_now(force=True)
            except AuthError as exc:
                log.warning("scheduled refresh failed: %s", exc)

    async def start(self):
        if self._task is None:
            self._task = asyncio.create_task(self._run())

    async def stop(self):
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/auth/test_scheduler.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add penpine/auth/scheduler.py tests/auth/test_scheduler.py
git commit -c commit.gpgsign=false -m "feat: add RefreshScheduler for proactive gated refresh"
```

---

## Task 10: AuthProfile + public API + integration

**Files:**
- Create: `penpine/auth/profile.py`
- Modify: `penpine/auth/__init__.py`, `penpine/__init__.py`
- Test: `tests/auth/test_profile.py`, `tests/auth/test_integration.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/auth/test_profile.py
import penpine
from penpine.auth import (
    AuthProfile, SessionManager, Session, AuthProvider, JsonLoginProvider,
    BearerAuth, RefreshScheduler, AuthInterceptor, RefreshGate, AuthError,
)
from penpine.auth.scheme import BearerAuth as BearerAuth2
from tests.auth._fakes import FakeEngine


class StubProvider(AuthProvider):
    async def login(self, engine):
        return Session(token="t")


def test_profile_builds_manager():
    profile = AuthProfile("admin", StubProvider(), BearerAuth())
    mgr = profile.manager(auth_engine=FakeEngine([]))
    assert isinstance(mgr, SessionManager)
    assert profile.name == "admin"


def test_public_exports():
    assert all([AuthProfile, SessionManager, RefreshScheduler, AuthInterceptor,
                RefreshGate, JsonLoginProvider, AuthError])
    assert hasattr(penpine, "SessionManager")
    assert hasattr(penpine, "AuthProfile")
    assert penpine.SessionManager is SessionManager
```

```python
# tests/auth/test_integration.py
from penpine.core.message import Request
from penpine.auth.manager import SessionManager
from penpine.auth.provider import JsonLoginProvider
from penpine.auth.scheme import BearerAuth
from tests.auth._fakes import FakeEngine


def login_response(request):
    # rotate token per login call so re-login yields a fresh token
    login_response.n += 1
    body = b'{"access_token":"TOK%d"}' % login_response.n
    return (b"HTTP/1.1 200 OK\r\nContent-Length: " + str(len(body)).encode()
            + b"\r\n\r\n" + body)
login_response.n = 0


def protected(request):
    # 401 unless an Authorization header is present AND it is the latest token
    auth = request.headers.get("Authorization")
    if auth == f"Bearer TOK{login_response.n}":
        return b"HTTP/1.1 200 OK\r\nContent-Length: 3\r\n\r\nyes"
    return b"HTTP/1.1 401 Unauthorized\r\nContent-Length: 0\r\n\r\n"


async def test_end_to_end_login_apply_and_relogin():
    login_response.n = 0
    auth_engine = FakeEngine([login_response])
    # first protected hit 401s (stale), forcing a re-login, then 200
    send_engine = FakeEngine([
        b"HTTP/1.1 401 Unauthorized\r\nContent-Length: 0\r\n\r\n",
        protected,
    ])
    provider = JsonLoginProvider("http://h/login", {"u": "a"}, token_path="$.access_token")
    mgr = SessionManager(provider, BearerAuth(),
                         auth_engine=auth_engine, send_engine=send_engine)
    resp = await mgr.send(Request.from_url("http://h/protected"))
    assert resp.status_code == 200
    assert resp.body.raw == b"yes"
    assert len(auth_engine.sent) == 2          # logged in twice (initial + re-login)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/auth/test_profile.py tests/auth/test_integration.py -v`
Expected: FAIL — `profile`/exports missing.

- [ ] **Step 3: Write minimal implementation**

```python
# penpine/auth/profile.py
"""AuthProfile: an identity bundling a provider + scheme into a SessionManager."""
from __future__ import annotations

from dataclasses import dataclass

from penpine.auth.manager import SessionManager
from penpine.auth.provider import AuthProvider
from penpine.auth.scheme import AuthScheme


@dataclass
class AuthProfile:
    name: str
    provider: AuthProvider
    scheme: AuthScheme

    def manager(self, *, auth_engine=None, send_engine=None, **kwargs) -> SessionManager:
        return SessionManager(self.provider, self.scheme,
                              auth_engine=auth_engine, send_engine=send_engine, **kwargs)
```

```python
# penpine/auth/__init__.py
"""Penpine L2 session & auth."""
from penpine.auth.session import Session
from penpine.auth.scheme import (
    AuthScheme, BearerAuth, BasicAuth, CookieAuth, HeaderAuth, MultiScheme,
)
from penpine.auth.provider import AuthProvider, JsonLoginProvider, FormLoginProvider
from penpine.auth.gate import RefreshGate
from penpine.auth.manager import SessionManager
from penpine.auth.scheduler import RefreshScheduler
from penpine.auth.interceptor import AuthInterceptor
from penpine.auth.profile import AuthProfile
from penpine.auth.exceptions import (
    AuthError, LoginError, RefreshError, AuthConfigError,
)

__all__ = [
    "Session", "AuthScheme", "BearerAuth", "BasicAuth", "CookieAuth", "HeaderAuth",
    "MultiScheme", "AuthProvider", "JsonLoginProvider", "FormLoginProvider",
    "RefreshGate", "SessionManager", "RefreshScheduler", "AuthInterceptor",
    "AuthProfile", "AuthError", "LoginError", "RefreshError", "AuthConfigError",
]
```

Then in `penpine/__init__.py`, add these imports after the existing transport imports (before `__all__`):

```python
from penpine.auth.manager import SessionManager
from penpine.auth.profile import AuthProfile
```

And change the `__all__` list in `penpine/__init__.py` to:

```python
__all__ = [
    "Request", "Response", "RequestBuilder", "Headers", "Body",
    "configure_logging", "get_logger",
    "Engine", "Connection",
    "SessionManager", "AuthProfile",
]
```

- [ ] **Step 4: Run the FULL suite**

Run: `python -m pytest -q`
Expected: PASS — all L0+L1+L2 tests green (no failures, no errors).

- [ ] **Step 5: Commit**

```bash
git add penpine/auth/profile.py penpine/auth/__init__.py penpine/__init__.py tests/auth/test_profile.py tests/auth/test_integration.py
git commit -c commit.gpgsign=false -m "feat: add AuthProfile + expose L2 public API + integration"
```

---

## Self-Review Notes (against the spec)

- **§3 module layout** → Tasks 0–10 create every listed module.
- **§4 Session + AuthScheme** (bearer/basic/cookie/header/multi, immutability) → Tasks 2, 3.
- **§5 AuthProvider** (base + JsonLoginProvider + FormLoginProvider; auth-flow engine has no interceptor) → Task 4. (The auth-flow-engine separation is realized in §6's `auth_engine` vs `send_engine` split — Task 6.)
- **§6 RefreshGate + SessionManager** (barrier drain; ensure_fresh/refresh_now/apply/is_auth_failure/invalidate/send retry; auth_engine vs send_engine; sync facade) → Tasks 5, 6, 7.
- **§7 RefreshScheduler** (periodic/expiry, error-tolerant, start/stop) → Task 9.
- **§8 AuthInterceptor** (apply + 401 RetrySignal; no drain) → Task 8.
- **§9 AuthProfile** → Task 10.
- **§10 errors/logging** → Task 1 (errors); logging via `get_logger` in scheduler (Task 9) and is available to manager/provider.
- **§11 testing** (FakeEngine, schemes, providers, gate drain ordering, manager retry/herd, interceptor, scheduler, integration) → every task is test-first; gate ordering Task 5; integration Task 10.

**Deferred (per spec §2 Non-Goals):** data profiles / runtime data (L3), attack framework (L4), persistent session storage, multi-identity orchestration machinery.

**Note for implementers:** `tests/auth/_fakes.py` is imported as `from tests.auth._fakes import FakeEngine` (works because `tests/`, `tests/auth/` are packages with `__init__.py`). Create it in Task 4 before any test that imports it.
```
