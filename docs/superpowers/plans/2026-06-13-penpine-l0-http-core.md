# Penpine L0 — HTTP Message Core Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build L0 of Penpine — a byte-faithful, immutable HTTP/1.1 message model with parsing, serialization, parsed body views, and a locator DSL, with zero network code.

**Architecture:** Pure in-memory model. `Request`/`Response` are immutable; mutators return copies. `Headers` preserve order/casing/duplicates. `Body` keeps raw bytes plus lazy parsed views. A locator DSL addresses any sub-part of a request (the seam L4 will consume). Parser is lenient by default. Only third-party dependency is `jsonpath-ng`, isolated to the locator/json view.

**Tech Stack:** Python 3.11+, `jsonpath-ng` (runtime), `pytest` (dev). Stdlib `logging`, `json`, `urllib.parse` (used only as a pure string codec, no network).

---

## File Structure

```
pyproject.toml
penpine/
  __init__.py
  logging.py
  exceptions.py
  core/
    __init__.py
    headers.py          # Headers
    url.py              # parse_target, build_target, query multidict
    cookies.py          # parse_cookie_header, parse_set_cookie
    body/
      __init__.py
      base.py           # Body (raw + lazy views)
      json_body.py      # JsonBody
      form_body.py      # FormBody
      multipart_body.py # MultipartBody
    meta.py             # ConnectionMeta
    message.py          # HttpMessage, Request, Response
    parse/
      __init__.py
      framing.py        # body length / chunked decode
      http_parser.py    # parse_request, parse_response
    serialize.py        # serialize_request
    locator.py          # Locator DSL
    loaders.py          # from_raw/from_file/from_url
    builder.py          # RequestBuilder
tests/
  ... mirrors penpine/
```

Build order is bottom-up: leaf utilities first (logging, exceptions, headers, url, body views), then the model, then parse/serialize, then mutators/locator, then loaders/builder.

---

## Task 0: Project scaffolding

**Files:**
- Create: `pyproject.toml`, `penpine/__init__.py`, `penpine/core/__init__.py`, `penpine/core/body/__init__.py`, `penpine/core/parse/__init__.py`, `tests/__init__.py`

- [ ] **Step 1: Create `pyproject.toml`**

```toml
[project]
name = "penpine"
version = "0.0.1"
description = "A layered Python pentesting framework — L0 HTTP message core"
requires-python = ">=3.11"
dependencies = ["jsonpath-ng>=1.6"]

[project.optional-dependencies]
dev = ["pytest>=8.0"]

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.pytest.ini_options]
testpaths = ["tests"]
```

- [ ] **Step 2: Create empty package init files**

Create these as empty files: `penpine/__init__.py`, `penpine/core/__init__.py`, `penpine/core/body/__init__.py`, `penpine/core/parse/__init__.py`, `tests/__init__.py`.

- [ ] **Step 3: Install dev deps**

Run: `python -m pip install -e ".[dev]"`
Expected: installs `penpine`, `jsonpath-ng`, `pytest` successfully.

- [ ] **Step 4: Verify pytest runs (no tests yet)**

Run: `python -m pytest -q`
Expected: `no tests ran` (exit 5) or similar — confirms pytest is wired.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml penpine tests
git commit -c commit.gpgsign=false -m "chore: scaffold penpine L0 package"
```

---

## Task 1: Logging

**Files:**
- Create: `penpine/logging.py`
- Test: `tests/test_logging.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_logging.py
import logging
from penpine.logging import get_logger, configure_logging


def test_get_logger_returns_namespaced_logger():
    log = get_logger("penpine.core.foo")
    assert isinstance(log, logging.Logger)
    assert log.name == "penpine.core.foo"


def test_no_import_side_effects_on_root():
    root = logging.getLogger()
    before = len(root.handlers)
    get_logger("penpine.x")
    assert len(root.handlers) == before


def test_configure_logging_sets_level_and_handler():
    log = configure_logging(level=logging.DEBUG)
    assert log.level == logging.DEBUG
    assert any(h for h in log.handlers)
    # idempotent: calling twice does not stack handlers
    n = len(log.handlers)
    configure_logging(level=logging.INFO)
    assert len(log.handlers) == n
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_logging.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'penpine.logging'` content (module missing).

- [ ] **Step 3: Write minimal implementation**

```python
# penpine/logging.py
"""Shared logging for penpine. No side effects at import time."""
from __future__ import annotations

import logging

_ROOT_NAME = "penpine"

_LEVEL_COLORS = {
    logging.DEBUG: "\033[36m",
    logging.INFO: "\033[32m",
    logging.WARNING: "\033[33m",
    logging.ERROR: "\033[31m",
    logging.CRITICAL: "\033[1;31m",
}
_RESET = "\033[0m"


class _ColorFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        color = _LEVEL_COLORS.get(record.levelno, "")
        base = super().format(record)
        return f"{color}{base}{_RESET}" if color else base


def get_logger(name: str) -> logging.Logger:
    """Return a namespaced logger. Does not attach handlers."""
    return logging.getLogger(name)


def configure_logging(level: int = logging.INFO) -> logging.Logger:
    """Attach a single colored console handler to the penpine root logger."""
    log = logging.getLogger(_ROOT_NAME)
    log.setLevel(level)
    log.propagate = False
    if not log.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(_ColorFormatter("%(levelname)s %(name)s: %(message)s"))
        log.addHandler(handler)
    return log
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_logging.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add penpine/logging.py tests/test_logging.py
git commit -c commit.gpgsign=false -m "feat: add shared logging helpers"
```

---

## Task 2: Exception hierarchy

**Files:**
- Create: `penpine/exceptions.py`
- Test: `tests/test_exceptions.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_exceptions.py
from penpine.exceptions import (
    PenpineError, ParseError, MalformedRequestError,
    BodyParseError, LocatorError, BuildError,
)


def test_hierarchy():
    assert issubclass(ParseError, PenpineError)
    assert issubclass(MalformedRequestError, ParseError)
    assert issubclass(BodyParseError, ParseError)
    assert issubclass(LocatorError, PenpineError)
    assert issubclass(BuildError, PenpineError)


def test_parse_error_carries_offset():
    err = ParseError("bad", offset=12, snippet="GET / HT")
    assert err.offset == 12
    assert err.snippet == "GET / HT"
    assert "offset=12" in str(err)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_exceptions.py -v`
Expected: FAIL — module/classes missing.

- [ ] **Step 3: Write minimal implementation**

```python
# penpine/exceptions.py
"""Exception hierarchy for penpine."""
from __future__ import annotations


class PenpineError(Exception):
    """Base class for all penpine errors."""


class ParseError(PenpineError):
    """Failure while parsing an HTTP message."""

    def __init__(self, message: str, *, offset: int | None = None, snippet: str | None = None):
        self.offset = offset
        self.snippet = snippet
        if offset is not None:
            message = f"{message} (offset={offset})"
        super().__init__(message)


class MalformedRequestError(ParseError):
    """Request violates HTTP/1.1 framing in strict mode."""


class BodyParseError(ParseError):
    """A typed body view could not be parsed."""


class LocatorError(PenpineError):
    """A locator expression is invalid or its target is absent."""


class BuildError(PenpineError):
    """Invalid RequestBuilder usage."""
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_exceptions.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add penpine/exceptions.py tests/test_exceptions.py
git commit -c commit.gpgsign=false -m "feat: add exception hierarchy"
```

---

## Task 3: Headers

**Files:**
- Create: `penpine/core/headers.py`
- Test: `tests/core/test_headers.py` (create `tests/core/__init__.py` too)

- [ ] **Step 1: Write the failing test**

```python
# tests/core/test_headers.py
from penpine.core.headers import Headers


