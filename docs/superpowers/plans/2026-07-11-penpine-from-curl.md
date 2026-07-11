# `Request.from_curl` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `Request.from_curl(command)` that parses a "Copy as cURL" command string into an immediately-sendable `Request` (method, headers, body, and `ConnectionMeta`).

**Architecture:** A new self-contained parser module `penpine/core/curl.py` (tokenizer + flag tables + `parse_curl`), with thin delegators `loaders.from_curl` and a `Request.from_curl` classmethod, mirroring the existing `from_raw`/`from_url` pattern.

**Tech Stack:** stdlib only (`shlex`, `base64`, `re`, `urllib.parse.quote`). No new runtime dependencies. Python 3.11+.

**Spec:** `docs/superpowers/specs/2026-07-11-penpine-from-curl-design.md`

## Global Constraints

- Commit WITHOUT GPG signing: `git -c commit.gpgsign=false commit -m "..."` (the `-c` flag goes BEFORE `commit`).
- Gates are LIVE on this repo: every commit must pass `ruff check .`, `ruff format --check .`, and `python -m pytest`. Run `ruff check <files> && ruff format <files>` before each commit. Ruff config: line-length 100, ruleset `E,F,W,I,UP,B,C4,SIM`.
- Do NOT define closures inside `for`/`while` loops that reference loop-scoped names (ruff `B023`). The parser walk uses a module-level `_next_value(tokens, i, inline, key)` helper, never a per-iteration closure.
- `BuildError` is imported from `penpine.exceptions` (NOT `penpine.core.exceptions`).
- No new top-level exports; the only new public surface is the `Request.from_curl` classmethod.
- Result `Request` MUST carry `ConnectionMeta(scheme, host, port)` from the URL (sendability).
- `serialize_request` does not auto-add `Content-Length`; `from_curl` sets it explicitly when a body is present and no `Content-Length` header was given.
- Existing full-suite baseline is `327 passed, 1 skipped`; new tests add to it, nothing regresses.

Relevant existing APIs (verbatim):
- `Headers(items: Iterable[tuple[str,str]] | None)`, `Headers.get(name, default=None)` (case-insensitive), `Headers.items()`.
- `Body(raw: bytes = b"", content_type=None)` (accepts `str` or `bytes`).
- `parse_url(url) -> ParsedUrl(scheme, host, port, path, query)` from `penpine.core.url`.
- `ConnectionMeta(scheme=None, host=None, port=None)` from `penpine.core.meta`.
- `Request(method, target, version="HTTP/1.1", headers=Headers(), body=Body(b""), meta=ConnectionMeta())` from `penpine.core.message`.
- `get_logger(__name__)` from `penpine.logging`.

---

### Task 1: curl tokenizer + helper functions

**Files:**
- Create: `penpine/core/curl.py`
- Test: `tests/core/test_curl_tokenize.py`

**Interfaces:**
- Produces: `_tokenize(command: str) -> list[str]`; `_split_header(raw: str) -> tuple[str, str]`; `_assemble_data(entries: list[tuple[str, str]]) -> str`; flag-table constants (`_VALUE_FLAGS`, `_IGNORED_VALUE_FLAGS`, `_BOOL_FLAGS`, `_IGNORED_BOOL_FLAGS`, `_FORM_FLAGS`); `_next_value(tokens, i, inline, key) -> tuple[str, int]`. Task 2 (`parse_curl`) consumes all of these.

- [ ] **Step 1: Write the failing test** — `tests/core/test_curl_tokenize.py`:
```python
import pytest

from penpine.core.curl import _assemble_data, _split_header, _tokenize
from penpine.exceptions import BuildError


def test_tokenize_strips_leading_curl_and_splits_quotes():
    toks = _tokenize("curl 'http://h/a b' -H \"X: 1\"")
    assert toks == ["http://h/a b", "-H", "X: 1"]


def test_tokenize_joins_line_continuations():
    cmd = "curl 'http://h/' \\\n  -H 'A: 1' \\\n  -H 'B: 2'"
    assert _tokenize(cmd) == ["http://h/", "-H", "A: 1", "-H", "B: 2"]


def test_tokenize_decodes_ansi_c_quoting():
    # $'...' with \n and \t decoded, wrapped so shlex keeps it one token
    toks = _tokenize("curl 'http://h/' --data-raw $'a\\tb\\nc'")
    assert toks == ["http://h/", "--data-raw", "a\tb\nc"]


def test_tokenize_unbalanced_quote_raises():
    with pytest.raises(BuildError):
        _tokenize("curl 'http://h/")


def test_split_header_colon_and_semicolon():
    assert _split_header("Content-Type: application/json") == ("Content-Type", "application/json")
    assert _split_header("X-Empty;") == ("X-Empty", "")


def test_assemble_data_joins_and_urlencodes():
    assert _assemble_data([("data", "a=1"), ("data", "b=2")]) == "a=1&b=2"
    assert _assemble_data([("urlencode", "q=a b")]) == "q=a%20b"
    assert _assemble_data([("urlencode", "plain value")]) == "plain%20value"
    assert _assemble_data([("raw", '{"x":1}')]) == '{"x":1}'
```

