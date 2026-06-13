# Penpine L3 — Data & Context Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build L3 of Penpine — a thread-safe runtime `Context` bus, role-bound `DataProfile` fixtures, response `Extract`ors (+ capture helper/interceptor), a custom `{{ }}` template renderer, and an `Identity` bundle that ties auth + data + context per actor.

**Architecture:** Sits on L0 (response model/JSONPath/cookies/`Request` mutators), L1 (`Interceptor`), L2 (`AuthProfile`/`SessionManager`). `Context` is a `threading.Lock`-guarded dict shareable across identities. `Extract` rules pull values from responses; `capture()`/`CaptureInterceptor` write them to a context. `render()` substitutes `{{key}}` placeholders into a request. `Identity` bundles a manager (SessionManager or Engine) + `DataProfile` + `Context`.

**Tech Stack:** Python 3.11+, stdlib `re`/`threading`, `pytest`, `pytest-asyncio` (already configured). Depends on L0–L2 (on `main`).

---

## File Structure

```
penpine/data/
  __init__.py     # public exports
  exceptions.py   # DataError hierarchy
  context.py      # Context + NamespacedView
  profile.py      # DataProfile
  extract.py      # Extract + extract_value + run_extractors
  capture.py      # capture() + CaptureInterceptor
  template.py     # render() + build_mapping()
  identity.py     # Identity
tests/data/
  ... mirrors the above
```

Build order: scaffolding → exceptions → context → profile → extract → capture → template → identity → public API + integration.

---

## Task 0: Scaffolding

**Files:**
- Create: `penpine/data/__init__.py`, `tests/data/__init__.py`

- [ ] **Step 1: Create empty package inits**

Create empty files: `penpine/data/__init__.py`, `tests/data/__init__.py`.

- [ ] **Step 2: Verify suite still green**

Run: `python -m pytest -q`
Expected: `162 passed` (L0+L1+L2 unaffected).

- [ ] **Step 3: Commit**

```bash
git add penpine/data tests/data
git commit -c commit.gpgsign=false -m "chore: scaffold L3 data package"
```

---

## Task 1: Exceptions

**Files:**
- Create: `penpine/data/exceptions.py`
- Test: `tests/data/test_exceptions.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/data/test_exceptions.py
from penpine.exceptions import PenpineError
from penpine.data.exceptions import DataError, ExtractError, TemplateError


def test_hierarchy():
    for cls in (ExtractError, TemplateError):
        assert issubclass(cls, DataError)
    assert issubclass(DataError, PenpineError)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/data/test_exceptions.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Write minimal implementation**

```python
# penpine/data/exceptions.py
"""Data-layer exceptions."""
from __future__ import annotations

from penpine.exceptions import PenpineError


class DataError(PenpineError):
    """Base class for data/context failures."""


class ExtractError(DataError):
    """A required extraction target was absent or its spec was invalid."""


class TemplateError(DataError):
    """An unknown placeholder was encountered during a strict render."""
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/data/test_exceptions.py -v`
Expected: PASS (1 passed).

- [ ] **Step 5: Commit**

```bash
git add penpine/data/exceptions.py tests/data/test_exceptions.py
git commit -c commit.gpgsign=false -m "feat: add data exception hierarchy"
```

---

## Task 2: Context + NamespacedView

**Files:**
- Create: `penpine/data/context.py`
- Test: `tests/data/test_context.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/data/test_context.py
import threading
import pytest

from penpine.data.context import Context
from penpine.data.exceptions import DataError


def test_get_set_has_default():
    c = Context()
    assert c.get("x") is None
    assert c.get("x", "d") == "d"
    c.set("x", 1)
    assert c.get("x") == 1
    assert c.has("x") is True
    assert c.has("y") is False


def test_require_raises_when_missing():
    c = Context({"a": 1})
    assert c.require("a") == 1
    with pytest.raises(DataError):
        c.require("missing")


def test_update_keys_and_to_dict_snapshot():
    c = Context()
    c.update({"a": 1, "b": 2})
    assert set(c.keys()) == {"a", "b"}
    snap = c.to_dict()
    snap["a"] = 99
    assert c.get("a") == 1   # snapshot is a copy