def test_preserves_order_casing_duplicates():
    h = Headers([("Host", "a"), ("X-Foo", "1"), ("x-foo", "2")])
    assert list(h.items()) == [("Host", "a"), ("X-Foo", "1"), ("x-foo", "2")]


def test_case_insensitive_lookup():
    h = Headers([("Content-Type", "application/json")])
    assert h["content-type"] == "application/json"
    assert h.get("CONTENT-TYPE") == "application/json"
    assert h.get("missing", "d") == "d"
    assert "CONTENT-type" in h


def test_get_all_returns_every_match():
    h = Headers([("Set-Cookie", "a=1"), ("set-cookie", "b=2")])
    assert h.get_all("set-cookie") == ["a=1", "b=2"]


def test_mutators_return_new_instance_and_keep_original():
    h = Headers([("A", "1")])
    h2 = h.add("A", "2")
    assert list(h.items()) == [("A", "1")]
    assert list(h2.items()) == [("A", "1"), ("A", "2")]
    h3 = h2.set("a", "9")
    assert list(h3.items()) == [("a", "9")]
    h4 = h3.remove("A")
    assert list(h4.items()) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/core/test_headers.py -v`
Expected: FAIL — module missing. (Create empty `tests/core/__init__.py` first.)

- [ ] **Step 3: Write minimal implementation**

```python
# penpine/core/headers.py
"""Ordered, case-preserving, multi-valued HTTP headers (immutable)."""
from __future__ import annotations

from typing import Iterable, Iterator


class Headers:
    __slots__ = ("_items",)

    def __init__(self, items: Iterable[tuple[str, str]] | None = None):
        self._items: tuple[tuple[str, str], ...] = tuple(items or ())

    def items(self) -> Iterator[tuple[str, str]]:
        return iter(self._items)

    def names(self) -> list[str]:
        return [n for n, _ in self._items]

    def get(self, name: str, default=None):
        low = name.lower()
        for n, v in self._items:
            if n.lower() == low:
                return v
        return default

    def get_all(self, name: str) -> list[str]:
        low = name.lower()
        return [v for n, v in self._items if n.lower() == low]

    def __getitem__(self, name: str) -> str:
        v = self.get(name, _MISSING)
        if v is _MISSING:
            raise KeyError(name)
        return v

    def __contains__(self, name: str) -> bool:
        return self.get(name, _MISSING) is not _MISSING

    def __iter__(self) -> Iterator[tuple[str, str]]:
        return iter(self._items)

    def __len__(self) -> int:
        return len(self._items)

    def __eq__(self, other) -> bool:
        return isinstance(other, Headers) and self._items == other._items

    def add(self, name: str, value: str) -> "Headers":
        return Headers([*self._items, (name, value)])

    def set(self, name: str, value: str) -> "Headers":
        low = name.lower()
        kept = [(n, v) for n, v in self._items if n.lower() != low]
        return Headers([*kept, (name, value)])

    def remove(self, name: str) -> "Headers":
        low = name.lower()
        return Headers([(n, v) for n, v in self._items if n.lower() != low])

    def __repr__(self) -> str:
        return f"Headers({list(self._items)!r})"


_MISSING = object()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/core/test_headers.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add penpine/core/headers.py tests/core/__init__.py tests/core/test_headers.py
git commit -c commit.gpgsign=false -m "feat: add immutable Headers"
```

---

## Task 4: URL / target parsing

**Files:**
- Create: `penpine/core/url.py`
- Test: `tests/core/test_url.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/core/test_url.py
from penpine.core.url import parse_url, parse_query, build_query, set_query_param


def test_parse_url_components():
    u = parse_url("https://example.com:8443/a/b?x=1&y=2")
    assert u.scheme == "https"
    assert u.host == "example.com"
    assert u.port == 8443
    assert u.path == "/a/b"
    assert u.query == "x=1&y=2"


def test_default_ports():
    assert parse_url("http://h/").port == 80
    assert parse_url("https://h/").port == 443


def test_parse_query_preserves_order_and_dupes():
    assert parse_query("a=1&b=2&a=3") == [("a", "1"), ("b", "2"), ("a", "3")]


def test_set_query_param_replaces_first_keeps_rest():
    target = "/p?a=1&b=2"
    assert set_query_param(target, "a", "9") == "/p?a=9&b=2"


def test_set_query_param_adds_when_absent():
    assert set_query_param("/p", "a", "1") == "/p?a=1"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/core/test_url.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Write minimal implementation**

```python
# penpine/core/url.py
"""URL/target parsing helpers. Pure string operations, no network."""
from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import quote, unquote

_DEFAULT_PORTS = {"http": 80, "https": 443}


@dataclass(frozen=True)
class ParsedUrl:
    scheme: str
    host: str
    port: int
    path: str
    query: str


def parse_url(url: str) -> ParsedUrl:
    scheme, _, rest = url.partition("://")
    scheme = scheme.lower()
    authority, slash, tail = rest.partition("/")
    path_and_query = (slash + tail) if slash else "/"
    host, _, port_s = authority.partition(":")
    port = int(port_s) if port_s else _DEFAULT_PORTS.get(scheme, 80)
    path, _, query = path_and_query.partition("?")
    return ParsedUrl(scheme, host, port, path or "/", query)


def parse_query(query: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    if not query:
        return out
    for pair in query.split("&"):
        if not pair:
            continue
        k, sep, v = pair.partition("=")
        out.append((unquote(k), unquote(v) if sep else ""))
    return out


def build_query(pairs: list[tuple[str, str]]) -> str:
    return "&".join(f"{quote(k, safe='')}={quote(v, safe='')}" for k, v in pairs)


def split_target(target: str) -> tuple[str, str]:
    """Split an origin-form target into (path, query)."""
    path, _, query = target.partition("?")
    return path, query


def set_query_param(target: str, name: str, value: str) -> str:
    path, query = split_target(target)
    pairs = parse_query(query)
    replaced = False
    new_pairs: list[tuple[str, str]] = []
    for k, v in pairs:
        if k == name and not replaced:
            new_pairs.append((k, value))
            replaced = True
        else:
            new_pairs.append((k, v))
    if not replaced:
        new_pairs.append((name, value))
    q = build_query(new_pairs)
    return f"{path}?{q}" if q else path
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/core/test_url.py -v`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add penpine/core/url.py tests/core/test_url.py
git commit -c commit.gpgsign=false -m "feat: add url/target parsing helpers"
```

---

## Task 5: Body base + raw

**Files:**
- Create: `penpine/core/body/base.py`
- Test: `tests/core/body/test_base.py` (create `tests/core/body/__init__.py`)

- [ ] **Step 1: Write the failing test**

```python
# tests/core/body/test_base.py
from penpine.core.body.base import Body


def test_raw_preserved_and_text():
    b = Body(b"hello", content_type="text/plain")
    assert b.raw == b"hello"
    assert b.text() == "hello"
    assert len(b) == 5


def test_empty_body():
    b = Body(b"")
    assert b.raw == b""
    assert b.text() == ""


def test_equality_on_raw():
    assert Body(b"x") == Body(b"x")
    assert Body(b"x") != Body(b"y")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/core/body/test_base.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Write minimal implementation**