- [ ] **Step 2: Run test to verify it fails** — `python -m pytest tests/core/test_curl_tokenize.py -v` → `ModuleNotFoundError: No module named 'penpine.core.curl'`.

- [ ] **Step 3: Create `penpine/core/curl.py`:**
```python
"""Parse a curl command string into a Request."""

from __future__ import annotations

import re
import shlex
from urllib.parse import quote

from penpine.exceptions import BuildError
from penpine.logging import get_logger

log = get_logger(__name__)

# Flags we model that consume an argument.
_VALUE_FLAGS = {
    "-X", "--request", "-H", "--header", "-d", "--data", "--data-ascii",
    "--data-raw", "--data-binary", "--data-urlencode", "--json",
    "-b", "--cookie", "-A", "--user-agent", "-e", "--referer",
    "-u", "--user", "--url",
}
# Flags we accept but ignore, which still consume their argument.
_IGNORED_VALUE_FLAGS = {
    "-x", "--proxy", "--max-time", "--connect-timeout", "-m", "-o", "--output",
    "-E", "--cert", "--key", "--cacert", "--resolve", "--retry", "-w",
    "--write-out", "--limit-rate", "-r", "--range", "-T", "--upload-file",
    "--proxy-user",
}
# Boolean flags we model.
_BOOL_FLAGS = {"-G", "--get", "--compressed"}
# Boolean flags we accept but ignore.
_IGNORED_BOOL_FLAGS = {
    "-k", "--insecure", "-L", "--location", "-s", "--silent", "-S",
    "--show-error", "-v", "--verbose", "-i", "--include", "-f", "--fail",
    "-#", "--progress-bar", "--http1.1", "--http2", "-N", "--no-buffer",
}
_FORM_FLAGS = {"-F", "--form", "--form-string"}

_ANSI_C_RE = re.compile(r"\$'((?:[^'\\]|\\.)*)'")
_ANSI_C_SIMPLE = {
    "n": "\n", "t": "\t", "r": "\r", "\\": "\\", "'": "'", '"': '"',
    "a": "\a", "b": "\b", "f": "\f", "v": "\v",
}


def _decode_ansi_c(s: str) -> str:
    out: list[str] = []
    i = 0
    while i < len(s):
        ch = s[i]
        if ch == "\\" and i + 1 < len(s):
            nxt = s[i + 1]
            if nxt in _ANSI_C_SIMPLE:
                out.append(_ANSI_C_SIMPLE[nxt])
                i += 2
                continue
            if nxt == "x":
                m = re.match(r"[0-9a-fA-F]{1,2}", s[i + 2 : i + 4])
                if m:
                    out.append(chr(int(m.group(0), 16)))
                    i += 2 + len(m.group(0))
                    continue
            if nxt == "u":
                m = re.match(r"[0-9a-fA-F]{4}", s[i + 2 : i + 6])
                if m:
                    out.append(chr(int(m.group(0), 16)))
                    i += 6
                    continue
            out.append(ch)
            i += 1
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def _preprocess(command: str) -> str:
    command = re.sub(r"\\\r?\n", " ", command)

    def _repl(match: re.Match) -> str:
        decoded = _decode_ansi_c(match.group(1))
        # Re-wrap as a POSIX single-quoted token (escape embedded single quotes).
        return "'" + decoded.replace("'", "'\"'\"'") + "'"

    return _ANSI_C_RE.sub(_repl, command)


def _tokenize(command: str) -> list[str]:
    try:
        tokens = shlex.split(_preprocess(command), posix=True)
    except ValueError as exc:
        raise BuildError(f"could not tokenize curl command: {exc}") from exc
    if tokens and tokens[0] == "curl":
        tokens = tokens[1:]
    return tokens


def _split_header(raw: str) -> tuple[str, str]:
    if ":" in raw:
        name, _, value = raw.partition(":")
        return name.strip(), value.strip()
    if raw.endswith(";"):
        return raw[:-1].strip(), ""
    return raw.strip(), ""


def _assemble_data(entries: list[tuple[str, str]]) -> str:
    parts: list[str] = []
    for kind, value in entries:
        if kind == "urlencode":
            if "=" in value:
                name, _, content = value.partition("=")
                parts.append(f"{name}={quote(content, safe='')}")
            else:
                parts.append(quote(value, safe=""))
        else:
            parts.append(value)
    return "&".join(parts)


def _next_value(tokens: list[str], i: int, inline: str | None, key: str) -> tuple[str, int]:
    if inline is not None:
        return inline, i
    if i + 1 >= len(tokens):
        raise BuildError(f"curl flag {key} expects a value")
    return tokens[i + 1], i + 1
```