def test_namespace_prefixes_keys():
    c = Context()
    view = c.namespace("userA")
    view.set("order_id", "123")
    assert c.get("userA.order_id") == "123"
    assert view.get("order_id") == "123"
    assert view.has("order_id") is True
    assert view.require("order_id") == "123"


def test_concurrent_writes_are_safe():
    c = Context()

    def writer(start):
        for i in range(start, start + 100):
            c.set(f"k{i}", i)

    threads = [threading.Thread(target=writer, args=(s,)) for s in (0, 100, 200)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(c.keys()) == 300
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/data/test_context.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Write minimal implementation**

```python
# penpine/data/context.py
"""Context: a thread-safe key/value bus shared across identities."""
from __future__ import annotations

import threading

from penpine.data.exceptions import DataError


class Context:
    def __init__(self, initial: dict | None = None):
        self._data = dict(initial or {})
        self._lock = threading.Lock()

    def get(self, key, default=None):
        with self._lock:
            return self._data.get(key, default)

    def set(self, key, value) -> None:
        with self._lock:
            self._data[key] = value

    def has(self, key) -> bool:
        with self._lock:
            return key in self._data

    def require(self, key):
        with self._lock:
            if key not in self._data:
                raise DataError(f"context key not found: {key!r}")
            return self._data[key]

    def update(self, mapping) -> None:
        with self._lock:
            self._data.update(mapping)

    def keys(self) -> list:
        with self._lock:
            return list(self._data.keys())

    def to_dict(self) -> dict:
        with self._lock:
            return dict(self._data)

    def namespace(self, prefix: str) -> "NamespacedView":
        return NamespacedView(self, prefix)


class NamespacedView:
    def __init__(self, context: Context, prefix: str):
        self._ctx = context
        self._prefix = prefix

    def _key(self, key: str) -> str:
        return f"{self._prefix}.{key}"

    def get(self, key, default=None):
        return self._ctx.get(self._key(key), default)

    def set(self, key, value) -> None:
        self._ctx.set(self._key(key), value)

    def has(self, key) -> bool:
        return self._ctx.has(self._key(key))

    def require(self, key):
        return self._ctx.require(self._key(key))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/data/test_context.py -v`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add penpine/data/context.py tests/data/test_context.py
git commit -c commit.gpgsign=false -m "feat: add thread-safe Context bus with namespaced view"
```

---

## Task 3: DataProfile

**Files:**
- Create: `penpine/data/profile.py`
- Test: `tests/data/test_profile.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/data/test_profile.py
import pytest

from penpine.data.profile import DataProfile
from penpine.data.exceptions import DataError


def test_get_with_default():
    p = DataProfile("admin", {"account_id": "A1"})
    assert p.name == "admin"
    assert p.get("account_id") == "A1"
    assert p.get("missing", "d") == "d"


def test_require_raises_when_missing():
    p = DataProfile("admin", {"account_id": "A1"})
    assert p.require("account_id") == "A1"
    with pytest.raises(DataError):
        p.require("missing")


def test_default_values_empty():
    assert DataProfile("guest").values == {}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/data/test_profile.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Write minimal implementation**

```python
# penpine/data/profile.py
"""DataProfile: named static, role-bound fixtures."""
from __future__ import annotations

from dataclasses import dataclass, field

from penpine.data.exceptions import DataError


@dataclass
class DataProfile:
    name: str
    values: dict = field(default_factory=dict)

    def get(self, key, default=None):
        return self.values.get(key, default)

    def require(self, key):
        if key not in self.values:
            raise DataError(f"data profile {self.name!r} missing key: {key!r}")
        return self.values[key]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/data/test_profile.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add penpine/data/profile.py tests/data/test_profile.py
git commit -c commit.gpgsign=false -m "feat: add DataProfile fixtures"
```

---

## Task 4: Extractors

**Files:**
- Create: `penpine/data/extract.py`
- Test: `tests/data/test_extract.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/data/test_extract.py
import pytest

from penpine.core.parse.http_parser import parse_response
from penpine.data.extract import Extract, extract_value, run_extractors
from penpine.data.exceptions import ExtractError


def json_resp():
    return parse_response(
        b'HTTP/1.1 200 OK\r\nContent-Length: 22\r\n\r\n{"user":{"id":"U7"}}\r\n')


def test_extract_json():
    assert extract_value(json_resp(), Extract("id", json="$.user.id")) == "U7"


def test_extract_header():
    resp = parse_response(b"HTTP/1.1 200 OK\r\nX-Token: tk\r\nContent-Length: 0\r\n\r\n")
    assert extract_value(resp, Extract("t", header="X-Token")) == "tk"


def test_extract_cookie():
    resp = parse_response(
        b"HTTP/1.1 200 OK\r\nSet-Cookie: sid=abc; Path=/\r\nContent-Length: 0\r\n\r\n")
    assert extract_value(resp, Extract("s", cookie="sid")) == "abc"


def test_extract_regex_group_and_whole():
    resp = parse_response(b"HTTP/1.1 200 OK\r\nContent-Length: 11\r\n\r\ncsrf=XY9abc")
    assert extract_value(resp, Extract("c", regex=r"csrf=(\w+)")) == "XY9abc"
    assert extract_value(resp, Extract("c", regex=r"csrf=\w+")) == "csrf=XY9abc"


def test_extract_status():
    resp = parse_response(b"HTTP/1.1 201 Created\r\nContent-Length: 0\r\n\r\n")
    assert extract_value(resp, Extract("code", status=True)) == 201


def test_required_miss_raises_and_optional_default():
    resp = parse_response(b"HTTP/1.1 200 OK\r\nContent-Length: 0\r\n\r\n")
    with pytest.raises(ExtractError):
        extract_value(resp, Extract("t", header="Nope"))
    assert extract_value(resp, Extract("t", header="Nope", required=False, default="d")) == "d"


def test_no_source_raises():
    with pytest.raises(ExtractError):
        extract_value(json_resp(), Extract("x"))


def test_run_extractors_returns_dict():
    resp = parse_response(
        b'HTTP/1.1 200 OK\r\nX-Token: tk\r\nContent-Length: 22\r\n\r\n{"user":{"id":"U7"}}\r\n')
    out = run_extractors(resp, [Extract("id", json="$.user.id"), Extract("t", header="X-Token")])
    assert out == {"id": "U7", "t": "tk"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/data/test_extract.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Write minimal implementation**

```python
# penpine/data/extract.py
"""Extractors: pull values out of a Response."""
from __future__ import annotations

import re
from dataclasses import dataclass

from penpine.core.cookies import parse_set_cookie
from penpine.data.exceptions import ExtractError

_MISSING = object()


@dataclass
class Extract:
    key: str
    json: str | None = None
    header: str | None = None
    cookie: str | None = None
    regex: str | None = None
    status: bool = False
    required: bool = True
    default: object = None


def _raw_extract(response, spec: Extract):
    if spec.status:
        return response.status_code
    if spec.json is not None:
        try:
            return response.body.json.get(spec.json)
        except Exception:
            return _MISSING
    if spec.header is not None:
        return response.headers.get(spec.header, _MISSING)
    if spec.cookie is not None:
        for name, value in response.headers.items():
            if name.lower() == "set-cookie":
                parsed = parse_set_cookie(value)
                if parsed.name == spec.cookie:
                    return parsed.value
        return _MISSING
    if spec.regex is not None:
        match = re.search(spec.regex, response.body.text())
        if match is None:
            return _MISSING
        return match.group(1) if match.groups() else match.group(0)
    raise ExtractError(f"Extract({spec.key!r}) has no source set")


def extract_value(response, spec: Extract):
    value = _raw_extract(response, spec)
    if value is _MISSING:
        if spec.required:
            raise ExtractError(f"required value not found for key {spec.key!r}")
        return spec.default
    return value


def run_extractors(response, specs) -> dict:
    return {spec.key: extract_value(response, spec) for spec in specs}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/data/test_extract.py -v`
Expected: PASS (8 passed).

- [ ] **Step 5: Commit**

```bash
git add penpine/data/extract.py tests/data/test_extract.py
git commit -c commit.gpgsign=false -m "feat: add response extractors (json/header/cookie/regex/status)"
```

---

## Task 5: Capture + CaptureInterceptor

**Files:**
- Create: `penpine/data/capture.py`
- Test: `tests/data/test_capture.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/data/test_capture.py
import pytest

from penpine.core.message import Request
from penpine.core.parse.http_parser import parse_response
from penpine.data.context import Context
from penpine.data.capture import capture, CaptureInterceptor
from penpine.data.extract import Extract
from penpine.data.exceptions import ExtractError


def resp_with_token():
    return parse_response(b"HTTP/1.1 200 OK\r\nX-Token: tk\r\nContent-Length: 0\r\n\r\n")


async def test_manual_capture_writes_to_context():
    ctx = Context()
    out = capture(ctx, resp_with_token(), [Extract("t", header="X-Token")])
    assert out == {"t": "tk"}
    assert ctx.get("t") == "tk"


async def test_manual_capture_is_strict():
    ctx = Context()
    with pytest.raises(ExtractError):
        capture(ctx, resp_with_token(), [Extract("missing", header="Nope")])


async def test_interceptor_captures_present_values():
    ctx = Context()
    ic = CaptureInterceptor(ctx, [Extract("t", header="X-Token")])
    out = await ic.after_receive(Request.from_url("http://h/"), resp_with_token())
    assert ctx.get("t") == "tk"
    assert out.status_code == 200


async def test_interceptor_swallows_missing_and_returns_response():
    ctx = Context()
    resp = resp_with_token()
    ic = CaptureInterceptor(ctx, [Extract("missing", header="Nope"),
                                  Extract("t", header="X-Token")])
    out = await ic.after_receive(Request.from_url("http://h/"), resp)
    assert out is resp                 # passthrough, no raise
    assert ctx.has("missing") is False  # missing skipped
    assert ctx.get("t") == "tk"         # present value still captured


async def test_interceptor_before_send_is_passthrough():
    ctx = Context()
    ic = CaptureInterceptor(ctx, [])
    req = Request.from_url("http://h/")
    assert await ic.before_send(req) is req
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/data/test_capture.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Write minimal implementation**

```python
# penpine/data/capture.py
"""Capture: write extracted response values into a Context."""
from __future__ import annotations

from penpine.data.extract import extract_value, run_extractors
from penpine.logging import get_logger
from penpine.transport.interceptor import Interceptor

log = get_logger(__name__)


def capture(context, response, specs) -> dict:
    """Strict: a missing required value raises ExtractError."""
    captured = run_extractors(response, specs)
    context.update(captured)
    return captured


class CaptureInterceptor(Interceptor):
    """Best-effort auto-capture on every response (L1 seam)."""

    def __init__(self, context, specs):
        self._context = context
        self._specs = list(specs)

    async def before_send(self, request):
        return request

    async def after_receive(self, request, response):
        for spec in self._specs:
            try:
                value = extract_value(response, spec)
            except Exception as exc:
                log.warning("auto-capture for key %r failed: %s", spec.key, exc)
                continue
            self._context.set(spec.key, value)
        return response
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/data/test_capture.py -v`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add penpine/data/capture.py tests/data/test_capture.py
git commit -c commit.gpgsign=false -m "feat: add capture helper and best-effort CaptureInterceptor"
```

---

## Task 6: Template renderer

**Files:**
- Create: `penpine/data/template.py`
- Test: `tests/data/test_template.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/data/test_template.py
import pytest

from penpine.core.message import Request
from penpine.core.headers import Headers
from penpine.data.context import Context
from penpine.data.profile import DataProfile
from penpine.data.template import render, build_mapping
from penpine.data.exceptions import TemplateError


def test_render_substitutes_target_header_body():
    req = Request(method="POST", target="/orders/{{order_id}}",
                  headers=Headers([("Host", "h"), ("X-Trace", "{{trace}}")]),
                  body=b"id={{order_id}}")
    out = render(req, {"order_id": "123", "trace": "abc"})
    assert out.target == "/orders/123"
    assert out.headers["X-Trace"] == "abc"
    assert out.body.raw == b"id=123"
    assert out.headers["Content-Length"] == "6"   # recomputed from new body


def test_render_strict_unknown_raises():
    req = Request(method="GET", target="/{{missing}}", headers=Headers([("Host", "h")]))
    with pytest.raises(TemplateError):
        render(req, {})


def test_render_non_strict_leaves_unknown():
    req = Request(method="GET", target="/{{missing}}", headers=Headers([("Host", "h")]))
    out = render(req, {}, strict=False)
    assert out.target == "/{{missing}}"


def test_render_dotted_key_is_literal():
    req = Request(method="GET", target="/{{userA.order_id}}", headers=Headers([("Host", "h")]))
    out = render(req, {"userA.order_id": "9"})
    assert out.target == "/9"


def test_build_mapping_precedence_data_lt_context_lt_extra():
    data = DataProfile("p", {"k": "data", "only_data": "d"})
    ctx = Context({"k": "ctx", "only_ctx": "c"})
    mapping = build_mapping(context=ctx, data=data, extra={"k": "extra"})
    assert mapping["k"] == "extra"
    assert mapping["only_data"] == "d"
    assert mapping["only_ctx"] == "c"


def test_build_mapping_accepts_plain_dicts():
    mapping = build_mapping(context={"a": 1}, data={"b": 2})
    assert mapping == {"a": 1, "b": 2}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/data/test_template.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Write minimal implementation**

```python
# penpine/data/template.py
"""Custom {{ }} template renderer over a Request, and mapping builder."""
from __future__ import annotations

import re

from penpine.core.headers import Headers
from penpine.data.context import Context
from penpine.data.exceptions import TemplateError
from penpine.data.profile import DataProfile

_PLACEHOLDER = re.compile(r"\{\{\s*([^}\s]+)\s*\}\}")


def build_mapping(context=None, data=None, extra=None) -> dict:
    """Merge sources with precedence data < context < extra."""
    mapping: dict = {}
    if data is not None:
        mapping.update(data.values if isinstance(data, DataProfile) else dict(data))
    if context is not None:
        mapping.update(context.to_dict() if isinstance(context, Context) else dict(context))
    if extra is not None:
        mapping.update(dict(extra))
    return mapping


def render(request, mapping, *, strict=True):
    def _replace(text: str) -> str:
        def _sub(match):
            key = match.group(1)
            if key in mapping:
                return str(mapping[key])
            if strict:
                raise TemplateError(f"unknown placeholder: {{{{{key}}}}}")
            return match.group(0)
        return _PLACEHOLDER.sub(_sub, text)

    new = request.with_target(_replace(request.target))
    new = new.with_headers(
        Headers([(name, _replace(value)) for name, value in new.headers.items()]))
    if request.body.raw:
        new = new.with_body(_replace(request.body.text()).encode())
    return new
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/data/test_template.py -v`
Expected: PASS (6 passed).

- [ ] **Step 5: Commit**

```bash
git add penpine/data/template.py tests/data/test_template.py
git commit -c commit.gpgsign=false -m "feat: add {{ }} template renderer and mapping builder"
```

---

## Task 7: Identity

**Files:**
- Create: `penpine/data/identity.py`
- Test: `tests/data/test_identity.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/data/test_identity.py
import pytest

from penpine.core.message import Request
from penpine.core.headers import Headers
from penpine.data.identity import Identity
from penpine.data.context import Context
from penpine.data.profile import DataProfile
from penpine.data.extract import Extract
from penpine.data.exceptions import DataError
from tests.auth._fakes import FakeEngine


def ok():
    return b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nok"


async def test_send_delegates_to_manager():
    engine = FakeEngine([ok()])
    ident = Identity("A", manager=engine)
    resp = await ident.send(Request.from_url("http://h/r"))
    assert resp.status_code == 200
    assert len(engine.sent) == 1


async def test_send_without_manager_raises():
    ident = Identity("A")
    with pytest.raises(DataError):
        await ident.send(Request.from_url("http://h/r"))


def test_render_merges_data_and_ctx_with_ctx_override():
    data = DataProfile("A", {"k": "from_data", "fixture": "F"})
    ctx = Context({"k": "from_ctx"})
    ident = Identity("A", data=data, context=ctx)
    req = Request(method="GET", target="/{{k}}/{{fixture}}", headers=Headers([("Host", "h")]))
    out = ident.render(req)
    assert out.target == "/from_ctx/F"     # ctx overrides data; data fixture still available


def test_capture_writes_to_identity_context():
    from penpine.core.parse.http_parser import parse_response
    ctx = Context()
    ident = Identity("A", context=ctx)
    resp = parse_response(b"HTTP/1.1 200 OK\r\nX-Token: tk\r\nContent-Length: 0\r\n\r\n")
    ident.capture(resp, [Extract("t", header="X-Token")])
    assert ctx.get("t") == "tk"


def test_defaults_create_empty_data_and_context():
    ident = Identity("A")
    assert isinstance(ident.data, DataProfile)
    assert isinstance(ident.ctx, Context)
    assert ident.manager is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/data/test_identity.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Write minimal implementation**

```python
# penpine/data/identity.py
"""Identity: an actor bundling auth/manager + data + context."""
from __future__ import annotations

from penpine.data.capture import capture
from penpine.data.context import Context
from penpine.data.exceptions import DataError
from penpine.data.profile import DataProfile
from penpine.data.template import build_mapping, render


class Identity:
    def __init__(self, name, *, auth_profile=None, manager=None, data=None,
                 context=None, **manager_kw):
        self.name = name
        self.auth_profile = auth_profile
        if manager is not None:
            self._manager = manager
        elif auth_profile is not None:
            self._manager = auth_profile.manager(**manager_kw)
        else:
            self._manager = None
        self.data = data if data is not None else DataProfile(name)
        self.ctx = context if context is not None else Context()

    @property
    def manager(self):
        return self._manager

    async def send(self, request, **kwargs):
        if self._manager is None:
            raise DataError(f"identity {self.name!r} has no manager to send with")
        return await self._manager.send(request, **kwargs)

    def send_sync(self, request, **kwargs):
        if self._manager is None:
            raise DataError(f"identity {self.name!r} has no manager to send with")
        return self._manager.send_sync(request, **kwargs)

    def render(self, request, *, strict=True):
        mapping = build_mapping(context=self.ctx, data=self.data)
        return render(request, mapping, strict=strict)

    def capture(self, response, specs):
        return capture(self.ctx, response, specs)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/data/test_identity.py -v`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add penpine/data/identity.py tests/data/test_identity.py
git commit -c commit.gpgsign=false -m "feat: add Identity bundle (manager + data + context)"
```

---

## Task 8: Public API + cross-identity integration

**Files:**
- Modify: `penpine/data/__init__.py`, `penpine/__init__.py`
- Test: `tests/data/test_public_api.py`, `tests/data/test_integration.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/data/test_public_api.py
import penpine
from penpine.data import (
    Context, NamespacedView, DataProfile, Extract, capture, CaptureInterceptor,
    render, build_mapping, Identity, DataError, ExtractError, TemplateError,
)


def test_data_exports_exist():
    assert all([Context, NamespacedView, DataProfile, Extract, capture,
                CaptureInterceptor, render, build_mapping, Identity,
                DataError, ExtractError, TemplateError])


def test_top_level_reexports():
    assert penpine.Identity is Identity
    assert penpine.Context is Context
```

```python
# tests/data/test_integration.py
from penpine.core.message import Request
from penpine.data.identity import Identity
from penpine.data.context import Context
from penpine.data.extract import Extract
from tests.auth._fakes import FakeEngine


def create_order_resp(request):
    body = b'{"id":"ORD-123"}'
    return (b"HTTP/1.1 201 Created\r\nContent-Length: " + str(len(body)).encode()
            + b"\r\n\r\n" + body)


def use_order_resp(request):
    return b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nok"


async def test_user_a_creates_user_b_uses_via_shared_context():
    ctx = Context()
    alice = Identity("alice", manager=FakeEngine([create_order_resp]), context=ctx)
    bob = Identity("bob", manager=FakeEngine([use_order_resp]), context=ctx)

    # alice creates an order, capturing the id into the shared context
    resp = await alice.send(Request.from_url("http://h/orders"))
    alice.capture(resp, [Extract("order_id", json="$.id")])
    assert ctx.get("order_id") == "ORD-123"

    # bob renders a request that references the captured id, then sends it
    raw = (b"POST /use HTTP/1.1\r\nHost: h\r\nContent-Length: 15\r\n\r\n"
           b"id={{order_id}}")
    rendered = bob.render(Request.from_raw(raw))
    assert rendered.body.raw == b"id=ORD-123"
    assert rendered.headers["Content-Length"] == "10"

    bob_resp = await bob.send(rendered)
    assert bob_resp.status_code == 200
    assert bob.manager.sent[0].body.raw == b"id=ORD-123"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/data/test_public_api.py tests/data/test_integration.py -v`
Expected: FAIL — exports / behavior missing.

- [ ] **Step 3: Write minimal implementation**

```python
# penpine/data/__init__.py
"""Penpine L3 data & context."""
from penpine.data.context import Context, NamespacedView
from penpine.data.profile import DataProfile
from penpine.data.extract import Extract, extract_value, run_extractors
from penpine.data.capture import capture, CaptureInterceptor
from penpine.data.template import render, build_mapping
from penpine.data.identity import Identity
from penpine.data.exceptions import DataError, ExtractError, TemplateError

__all__ = [
    "Context", "NamespacedView", "DataProfile", "Extract", "extract_value",
    "run_extractors", "capture", "CaptureInterceptor", "render", "build_mapping",
    "Identity", "DataError", "ExtractError", "TemplateError",
]
```

Then in `penpine/__init__.py`, add these imports after the existing auth imports (before `__all__`):

```python
from penpine.data.context import Context
from penpine.data.identity import Identity
```

And change the `__all__` list in `penpine/__init__.py` to:

```python
__all__ = [
    "Request", "Response", "RequestBuilder", "Headers", "Body",
    "configure_logging", "get_logger",
    "Engine", "Connection",
    "SessionManager", "AuthProfile",
    "Context", "Identity",
]
```

- [ ] **Step 4: Run the FULL suite**

Run: `python -m pytest -q`
Expected: PASS — all L0–L3 tests green (no failures, no errors).

- [ ] **Step 5: Commit**

```bash
git add penpine/data/__init__.py penpine/__init__.py tests/data/test_public_api.py tests/data/test_integration.py
git commit -c commit.gpgsign=false -m "feat: expose L3 public API + cross-identity integration"
```

---

## Self-Review Notes (against the spec)

- **§3 module layout** → Tasks 0–8 create every listed module.
- **§4 errors** → Task 1.
- **§5 Context + NamespacedView** (get/set/has/require/update/keys/to_dict snapshot/namespace + thread-safety) → Task 2.
- **§6 DataProfile** → Task 3.
- **§7 Extractors** (json/header/cookie/regex/status, required/default, no-source error) → Task 4.
- **§8 capture + CaptureInterceptor** (manual strict, interceptor best-effort, passthrough) → Task 5.
- **§9 render + build_mapping** (target/header/body, CL recompute, strict miss, dotted keys, precedence data<context<extra, plain dicts) → Task 6.
- **§10 Identity** (manager = supplied/auth_profile/none; send delegate; no-manager raises; render merge; capture) → Task 7.
- **§12 testing** → test-first throughout; the headline cross-identity flow is Task 8's integration test.

**Deferred (per spec §2 Non-Goals):** hierarchical/scoped contexts, persistence, the attack framework (L4).

**Notes for implementers:** `tests/data/test_identity.py` and `tests/data/test_integration.py` import `from tests.auth._fakes import FakeEngine` (reusing L2's test helper — `tests/`, `tests/auth/` are packages). `build_mapping` distinguishes a `DataProfile`/`Context` from a plain dict via `isinstance` (a plain dict's `.values` is a method, not the data), so don't "simplify" that to attribute access.
```