```python
# penpine/core/body/base.py
"""Body: raw bytes plus lazy typed views."""
from __future__ import annotations

from functools import cached_property


class Body:
    def __init__(self, raw: bytes = b"", content_type: str | None = None):
        if isinstance(raw, str):
            raw = raw.encode("utf-8")
        self._raw = raw
        self.content_type = content_type

    @property
    def raw(self) -> bytes:
        return self._raw

    def text(self, encoding: str = "utf-8") -> str:
        return self._raw.decode(encoding, errors="replace")

    def __len__(self) -> int:
        return len(self._raw)

    def __eq__(self, other) -> bool:
        return isinstance(other, Body) and self._raw == other._raw

    def __repr__(self) -> str:
        return f"Body({self._raw[:32]!r}{'...' if len(self._raw) > 32 else ''})"

    @cached_property
    def json(self):
        from penpine.core.body.json_body import JsonBody
        return JsonBody.from_bytes(self._raw)

    @cached_property
    def form(self):
        from penpine.core.body.form_body import FormBody
        return FormBody.from_bytes(self._raw)

    @cached_property
    def multipart(self):
        from penpine.core.body.multipart_body import MultipartBody
        return MultipartBody.from_bytes(self._raw, self.content_type)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/core/body/test_base.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add penpine/core/body/base.py tests/core/body/__init__.py tests/core/body/test_base.py
git commit -c commit.gpgsign=false -m "feat: add Body base with raw + lazy view hooks"
```

---

## Task 6: JSON body view

**Files:**
- Create: `penpine/core/body/json_body.py`
- Test: `tests/core/body/test_json_body.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/core/body/test_json_body.py
import pytest
from penpine.core.body.json_body import JsonBody
from penpine.exceptions import BodyParseError


def test_parse_and_get():
    jb = JsonBody.from_bytes(b'{"user": {"id": 5, "name": "ann"}}')
    assert jb.get("$.user.id") == 5
    assert jb.get("$.user.name") == "ann"


def test_set_returns_new_and_reserializes():
    jb = JsonBody.from_bytes(b'{"a": 1}')
    jb2 = jb.set("$.a", 2)
    assert jb.get("$.a") == 1          # original unchanged
    assert jb2.get("$.a") == 2
    assert b'"a": 2' in jb2.to_bytes() or b'"a":2' in jb2.to_bytes()


def test_invalid_json_raises():
    with pytest.raises(BodyParseError):
        JsonBody.from_bytes(b"{not json")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/core/body/test_json_body.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Write minimal implementation**

```python
# penpine/core/body/json_body.py
"""JSON body view with JSONPath get/set (jsonpath-ng isolated here)."""
from __future__ import annotations

import copy
import json

from jsonpath_ng.ext import parse as jsonpath_parse

from penpine.exceptions import BodyParseError


class JsonBody:
    def __init__(self, data):
        self._data = data

    @classmethod
    def from_bytes(cls, raw: bytes) -> "JsonBody":
        try:
            return cls(json.loads(raw.decode("utf-8")))
        except (ValueError, UnicodeDecodeError) as exc:
            raise BodyParseError(f"invalid JSON body: {exc}") from exc

    @property
    def data(self):
        return self._data

    def get(self, path: str):
        matches = jsonpath_parse(path).find(self._data)
        if not matches:
            raise BodyParseError(f"JSON path not found: {path}")
        return matches[0].value

    def set(self, path: str, value) -> "JsonBody":
        new_data = copy.deepcopy(self._data)
        expr = jsonpath_parse(path)
        if not expr.find(new_data):
            raise BodyParseError(f"JSON path not found: {path}")
        expr.update(new_data, value)
        return JsonBody(new_data)

    def to_bytes(self) -> bytes:
        return json.dumps(self._data).encode("utf-8")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/core/body/test_json_body.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add penpine/core/body/json_body.py tests/core/body/test_json_body.py
git commit -c commit.gpgsign=false -m "feat: add JSON body view with JSONPath get/set"
```

---

## Task 7: Form body view

**Files:**
- Create: `penpine/core/body/form_body.py`
- Test: `tests/core/body/test_form_body.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/core/body/test_form_body.py
from penpine.core.body.form_body import FormBody


def test_parse_preserves_order_and_dupes():
    fb = FormBody.from_bytes(b"a=1&b=2&a=3")
    assert fb.fields == [("a", "1"), ("b", "2"), ("a", "3")]


def test_get_returns_first():
    fb = FormBody.from_bytes(b"a=1&a=3")
    assert fb.get("a") == "1"


def test_set_returns_new_and_reserializes():
    fb = FormBody.from_bytes(b"a=1&b=2")
    fb2 = fb.set("a", "9")
    assert fb.get("a") == "1"
    assert fb2.get("a") == "9"
    assert fb2.to_bytes() == b"a=9&b=2"


def test_url_decoding():
    fb = FormBody.from_bytes(b"q=hello%20world")
    assert fb.get("q") == "hello world"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/core/body/test_form_body.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Write minimal implementation**

```python
# penpine/core/body/form_body.py
"""application/x-www-form-urlencoded body view."""
from __future__ import annotations

from penpine.core.url import build_query, parse_query


class FormBody:
    def __init__(self, fields: list[tuple[str, str]]):
        self._fields = list(fields)

    @classmethod
    def from_bytes(cls, raw: bytes) -> "FormBody":
        return cls(parse_query(raw.decode("utf-8", errors="replace")))

    @property
    def fields(self) -> list[tuple[str, str]]:
        return list(self._fields)

    def get(self, name: str, default=None):
        for k, v in self._fields:
            if k == name:
                return v
        return default

    def set(self, name: str, value: str) -> "FormBody":
        replaced = False
        out: list[tuple[str, str]] = []
        for k, v in self._fields:
            if k == name and not replaced:
                out.append((k, value))
                replaced = True
            else:
                out.append((k, v))
        if not replaced:
            out.append((name, value))
        return FormBody(out)

    def to_bytes(self) -> bytes:
        return build_query(self._fields).encode("utf-8")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/core/body/test_form_body.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add penpine/core/body/form_body.py tests/core/body/test_form_body.py
git commit -c commit.gpgsign=false -m "feat: add urlencoded form body view"
```

---

## Task 8: Multipart body view

**Files:**
- Create: `penpine/core/body/multipart_body.py`
- Test: `tests/core/body/test_multipart_body.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/core/body/test_multipart_body.py
from penpine.core.body.multipart_body import MultipartBody

CT = 'multipart/form-data; boundary=----b'
RAW = (
    b"------b\r\n"
    b'Content-Disposition: form-data; name="a"\r\n\r\n'
    b"1\r\n"
    b"------b\r\n"
    b'Content-Disposition: form-data; name="file"; filename="f.txt"\r\n'
    b"Content-Type: text/plain\r\n\r\n"
    b"DATA\r\n"
    b"------b--\r\n"
)


def test_parse_parts():
    mb = MultipartBody.from_bytes(RAW, CT)
    assert mb.get("a") == b"1"
    assert mb.get("file") == b"DATA"
    assert mb.names() == ["a", "file"]


def test_set_and_reserialize_roundtrips_names():
    mb = MultipartBody.from_bytes(RAW, CT)
    mb2 = mb.set("a", b"9")
    assert mb.get("a") == b"1"
    assert mb2.get("a") == b"9"
    reparsed = MultipartBody.from_bytes(mb2.to_bytes(), CT)
    assert reparsed.get("a") == b"9"
    assert reparsed.get("file") == b"DATA"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/core/body/test_multipart_body.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Write minimal implementation**

```python
# penpine/core/body/multipart_body.py
"""multipart/form-data body view (raw-preserving per-part content)."""
from __future__ import annotations

import re
from dataclasses import dataclass

from penpine.exceptions import BodyParseError

_NAME_RE = re.compile(rb'name="([^"]*)"')


@dataclass(frozen=True)
class Part:
    name: str
    headers: bytes        # raw header block for the part (without trailing CRLFCRLF)
    content: bytes