- [ ] **Step 4: Run test to verify it passes** — `python -m pytest tests/core/test_curl_tokenize.py -v` → all pass.

- [ ] **Step 5: Lint, format, commit.**
```bash
ruff check penpine/core/curl.py tests/core/test_curl_tokenize.py && ruff format penpine/core/curl.py tests/core/test_curl_tokenize.py
git add penpine/core/curl.py tests/core/test_curl_tokenize.py
git -c commit.gpgsign=false commit -m "feat(core): add curl tokenizer and helpers for from_curl"
```

---

### Task 2: `parse_curl` — flag walk + Request construction

**Files:**
- Modify: `penpine/core/curl.py` (add `parse_curl`)
- Test: `tests/core/test_curl_parse.py`

**Interfaces:**
- Consumes: everything from Task 1 (`_tokenize`, `_split_header`, `_assemble_data`, `_next_value`, the flag-table constants).
- Produces: `parse_curl(command: str) -> Request` (imports `Request` lazily inside the function to avoid a circular import, matching `loaders.from_url`).

- [ ] **Step 1: Write the failing test** — `tests/core/test_curl_parse.py`:
```python
import base64

import pytest

from penpine.core.curl import parse_curl
from penpine.exceptions import BuildError


def test_simple_get_sets_meta_and_host():
    req = parse_curl("curl 'https://api.example/things?id=1'")
    assert req.method == "GET"
    assert req.target == "/things?id=1"
    assert req.headers.get("Host") == "api.example"
    assert req.meta.scheme == "https"
    assert req.meta.host == "api.example"
    assert req.meta.port == 443


def test_headers_preserved_in_order():
    req = parse_curl("curl 'http://h/' -H 'A: 1' -H 'B: 2'")
    names = [n for n, _ in req.headers.items()]
    assert names == ["Host", "A", "B"]


def test_data_infers_post_and_content_type_and_length():
    req = parse_curl("curl 'http://h/x' --data-raw 'a=1&b=2'")
    assert req.method == "POST"
    assert req.body.raw == b"a=1&b=2"
    assert req.headers.get("Content-Type") == "application/x-www-form-urlencoded"
    assert req.headers.get("Content-Length") == "7"


def test_explicit_content_type_not_overridden():
    req = parse_curl("curl 'http://h/x' -H 'Content-Type: text/plain' -d 'hi'")
    assert req.headers.get("Content-Type") == "text/plain"


def test_json_flag_sets_body_and_content_type_and_accept():
    req = parse_curl("curl 'http://h/x' --json '{\"a\":1}'")
    assert req.method == "POST"
    assert req.body.raw == b'{"a":1}'
    assert req.headers.get("Content-Type") == "application/json"
    assert req.headers.get("Accept") == "application/json"


def test_dash_G_moves_data_to_query_and_clears_body():
    req = parse_curl("curl 'http://h/s?x=1' -G --data-urlencode 'q=a b'")
    assert req.method == "GET"
    assert req.target == "/s?x=1&q=a%20b"
    assert req.body.raw == b""


def test_explicit_method_wins():
    req = parse_curl("curl 'http://h/x' -X DELETE")
    assert req.method == "DELETE"


def test_basic_auth_cookie_ua_referer():
    req = parse_curl("curl 'http://h/' -u 'a:b' -b 'k=v' -A 'agent/1' -e 'http://ref/'")
    expected = "Basic " + base64.b64encode(b"a:b").decode()
    assert req.headers.get("Authorization") == expected
    assert req.headers.get("Cookie") == "k=v"
    assert req.headers.get("User-Agent") == "agent/1"
    assert req.headers.get("Referer") == "http://ref/"


def test_long_flag_equals_form():
    req = parse_curl("curl 'http://h/x' --data-raw='y=2' --request=PUT")
    assert req.method == "PUT"
    assert req.body.raw == b"y=2"


def test_ignored_value_flag_does_not_capture_url():
    req = parse_curl("curl -x http://proxy:8080 -k --max-time 30 'http://real/target'")
    assert req.meta.host == "real"
    assert req.target == "/target"


def test_unknown_flag_ignored():
    req = parse_curl("curl --totally-unknown 'http://h/ok'")
    assert req.meta.host == "h"


def test_non_default_port_in_host_header():
    req = parse_curl("curl 'http://h:8000/p'")
    assert req.headers.get("Host") == "h:8000"
    assert req.meta.port == 8000


def test_form_flag_raises():
    with pytest.raises(BuildError):
        parse_curl("curl 'http://h/' -F 'a=b'")


def test_no_url_raises():
    with pytest.raises(BuildError):
        parse_curl("curl -X POST")
```

- [ ] **Step 2: Run test to verify it fails** — `python -m pytest tests/core/test_curl_parse.py -v` → `ImportError: cannot import name 'parse_curl'`.

- [ ] **Step 3: Append `parse_curl` to `penpine/core/curl.py`:**
```python
def parse_curl(command: str) -> Request:
    from penpine.core.body.base import Body
    from penpine.core.headers import Headers
    from penpine.core.message import Request
    from penpine.core.meta import ConnectionMeta
    from penpine.core.url import parse_url

    tokens = _tokenize(command)

    url: str | None = None
    method: str | None = None
    header_items: list[tuple[str, str]] = []
    data_entries: list[tuple[str, str]] = []
    is_get = False
    is_json = False
    user: str | None = None

    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if not tok.startswith("-"):
            if url is None:
                url = tok
            else:
                log.debug("ignoring extra positional argument: %r", tok)
            i += 1
            continue

        if tok.startswith("--") and "=" in tok:
            key, _, inline = tok.partition("=")
        else:
            key, inline = tok, None

        if key in _FORM_FLAGS:
            raise BuildError(
                "multipart -F/--form is not supported by from_curl; "
                "use RequestBuilder for multipart bodies"
            )
        elif key in ("-X", "--request"):
            method, i = _next_value(tokens, i, inline, key)
        elif key in ("-H", "--header"):
            value, i = _next_value(tokens, i, inline, key)
            header_items.append(_split_header(value))
        elif key in ("-A", "--user-agent"):
            value, i = _next_value(tokens, i, inline, key)
            header_items.append(("User-Agent", value))
        elif key in ("-e", "--referer"):
            value, i = _next_value(tokens, i, inline, key)
            header_items.append(("Referer", value))
        elif key in ("-b", "--cookie"):
            value, i = _next_value(tokens, i, inline, key)
            header_items.append(("Cookie", value))
        elif key in ("-u", "--user"):
            user, i = _next_value(tokens, i, inline, key)
        elif key == "--url":
            url, i = _next_value(tokens, i, inline, key)
        elif key in ("-d", "--data", "--data-ascii"):
            value, i = _next_value(tokens, i, inline, key)
            data_entries.append(("data", value))
        elif key == "--data-raw":
            value, i = _next_value(tokens, i, inline, key)
            data_entries.append(("raw", value))
        elif key == "--data-binary":
            value, i = _next_value(tokens, i, inline, key)
            data_entries.append(("binary", value))
        elif key == "--data-urlencode":
            value, i = _next_value(tokens, i, inline, key)
            data_entries.append(("urlencode", value))
        elif key == "--json":
            value, i = _next_value(tokens, i, inline, key)
            data_entries.append(("raw", value))
            is_json = True
        elif key in ("-G", "--get"):
            is_get = True
        elif key == "--compressed":
            pass
        elif key in _IGNORED_VALUE_FLAGS:
            _, i = _next_value(tokens, i, inline, key)
            log.debug("ignoring curl flag with value: %s", key)
        else:
            log.debug("ignoring curl flag: %s", key)
        i += 1

    if url is None:
        raise BuildError("no URL found in curl command")

    parsed = parse_url(url)
    data_str = _assemble_data(data_entries)

    if method is None:
        method = "GET" if (is_get or not data_entries) else "POST"
    method = method.upper()

    query = parsed.query
    body = data_str.encode("utf-8")
    if is_get and data_entries:
        query = f"{query}&{data_str}" if query else data_str
        body = b""

    target = parsed.path + (f"?{query}" if query else "")
    host_header = parsed.host if parsed.port in (80, 443) else f"{parsed.host}:{parsed.port}"
    items: list[tuple[str, str]] = [("Host", host_header), *header_items]

    def _has(name: str) -> bool:
        return any(existing.lower() == name.lower() for existing, _ in items)

    if user is not None:
        if ":" not in user:
            user = user + ":"
        token = base64.b64encode(user.encode("utf-8")).decode("ascii")
        if not _has("Authorization"):
            items.append(("Authorization", f"Basic {token}"))

    if body and not _has("Content-Type"):
        items.append(
            ("Content-Type", "application/json" if is_json else "application/x-www-form-urlencoded")
        )
    if is_json and not _has("Accept"):
        items.append(("Accept", "application/json"))
    if body and not _has("Content-Length"):
        items.append(("Content-Length", str(len(body))))

    return Request(
        method=method,
        target=target,
        version="HTTP/1.1",
        headers=Headers(items),
        body=Body(body),
        meta=ConnectionMeta(scheme=parsed.scheme, host=parsed.host, port=parsed.port),
    )
```
Also add `import base64` to the top-of-file imports (alongside `re`, `shlex`). Keep the module import block sorted (ruff `I`): `base64`, `re`, `shlex`, then `from urllib.parse import quote`.