class MultipartBody:
    def __init__(self, boundary: str, parts: list[Part]):
        self._boundary = boundary
        self._parts = parts

    @staticmethod
    def _boundary_from_ct(content_type: str | None) -> str:
        if not content_type or "boundary=" not in content_type:
            raise BodyParseError("multipart content-type without boundary")
        return content_type.split("boundary=", 1)[1].strip().strip('"')

    @classmethod
    def from_bytes(cls, raw: bytes, content_type: str | None) -> "MultipartBody":
        boundary = cls._boundary_from_ct(content_type)
        delim = b"--" + boundary.encode()
        parts: list[Part] = []
        for chunk in raw.split(delim):
            chunk = chunk.strip(b"\r\n")
            if not chunk or chunk == b"--":
                continue
            head, _, content = chunk.partition(b"\r\n\r\n")
            m = _NAME_RE.search(head)
            name = m.group(1).decode() if m else ""
            parts.append(Part(name=name, headers=head, content=content))
        return cls(boundary, parts)

    def names(self) -> list[str]:
        return [p.name for p in self._parts]

    def get(self, name: str, default=None):
        for p in self._parts:
            if p.name == name:
                return p.content
        return default

    def set(self, name: str, content: bytes) -> "MultipartBody":
        out = [
            Part(p.name, p.headers, content) if p.name == name else p
            for p in self._parts
        ]
        return MultipartBody(self._boundary, out)

    def to_bytes(self) -> bytes:
        delim = b"--" + self._boundary.encode()
        out = b""
        for p in self._parts:
            out += delim + b"\r\n" + p.headers + b"\r\n\r\n" + p.content + b"\r\n"
        out += delim + b"--\r\n"
        return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/core/body/test_multipart_body.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add penpine/core/body/multipart_body.py tests/core/body/test_multipart_body.py
git commit -c commit.gpgsign=false -m "feat: add multipart/form-data body view"
```

---

## Task 9: Cookies

**Files:**
- Create: `penpine/core/cookies.py`
- Test: `tests/core/test_cookies.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/core/test_cookies.py
from penpine.core.cookies import parse_cookie_header, parse_set_cookie


def test_parse_request_cookie_header():
    assert parse_cookie_header("a=1; b=2; a=3") == [("a", "1"), ("b", "2"), ("a", "3")]