- [ ] **Step 4: Run test to verify it passes** — `python -m pytest tests/core/test_curl_parse.py -v` → all pass.

- [ ] **Step 5: Lint, format, commit.**
```bash
ruff check penpine/core/curl.py tests/core/test_curl_parse.py && ruff format penpine/core/curl.py tests/core/test_curl_parse.py
git add penpine/core/curl.py tests/core/test_curl_parse.py
git -c commit.gpgsign=false commit -m "feat(core): implement parse_curl flag walk and Request construction"
```

---

### Task 3: `loaders.from_curl` + `Request.from_curl` + integration

**Files:**
- Modify: `penpine/core/loaders.py` (add `from_curl`)
- Modify: `penpine/core/message.py` (add `Request.from_curl` classmethod)
- Test: `tests/core/test_from_curl_integration.py`

**Interfaces:**
- Consumes: `penpine.core.curl.parse_curl` (Task 2).
- Produces: `loaders.from_curl(command) -> Request`; `Request.from_curl(command) -> Request`.

- [ ] **Step 1: Write the failing test** — `tests/core/test_from_curl_integration.py`:
```python
from penpine.core.message import Request

CHROME_GET = (
    "curl 'https://api.example.com/v1/items?page=2' \\\n"
    "  -H 'accept: application/json' \\\n"
    "  -H 'authorization: Bearer abc.def' \\\n"
    "  -b 'sid=xyz' \\\n"
    "  --compressed"
)

FIREFOX_POST = (
    "curl 'https://api.example.com/login' -X POST "
    "-H 'Content-Type: application/json' "
    "--data-raw $'{\"user\":\"ann\",\"pw\":\"p@ss\"}'"
)


def test_request_from_curl_classmethod_chrome_get():
    req = Request.from_curl(CHROME_GET)
    assert req.method == "GET"
    assert req.target == "/v1/items?page=2"
    assert req.headers.get("authorization") == "Bearer abc.def"
    assert req.headers.get("Cookie") == "sid=xyz"
    assert (req.meta.scheme, req.meta.host, req.meta.port) == ("https", "api.example.com", 443)


def test_request_from_curl_firefox_post_ansi_c_body():
    req = Request.from_curl(FIREFOX_POST)
    assert req.method == "POST"
    assert req.body.raw == b'{"user":"ann","pw":"p@ss"}'
    assert req.headers.get("Content-Type") == "application/json"


def test_loaders_from_curl_matches_classmethod():
    from penpine.core.loaders import from_curl

    a = from_curl("curl 'http://h/p'")
    b = Request.from_curl("curl 'http://h/p'")
    assert a.method == b.method and a.target == b.target and a.meta == b.meta


def test_from_curl_result_is_sendable_meta_set():
    # Regression against the "request.meta missing host/port" class of bug.
    req = Request.from_curl("curl 'https://t.example:8443/api' -d 'x=1'")
    assert req.meta.host == "t.example"
    assert req.meta.port == 8443
    assert req.meta.scheme == "https"
```

- [ ] **Step 2: Run test to verify it fails** — `python -m pytest tests/core/test_from_curl_integration.py -v` → `AttributeError: type object 'Request' has no attribute 'from_curl'`.

- [ ] **Step 3a: Add `from_curl` to `penpine/core/loaders.py`** (after the existing `from_url` function):
```python
def from_curl(command):
    from penpine.core.curl import parse_curl

    return parse_curl(command)
```

- [ ] **Step 3b: Add the classmethod to `penpine/core/message.py`** immediately after the existing `from_file` classmethod:
```python
    @classmethod
    def from_curl(cls, command) -> Request:
        from penpine.core.loaders import from_curl

        return from_curl(command)
```

- [ ] **Step 4: Run test to verify it passes** — `python -m pytest tests/core/test_from_curl_integration.py -v` → all pass.

- [ ] **Step 5: Full suite + gates, then commit.**
```bash
python -m pytest -q          # expect: prior 327 + new curl tests all pass, 1 skipped
ruff check . && ruff format --check .
git add penpine/core/loaders.py penpine/core/message.py tests/core/test_from_curl_integration.py
git -c commit.gpgsign=false commit -m "feat(core): wire Request.from_curl and loaders.from_curl"
```

---

### Final verification (after all tasks)

- [ ] `ruff check . && ruff format --check . && python -m pytest -q` → gates clean; suite green (327 baseline + the new curl tests, 1 skipped).
- [ ] Quick smoke: `python -c "from penpine import Request; r=Request.from_curl(\"curl 'https://h/p?q=1' -H 'A: b' --data-raw x\"); print(r.method, r.target, r.meta, dict(r.headers.items()))"` prints POST, `/p?q=1`, https meta, and the headers.

---

## Self-Review

**Spec coverage:**
- §3 module layout (curl.py, loaders delegator, message classmethod) → Tasks 1–3. ✓
- §4 public API (`parse_curl`, `loaders.from_curl`, `Request.from_curl`) → Tasks 2–3. ✓
- §5 tokenizing (continuations, `$'…'` decode, shlex, drop `curl`, unbalanced→BuildError) → Task 1 (`_preprocess`/`_decode_ansi_c`/`_tokenize`) + tests. ✓
- §6 flag table & walk (value/ignored-value/bool/ignored-bool/form/unknown; `--json` as value flag) → Task 1 constants + Task 2 walk + tests (`test_ignored_value_flag_does_not_capture_url`, `test_unknown_flag_ignored`, `test_form_flag_raises`). ✓
- §7 build (URL→target/host/meta, body assembly, method inference incl. `-G`, header order, basic auth, curl content-type defaults, Content-Length) → Task 2 + tests. ✓
- §8 errors (no URL, tokenization, `-F`) → Tasks 1–2 tests. ✓
- §9 testing strategy → Tasks 1–3 tests, incl. sendability regression. ✓

**Placeholder scan:** No TBD/TODO; every step has complete code. `parse_curl`'s `-> Request` return annotation needs no import because `from __future__ import annotations` (already at the top of `curl.py` from Task 1) makes annotations strings; `Request` is imported lazily inside the body for the actual construction. No `# noqa` required. ✓

**Type/name consistency:** `_tokenize`, `_split_header`, `_assemble_data`, `_next_value`, and the five flag-table constant names are defined in Task 1 and used identically in Task 2. `parse_curl` (Task 2) is consumed by `loaders.from_curl` (Task 3), which the `Request.from_curl` classmethod (Task 3) calls. `Headers(items)`, `Body(body)`, `ConnectionMeta(...)`, `parse_url(...)` match the verified signatures in Global Constraints. ✓