def test_parse_set_cookie():
    c = parse_set_cookie("sid=abc; Path=/; HttpOnly; Max-Age=60")
    assert c.name == "sid"
    assert c.value == "abc"
    assert c.attributes["path"] == "/"
    assert c.attributes["max-age"] == "60"
    assert c.flags == {"httponly"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/core/test_cookies.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Write minimal implementation**

```python
# penpine/core/cookies.py
"""Read-only cookie parsing (the stateful jar lives in L2)."""
from __future__ import annotations

from dataclasses import dataclass, field


def parse_cookie_header(value: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for part in value.split(";"):
        part = part.strip()
        if not part:
            continue
        k, _, v = part.partition("=")
        out.append((k.strip(), v.strip()))
    return out


@dataclass
class SetCookie:
    name: str
    value: str
    attributes: dict[str, str] = field(default_factory=dict)
    flags: set[str] = field(default_factory=set)


def parse_set_cookie(value: str) -> SetCookie:
    segments = [s.strip() for s in value.split(";") if s.strip()]
    name, _, val = segments[0].partition("=")
    cookie = SetCookie(name=name.strip(), value=val.strip())
    for seg in segments[1:]:
        if "=" in seg:
            k, _, v = seg.partition("=")
            cookie.attributes[k.strip().lower()] = v.strip()
        else:
            cookie.flags.add(seg.lower())
    return cookie
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/core/test_cookies.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add penpine/core/cookies.py tests/core/test_cookies.py
git commit -c commit.gpgsign=false -m "feat: add read-only cookie parsing"
```

---

## Task 10: ConnectionMeta + Request/Response model

**Files:**
- Create: `penpine/core/meta.py`, `penpine/core/message.py`
- Test: `tests/core/test_message.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/core/test_message.py
from penpine.core.meta import ConnectionMeta
from penpine.core.message import Request, Response
from penpine.core.headers import Headers
from penpine.core.body.base import Body


def test_request_construct_defaults():
    r = Request(method="GET", target="/", version="HTTP/1.1")
    assert isinstance(r.headers, Headers)
    assert isinstance(r.body, Body)
    assert r.meta == ConnectionMeta()


def test_request_is_immutable():
    r = Request(method="GET", target="/", version="HTTP/1.1")
    try:
        r.method = "POST"
        assert False, "should be frozen"
    except AttributeError:
        pass


def test_clone_produces_equal_independent_copy():
    r = Request(method="GET", target="/", version="HTTP/1.1",
                headers=Headers([("A", "1")]))
    c = r.clone()
    assert c.method == r.method and list(c.headers.items()) == list(r.headers.items())
    assert c is not r


def test_response_fields():
    resp = Response(status_code=200, reason="OK", version="HTTP/1.1")
    assert resp.status_code == 200
    assert resp.reason == "OK"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/core/test_message.py -v`
Expected: FAIL — modules missing.

- [ ] **Step 3: Write minimal implementation**

```python
# penpine/core/meta.py
"""Connection metadata populated by loaders/builder, consumed by L1."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ConnectionMeta:
    scheme: str | None = None
    host: str | None = None
    port: int | None = None
```

```python
# penpine/core/message.py
"""Immutable HTTP message model."""
from __future__ import annotations

from dataclasses import dataclass, field, replace

from penpine.core.body.base import Body
from penpine.core.headers import Headers
from penpine.core.meta import ConnectionMeta


def _coerce_body(body) -> Body:
    if isinstance(body, Body):
        return body
    if body is None:
        return Body(b"")
    return Body(body)


@dataclass(frozen=True)
class Request:
    method: str
    target: str
    version: str = "HTTP/1.1"
    headers: Headers = field(default_factory=Headers)
    body: Body = field(default_factory=lambda: Body(b""))
    meta: ConnectionMeta = field(default_factory=ConnectionMeta)
    preserve_content_length: bool = False
    parse_warnings: tuple[str, ...] = ()
    raw: bytes | None = None

    def __post_init__(self):
        object.__setattr__(self, "body", _coerce_body(self.body))

    def clone(self, **changes) -> "Request":
        return replace(self, **changes)


@dataclass(frozen=True)
class Response:
    status_code: int
    reason: str = ""
    version: str = "HTTP/1.1"
    headers: Headers = field(default_factory=Headers)
    body: Body = field(default_factory=lambda: Body(b""))
    parse_warnings: tuple[str, ...] = ()
    raw: bytes | None = None

    def __post_init__(self):
        object.__setattr__(self, "body", _coerce_body(self.body))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/core/test_message.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add penpine/core/meta.py penpine/core/message.py tests/core/test_message.py
git commit -c commit.gpgsign=false -m "feat: add immutable Request/Response model"
```

---

## Task 11: Framing (Content-Length / chunked)

**Files:**
- Create: `penpine/core/parse/framing.py`
- Test: `tests/core/parse/test_framing.py` (create `tests/core/parse/__init__.py`)

- [ ] **Step 1: Write the failing test**

```python
# tests/core/parse/test_framing.py
import pytest
from penpine.core.headers import Headers
from penpine.core.parse.framing import body_length, decode_chunked
from penpine.exceptions import ParseError


def test_content_length():
    h = Headers([("Content-Length", "5")])
    assert body_length(h) == ("length", 5)


def test_chunked():
    h = Headers([("Transfer-Encoding", "chunked")])
    assert body_length(h) == ("chunked", None)


def test_no_body():
    assert body_length(Headers()) == ("none", 0)


def test_decode_chunked():
    raw = b"4\r\nWiki\r\n5\r\npedia\r\n0\r\n\r\n"
    decoded, consumed = decode_chunked(raw)
    assert decoded == b"Wikipedia"
    assert consumed == len(raw)


def test_decode_chunked_incomplete_raises():
    with pytest.raises(ParseError):
        decode_chunked(b"4\r\nWi")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/core/parse/test_framing.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Write minimal implementation**

```python
# penpine/core/parse/framing.py
"""HTTP/1.1 body framing: Content-Length and chunked decoding."""
from __future__ import annotations

from penpine.core.headers import Headers
from penpine.exceptions import ParseError


def body_length(headers: Headers) -> tuple[str, int | None]:
    te = headers.get("Transfer-Encoding")
    if te and "chunked" in te.lower():
        return ("chunked", None)
    cl = headers.get("Content-Length")
    if cl is not None:
        try:
            return ("length", int(cl.strip()))
        except ValueError as exc:
            raise ParseError(f"invalid Content-Length: {cl!r}") from exc
    return ("none", 0)


def decode_chunked(data: bytes) -> tuple[bytes, int]:
    """Return (decoded_body, bytes_consumed)."""
    out = bytearray()
    pos = 0
    while True:
        nl = data.find(b"\r\n", pos)
        if nl == -1:
            raise ParseError("incomplete chunk size line", offset=pos)
        size_line = data[pos:nl].split(b";", 1)[0].strip()
        try:
            size = int(size_line, 16)
        except ValueError as exc:
            raise ParseError(f"invalid chunk size {size_line!r}", offset=pos) from exc
        pos = nl + 2
        if size == 0:
            end = data.find(b"\r\n", pos)
            if end == -1:
                raise ParseError("missing final CRLF after last chunk", offset=pos)
            return bytes(out), end + 2
        if pos + size + 2 > len(data):
            raise ParseError("incomplete chunk data", offset=pos)
        out += data[pos:pos + size]
        pos += size + 2
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/core/parse/test_framing.py -v`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add penpine/core/parse/framing.py tests/core/parse/__init__.py tests/core/parse/test_framing.py
git commit -c commit.gpgsign=false -m "feat: add body framing (content-length + chunked)"
```

---

## Task 12: HTTP parser (request + response)

**Files:**
- Create: `penpine/core/parse/http_parser.py`
- Test: `tests/core/parse/test_http_parser.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/core/parse/test_http_parser.py
import pytest
from penpine.core.parse.http_parser import parse_request, parse_response
from penpine.exceptions import MalformedRequestError


def test_parse_simple_get():
    raw = b"GET /a?x=1 HTTP/1.1\r\nHost: h\r\n\r\n"
    req = parse_request(raw)
    assert req.method == "GET"
    assert req.target == "/a?x=1"
    assert req.version == "HTTP/1.1"
    assert req.headers["Host"] == "h"
    assert req.body.raw == b""
    assert req.raw == raw


def test_parse_post_with_length():
    raw = b"POST / HTTP/1.1\r\nContent-Length: 4\r\n\r\nbody"
    req = parse_request(raw)
    assert req.body.raw == b"body"


def test_preserves_duplicate_and_mixed_case_headers():
    raw = b"GET / HTTP/1.1\r\nX-A: 1\r\nx-a: 2\r\n\r\n"
    req = parse_request(raw)
    assert req.headers.get_all("x-a") == ["1", "2"]


def test_lenient_lf_only_line_endings_warns():
    raw = b"GET / HTTP/1.1\nHost: h\n\n"
    req = parse_request(raw)
    assert req.headers["Host"] == "h"
    assert any("LF" in w or "line ending" in w for w in req.parse_warnings)


def test_strict_rejects_lf_only():
    raw = b"GET / HTTP/1.1\nHost: h\n\n"
    with pytest.raises(MalformedRequestError):
        parse_request(raw, strict=True)


def test_parse_response():
    raw = b"HTTP/1.1 404 Not Found\r\nContent-Length: 2\r\n\r\nno"
    resp = parse_response(raw)
    assert resp.status_code == 404
    assert resp.reason == "Not Found"
    assert resp.body.raw == b"no"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/core/parse/test_http_parser.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Write minimal implementation**

```python
# penpine/core/parse/http_parser.py
"""Parse raw bytes into Request/Response. Lenient by default."""
from __future__ import annotations

from penpine.core.body.base import Body
from penpine.core.headers import Headers
from penpine.core.message import Request, Response
from penpine.core.parse.framing import body_length, decode_chunked
from penpine.exceptions import MalformedRequestError


def _split_head_body(data: bytes, strict: bool) -> tuple[bytes, bytes, list[str]]:
    warnings: list[str] = []
    idx = data.find(b"\r\n\r\n")
    crlf = True
    if idx == -1:
        idx = data.find(b"\n\n")
        crlf = False
        if idx == -1:
            raise MalformedRequestError("no header/body separator found")
    if not crlf:
        if strict:
            raise MalformedRequestError("LF-only line endings")
        warnings.append("LF-only line endings normalized")
    head = data[:idx]
    body = data[idx + (4 if crlf else 2):]
    if not crlf:
        head = head.replace(b"\n", b"\r\n")
    return head, body, warnings


def _parse_headers(head_lines: list[bytes], strict: bool, warnings: list[str]) -> Headers:
    items: list[tuple[str, str]] = []
    for line in head_lines:
        text = line.decode("latin-1")
        if ":" not in text:
            if strict:
                raise MalformedRequestError(f"header without colon: {text!r}")
            warnings.append(f"malformed header line preserved: {text!r}")
            items.append((text, ""))
            continue
        name, _, value = text.partition(":")
        items.append((name, value.strip()))
    return Headers(items)


def _content_type(headers: Headers) -> str | None:
    return headers.get("Content-Type")


def _extract_body(headers: Headers, body: bytes) -> bytes:
    kind, length = body_length(headers)
    if kind == "length":
        return body[:length]
    if kind == "chunked":
        decoded, _ = decode_chunked(body)
        return decoded
    return body if body else b""


def parse_request(data: bytes, *, strict: bool = False) -> Request:
    head, body, warnings = _split_head_body(data, strict)
    lines = head.split(b"\r\n")
    start = lines[0].decode("latin-1")
    parts = start.split(" ")
    if len(parts) != 3:
        raise MalformedRequestError(f"invalid request line: {start!r}")
    method, target, version = parts
    headers = _parse_headers(lines[1:], strict, warnings)
    body_bytes = _extract_body(headers, body)
    return Request(
        method=method, target=target, version=version,
        headers=headers, body=Body(body_bytes, _content_type(headers)),
        parse_warnings=tuple(warnings), raw=data,
    )


def parse_response(data: bytes, *, strict: bool = False) -> Response:
    head, body, warnings = _split_head_body(data, strict)
    lines = head.split(b"\r\n")
    start = lines[0].decode("latin-1")
    version, _, rest = start.partition(" ")
    code_s, _, reason = rest.partition(" ")
    try:
        code = int(code_s)
    except ValueError as exc:
        raise MalformedRequestError(f"invalid status line: {start!r}") from exc
    headers = _parse_headers(lines[1:], strict, warnings)
    body_bytes = _extract_body(headers, body)
    return Response(
        status_code=code, reason=reason, version=version,
        headers=headers, body=Body(body_bytes, _content_type(headers)),
        parse_warnings=tuple(warnings), raw=data,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/core/parse/test_http_parser.py -v`
Expected: PASS (6 passed).

- [ ] **Step 5: Commit**

```bash
git add penpine/core/parse/http_parser.py tests/core/parse/test_http_parser.py
git commit -c commit.gpgsign=false -m "feat: add HTTP request/response parser"
```

---

## Task 13: Serialization + round-trip invariant

**Files:**
- Create: `penpine/core/serialize.py`
- Modify: `penpine/core/message.py` (add `.serialize()` / `.to_bytes()` to `Request`)
- Test: `tests/core/test_serialize.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/core/test_serialize.py
import pytest
from penpine.core.parse.http_parser import parse_request
from penpine.core.serialize import serialize_request

CORPUS = [
    b"GET /a?x=1 HTTP/1.1\r\nHost: h\r\n\r\n",
    b"POST / HTTP/1.1\r\nContent-Length: 4\r\nHost: h\r\n\r\nbody",
    b"GET / HTTP/1.1\r\nX-A: 1\r\nx-a: 2\r\nHOST: H\r\n\r\n",
]


@pytest.mark.parametrize("raw", CORPUS)
def test_roundtrip_byte_exact(raw):
    req = parse_request(raw)
    assert serialize_request(req) == raw


def test_request_serialize_method():
    raw = b"GET / HTTP/1.1\r\nHost: h\r\n\r\n"
    assert parse_request(raw).serialize() == raw
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/core/test_serialize.py -v`
Expected: FAIL — module/method missing.

- [ ] **Step 3: Write minimal implementation**

```python
# penpine/core/serialize.py
"""Serialize a Request back to raw bytes."""
from __future__ import annotations

from penpine.core.message import Request


def serialize_request(req: Request) -> bytes:
    start = f"{req.method} {req.target} {req.version}".encode("latin-1")
    lines = [start]
    for name, value in req.headers.items():
        lines.append(f"{name}: {value}".encode("latin-1"))
    head = b"\r\n".join(lines)
    return head + b"\r\n\r\n" + req.body.raw
```

Then add to `penpine/core/message.py` inside `class Request`:

```python
    def serialize(self) -> bytes:
        from penpine.core.serialize import serialize_request
        return serialize_request(self)

    def to_bytes(self) -> bytes:
        return self.serialize()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/core/test_serialize.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add penpine/core/serialize.py penpine/core/message.py tests/core/test_serialize.py
git commit -c commit.gpgsign=false -m "feat: add request serialization with round-trip invariant"
```

---

## Task 14: Request mutators + Content-Length policy

**Files:**
- Modify: `penpine/core/message.py` (add mutators to `Request`)
- Test: `tests/core/test_mutators.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/core/test_mutators.py
from penpine.core.message import Request
from penpine.core.headers import Headers
from penpine.core.body.base import Body


def base():
    return Request(method="POST", target="/p?a=1", version="HTTP/1.1",
                   headers=Headers([("Host", "h"), ("Content-Length", "0")]),
                   body=Body(b""))


def test_with_header_returns_copy():
    r = base()
    r2 = r.set_header("X-Test", "v")
    assert "X-Test" not in r.headers
    assert r2.headers["X-Test"] == "v"


def test_set_param_rebuilds_target():
    r = base().set_param("a", "9")
    assert r.target == "/p?a=9"


def test_with_body_recomputes_content_length():
    r = base().with_body(b"hello")
    assert r.body.raw == b"hello"
    assert r.headers["Content-Length"] == "5"


def test_preserve_content_length_keeps_mismatch():
    r = Request(method="POST", target="/", headers=Headers([("Content-Length", "100")]),
                body=Body(b""), preserve_content_length=True)
    r2 = r.with_body(b"hi")
    assert r2.headers["Content-Length"] == "100"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/core/test_mutators.py -v`
Expected: FAIL — methods missing.

- [ ] **Step 3: Write minimal implementation**

Add to `class Request` in `penpine/core/message.py` (and ensure `from penpine.core.url import set_query_param` and `from penpine.core.body.base import Body` are imported at module top):

```python
    def with_method(self, method: str) -> "Request":
        return self.clone(method=method, raw=None)

    def with_target(self, target: str) -> "Request":
        return self.clone(target=target, raw=None)

    def with_version(self, version: str) -> "Request":
        return self.clone(version=version, raw=None)

    def with_headers(self, headers: Headers) -> "Request":
        return self.clone(headers=headers, raw=None)

    def set_header(self, name: str, value: str) -> "Request":
        return self.clone(headers=self.headers.set(name, value), raw=None)

    def add_header(self, name: str, value: str) -> "Request":
        return self.clone(headers=self.headers.add(name, value), raw=None)

    def remove_header(self, name: str) -> "Request":
        return self.clone(headers=self.headers.remove(name), raw=None)

    def with_body(self, body) -> "Request":
        new_body = body if isinstance(body, Body) else Body(body, self.body.content_type)
        headers = self.headers
        if not self.preserve_content_length and "Transfer-Encoding" not in headers:
            headers = headers.set("Content-Length", str(len(new_body.raw)))
        return self.clone(body=new_body, headers=headers, raw=None)

    def set_param(self, name: str, value: str) -> "Request":
        return self.with_target(set_query_param(self.target, name, value))

    def set_form_field(self, name: str, value: str) -> "Request":
        return self.with_body(self.body.form.set(name, value).to_bytes())

    def set_json(self, path: str, value) -> "Request":
        return self.with_body(self.body.json.set(path, value).to_bytes())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/core/test_mutators.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add penpine/core/message.py tests/core/test_mutators.py
git commit -c commit.gpgsign=false -m "feat: add Request mutators with content-length policy"
```

---

## Task 15: Locator DSL

**Files:**
- Create: `penpine/core/locator.py`
- Modify: `penpine/core/message.py` (add `locate`, `replace_at`)
- Test: `tests/core/test_locator.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/core/test_locator.py
import pytest
from penpine.core.message import Request
from penpine.core.headers import Headers
from penpine.core.body.base import Body
from penpine.exceptions import LocatorError


def req_with_json():
    return Request(method="POST", target="/p?a=1&b=2", version="HTTP/1.1",
                   headers=Headers([("Host", "h"), ("Cookie", "sid=xyz"),
                                    ("Content-Type", "application/json")]),
                   body=Body(b'{"user":{"id":7}}', "application/json"))


def test_locate_param():
    r = req_with_json()
    loc = r.locate("param:a")
    assert loc.value == "1"
    assert r.replace_at("param:a", "99").target == "/p?a=99&b=2"


def test_locate_header_and_cookie():
    r = req_with_json()
    assert r.locate("header:Host").value == "h"
    assert r.locate("cookie:sid").value == "xyz"


def test_locate_json():
    r = req_with_json()
    assert r.locate("json:$.user.id").value == 7
    r2 = r.replace_at("json:$.user.id", 8)
    assert r2.body.json.get("$.user.id") == 8


def test_locate_request_line_parts():
    r = req_with_json()
    assert r.locate("method").value == "POST"
    assert r.replace_at("method", "PUT").method == "PUT"


def test_missing_target_raises():
    with pytest.raises(LocatorError):
        req_with_json().locate("param:nope")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/core/test_locator.py -v`
Expected: FAIL — module/methods missing.

- [ ] **Step 3: Write minimal implementation**

```python
# penpine/core/locator.py
"""Locator DSL: address and replace sub-parts of a Request."""
from __future__ import annotations

from dataclasses import dataclass

from penpine.core.cookies import parse_cookie_header
from penpine.core.url import parse_query, split_target
from penpine.exceptions import LocatorError


@dataclass(frozen=True)
class ResolvedLocator:
    request: "object"
    kind: str
    name: str
    value: object
    exists: bool = True

    def replace(self, new_value):
        return _replace(self.request, self.kind, self.name, new_value)


def parse_expr(expr: str) -> tuple[str, str]:
    if expr in ("method", "target", "version"):
        return expr, ""
    kind, sep, name = expr.partition(":")
    if not sep:
        raise LocatorError(f"invalid locator expression: {expr!r}")
    return kind, name


def locate(request, expr: str) -> ResolvedLocator:
    kind, name = parse_expr(expr)
    value = _read(request, kind, name)
    return ResolvedLocator(request=request, kind=kind, name=name, value=value)


def _read(request, kind: str, name: str):
    if kind in ("method", "target", "version"):
        return getattr(request, kind)
    if kind == "param":
        _, query = split_target(request.target)
        for k, v in parse_query(query):
            if k == name:
                return v
        raise LocatorError(f"query param not found: {name}")
    if kind == "header":
        if name not in request.headers:
            raise LocatorError(f"header not found: {name}")
        return request.headers[name]
    if kind == "cookie":
        for k, v in parse_cookie_header(request.headers.get("Cookie", "")):
            if k == name:
                return v
        raise LocatorError(f"cookie not found: {name}")
    if kind == "json":
        return request.body.json.get(name)
    if kind == "form":
        v = request.body.form.get(name, _MISSING)
        if v is _MISSING:
            raise LocatorError(f"form field not found: {name}")
        return v
    if kind == "multipart":
        v = request.body.multipart.get(name)
        if v is None:
            raise LocatorError(f"multipart field not found: {name}")
        return v
    if kind == "path-seg":
        path, _ = split_target(request.target)
        segs = [s for s in path.split("/") if s]
        try:
            return segs[int(name)]
        except (ValueError, IndexError) as exc:
            raise LocatorError(f"path segment not found: {name}") from exc
    raise LocatorError(f"unknown locator kind: {kind}")


def _replace(request, kind: str, name: str, value):
    if kind == "method":
        return request.with_method(value)
    if kind == "target":
        return request.with_target(value)
    if kind == "version":
        return request.with_version(value)
    if kind == "param":
        return request.set_param(name, value)
    if kind == "header":
        return request.set_header(name, value)
    if kind == "cookie":
        pairs = parse_cookie_header(request.headers.get("Cookie", ""))
        new = "; ".join(f"{k}={value if k == name else v}" for k, v in pairs)
        return request.set_header("Cookie", new)
    if kind == "json":
        return request.set_json(name, value)
    if kind == "form":
        return request.set_form_field(name, value)
    if kind == "multipart":
        data = value if isinstance(value, bytes) else str(value).encode()
        return request.with_body(request.body.multipart.set(name, data).to_bytes())
    if kind == "path-seg":
        path, query = split_target(request.target)
        segs = path.split("/")
        non_empty = [i for i, s in enumerate(segs) if s]
        segs[non_empty[int(name)]] = value
        new_path = "/".join(segs)
        return request.with_target(f"{new_path}?{query}" if query else new_path)
    raise LocatorError(f"cannot replace kind: {kind}")


_MISSING = object()
```

Then add to `class Request` in `penpine/core/message.py`:

```python
    def locate(self, expr: str):
        from penpine.core.locator import locate
        return locate(self, expr)

    def replace_at(self, expr_or_locator, value) -> "Request":
        if hasattr(expr_or_locator, "replace"):
            return expr_or_locator.replace(value)
        return self.locate(expr_or_locator).replace(value)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/core/test_locator.py -v`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add penpine/core/locator.py penpine/core/message.py tests/core/test_locator.py
git commit -c commit.gpgsign=false -m "feat: add locator DSL with resolve/replace"
```

---

## Task 16: Injection candidate enumeration

**Files:**
- Modify: `penpine/core/locator.py` (add `enumerate_candidates`)
- Modify: `penpine/core/message.py` (add `injection_candidates`)
- Test: `tests/core/test_candidates.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/core/test_candidates.py
from penpine.core.message import Request
from penpine.core.headers import Headers
from penpine.core.body.base import Body


def test_enumerates_params_headers_cookies_json():
    r = Request(method="POST", target="/api/v1/x?a=1&b=2", version="HTTP/1.1",
                headers=Headers([("Host", "h"), ("Cookie", "sid=xyz"),
                                 ("Content-Type", "application/json")]),
                body=Body(b'{"name":"ann"}', "application/json"))
    exprs = {f"{c.kind}:{c.name}" if c.name else c.kind
             for c in r.injection_candidates()}
    assert "param:a" in exprs
    assert "param:b" in exprs
    assert "header:Host" in exprs
    assert "cookie:sid" in exprs
    assert "json:$.name" in exprs


def test_kinds_filter():
    r = Request(method="GET", target="/?a=1", version="HTTP/1.1",
                headers=Headers([("Host", "h")]))
    only = r.injection_candidates(kinds={"param"})
    assert {c.kind for c in only} == {"param"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/core/test_candidates.py -v`
Expected: FAIL — methods missing.

- [ ] **Step 3: Write minimal implementation**

Add to `penpine/core/locator.py`:

```python
def _json_leaf_paths(data, prefix="$"):
    paths = []
    if isinstance(data, dict):
        for k, v in data.items():
            paths += _json_leaf_paths(v, f"{prefix}.{k}")
    elif isinstance(data, list):
        for i, v in enumerate(data):
            paths += _json_leaf_paths(v, f"{prefix}[{i}]")
    else:
        paths.append(prefix)
    return paths


def enumerate_candidates(request, kinds=None) -> list[ResolvedLocator]:
    out: list[ResolvedLocator] = []

    def emit(kind, name, value):
        if kinds is None or kind in kinds:
            out.append(ResolvedLocator(request, kind, name, value))

    _, query = split_target(request.target)
    for k, v in parse_query(query):
        emit("param", k, v)
    for name, value in request.headers.items():
        if name.lower() == "cookie":
            for ck, cv in parse_cookie_header(value):
                emit("cookie", ck, cv)
        else:
            emit("header", name, value)
    ctype = request.headers.get("Content-Type", "")
    if "application/json" in ctype and request.body.raw:
        try:
            for path in _json_leaf_paths(request.body.json.data):
                emit("json", path, request.body.json.get(path))
        except Exception:
            pass
    elif "application/x-www-form-urlencoded" in ctype:
        for k, v in request.body.form.fields:
            emit("form", k, v)
    return out
```

Add to `class Request` in `penpine/core/message.py`:

```python
    def injection_candidates(self, kinds=None):
        from penpine.core.locator import enumerate_candidates
        return enumerate_candidates(self, kinds)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/core/test_candidates.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add penpine/core/locator.py penpine/core/message.py tests/core/test_candidates.py
git commit -c commit.gpgsign=false -m "feat: add injection candidate enumeration"
```

---

## Task 17: Loaders

**Files:**
- Create: `penpine/core/loaders.py`
- Modify: `penpine/core/message.py` (add `from_raw`, `from_file`, `from_url` classmethods to `Request`)
- Test: `tests/core/test_loaders.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/core/test_loaders.py
from penpine.core.message import Request


def test_from_raw_string():
    r = Request.from_raw("GET / HTTP/1.1\r\nHost: h\r\n\r\n")
    assert r.method == "GET"
    assert r.headers["Host"] == "h"


def test_from_raw_sets_meta_when_provided():
    r = Request.from_raw(b"GET / HTTP/1.1\r\nHost: h\r\n\r\n",
                         scheme="https", host="h", port=443)
    assert r.meta.scheme == "https"
    assert r.meta.host == "h"
    assert r.meta.port == 443


def test_from_file(tmp_path):
    p = tmp_path / "req.txt"
    p.write_bytes(b"GET /x HTTP/1.1\r\nHost: h\r\n\r\n")
    r = Request.from_file(str(p))
    assert r.target == "/x"


def test_from_url_builds_request_and_meta():
    r = Request.from_url("https://example.com:8443/a?x=1", method="GET")
    assert r.method == "GET"
    assert r.target == "/a?x=1"
    assert r.headers["Host"] == "example.com:8443"
    assert r.meta.scheme == "https"
    assert r.meta.port == 8443
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/core/test_loaders.py -v`
Expected: FAIL — methods missing.

- [ ] **Step 3: Write minimal implementation**

```python
# penpine/core/loaders.py
"""Construct Request objects from raw bytes, files, or URLs."""
from __future__ import annotations

from penpine.core.body.base import Body
from penpine.core.headers import Headers
from penpine.core.meta import ConnectionMeta
from penpine.core.parse.http_parser import parse_request
from penpine.core.url import parse_url


def from_raw(data, *, strict=False, scheme=None, host=None, port=None):
    if isinstance(data, str):
        data = data.encode("utf-8")
    req = parse_request(data, strict=strict)
    if scheme or host or port:
        req = req.clone(meta=ConnectionMeta(scheme=scheme, host=host, port=port))
    return req


def from_file(path, *, strict=False, scheme=None, host=None, port=None):
    with open(path, "rb") as fh:
        return from_raw(fh.read(), strict=strict, scheme=scheme, host=host, port=port)


def from_url(url, *, method="GET", headers=None, body=None, version="HTTP/1.1"):
    from penpine.core.message import Request
    u = parse_url(url)
    host_header = u.host if u.port in (80, 443) else f"{u.host}:{u.port}"
    items = [("Host", host_header)]
    if headers:
        items += list(headers)
    target = u.path + (f"?{u.query}" if u.query else "")
    return Request(
        method=method, target=target, version=version,
        headers=Headers(items), body=Body(body or b""),
        meta=ConnectionMeta(scheme=u.scheme, host=u.host, port=u.port),
    )
```

Add to `class Request` in `penpine/core/message.py`:

```python
    @classmethod
    def from_raw(cls, data, **kw) -> "Request":
        from penpine.core.loaders import from_raw
        return from_raw(data, **kw)

    @classmethod
    def from_file(cls, path, **kw) -> "Request":
        from penpine.core.loaders import from_file
        return from_file(path, **kw)

    @classmethod
    def from_url(cls, url, **kw) -> "Request":
        from penpine.core.loaders import from_url
        return from_url(url, **kw)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/core/test_loaders.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add penpine/core/loaders.py penpine/core/message.py tests/core/test_loaders.py
git commit -c commit.gpgsign=false -m "feat: add request loaders (raw/file/url)"
```

---

## Task 18: RequestBuilder

**Files:**
- Create: `penpine/core/builder.py`
- Test: `tests/core/test_builder.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/core/test_builder.py
import json
import pytest
from penpine.core.builder import RequestBuilder
from penpine.exceptions import BuildError


def test_build_json_request_sets_headers_and_length():
    r = (RequestBuilder()
         .method("POST")
         .url("https://h/api")
         .json({"a": 1})
         .build())
    assert r.method == "POST"
    assert r.headers["Content-Type"] == "application/json"
    assert r.headers["Content-Length"] == str(len(r.body.raw))
    assert json.loads(r.body.raw) == {"a": 1}
    assert r.meta.host == "h"


def test_build_requires_url():
    with pytest.raises(BuildError):
        RequestBuilder().method("GET").build()


def test_form_builder():
    r = RequestBuilder().method("POST").url("http://h/x").form({"a": "1"}).build()
    assert r.headers["Content-Type"] == "application/x-www-form-urlencoded"
    assert r.body.raw == b"a=1"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/core/test_builder.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Write minimal implementation**

```python
# penpine/core/builder.py
"""Fluent RequestBuilder."""
from __future__ import annotations

import json as _json

from penpine.core.body.form_body import FormBody
from penpine.core.message import Request
from penpine.exceptions import BuildError


class RequestBuilder:
    def __init__(self):
        self._method = "GET"
        self._url = None
        self._version = "HTTP/1.1"
        self._headers: list[tuple[str, str]] = []
        self._body = b""
        self._content_type = None

    def method(self, m: str) -> "RequestBuilder":
        self._method = m
        return self

    def url(self, u: str) -> "RequestBuilder":
        self._url = u
        return self

    def version(self, v: str) -> "RequestBuilder":
        self._version = v
        return self

    def header(self, name: str, value: str) -> "RequestBuilder":
        self._headers.append((name, value))
        return self

    def body(self, data: bytes, content_type: str | None = None) -> "RequestBuilder":
        self._body = data if isinstance(data, bytes) else str(data).encode()
        self._content_type = content_type
        return self

    def json(self, obj) -> "RequestBuilder":
        self._body = _json.dumps(obj).encode("utf-8")
        self._content_type = "application/json"
        return self

    def form(self, fields: dict) -> "RequestBuilder":
        self._body = FormBody(list(fields.items())).to_bytes()
        self._content_type = "application/x-www-form-urlencoded"
        return self

    def build(self) -> Request:
        if not self._url:
            raise BuildError("RequestBuilder requires a url()")
        req = Request.from_url(self._url, method=self._method, version=self._version)
        for name, value in self._headers:
            req = req.add_header(name, value)
        if self._content_type:
            req = req.set_header("Content-Type", self._content_type)
        req = req.with_body(self._body)
        return req
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/core/test_builder.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add penpine/core/builder.py tests/core/test_builder.py
git commit -c commit.gpgsign=false -m "feat: add fluent RequestBuilder"
```

---

## Task 19: Public API surface + full suite green

**Files:**
- Modify: `penpine/__init__.py`, `penpine/core/__init__.py`
- Test: `tests/test_public_api.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_public_api.py
import penpine


def test_top_level_exports():
    assert hasattr(penpine, "Request")
    assert hasattr(penpine, "Response")
    assert hasattr(penpine, "RequestBuilder")
    assert hasattr(penpine, "configure_logging")
    r = penpine.Request.from_url("http://h/a")
    assert r.method == "GET"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_public_api.py -v`
Expected: FAIL — attributes missing.

- [ ] **Step 3: Write minimal implementation**

```python
# penpine/__init__.py
"""Penpine — layered Python pentesting framework (L0 HTTP core)."""
from penpine.core.message import Request, Response
from penpine.core.builder import RequestBuilder
from penpine.core.headers import Headers
from penpine.core.body.base import Body
from penpine.logging import configure_logging, get_logger

__all__ = [
    "Request", "Response", "RequestBuilder", "Headers", "Body",
    "configure_logging", "get_logger",
]
```

- [ ] **Step 4: Run the FULL suite**

Run: `python -m pytest -q`
Expected: PASS — all tasks' tests green (no failures, no errors).

- [ ] **Step 5: Commit**

```bash
git add penpine/__init__.py penpine/core/__init__.py tests/test_public_api.py
git commit -c commit.gpgsign=false -m "feat: expose public L0 API surface"
```

---

## Self-Review Notes (against the spec)

- **§3 Package layout** → Tasks 0–19 create every listed module.
- **§4 Data model** (Request/Response/Headers/Body/meta) → Tasks 3, 5, 10; immutability + clone in Task 10; mutators + Content-Length policy in Task 14.
- **§4.4 Headers fidelity** (order/casing/duplicates) → Task 3 + parser Task 12 + serialize round-trip Task 13.
- **§4.5 Body lazy views** (json/form/multipart/text) → Tasks 5–8.
- **§4.6 url/cookies** → Tasks 4, 9.
- **§5 Locator DSL + injection_candidates** → Tasks 15, 16. (Note: `raw:<start>-<end>` and duplicate-header `header:<name>[<i>]` addressing from the spec grammar are intentionally deferred — they aren't needed by any current consumer and add parser surface; track as a follow-up if L4 needs them.)
- **§6 Parsing/serialization** (lenient default, strict opt-in, chunked, round-trip invariant) → Tasks 11, 12, 13.
- **§7 Loaders/builder** → Tasks 17, 18.
- **§8 Errors/logging** → Tasks 1, 2 (used throughout).
- **§10 Testing strategy** → every task is test-first; round-trip corpus in Task 13.
- **§11 Dependencies** → `jsonpath-ng` isolated to json_body/locator (Tasks 6, 15); `pytest` dev only (Task 0).

**Deferred from spec (documented, not silently dropped):** `raw:` byte-range locator and indexed duplicate-header locator. These are the only spec grammar items not implemented in this plan; everything else in §1–§11 maps to a task.
```
