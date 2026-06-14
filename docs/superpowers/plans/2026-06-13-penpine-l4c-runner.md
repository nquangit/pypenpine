# Penpine L4c — Runner & Validation Harness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build L4c of Penpine — a `Runner` that, given a base request and a chosen attack (by name/module/test-cases), analyzes the request, selects points, generates test cases, sends them concurrently against a baseline via a duck-typed sender, validates the responses, and returns a full `Report`.

**Architecture:** `Runner.run()` resolves a module (L4a registry), selects points (L4b `analyze().for_attack()` ∩ `module.applies`), generates `TestCase`s, captures a baseline, sends each (building requests via `replace_at`) concurrently with per-attempt isolation, validates with the module's `Validator`, and collects `Attempt`s into a `Report`. A sync facade mirrors the engine/manager pattern.

**Tech Stack:** Python 3.11+, stdlib `asyncio`/`time`/`threading`/`dataclasses`, `pytest`, `pytest-asyncio`. Depends on L0–L4b (on `main`).

---

## File Structure

```
penpine/attack/
  results.py     # Attempt, Report
  runner.py      # Runner
tests/attack/
  _fakes.py      # FakeSender + reflect (test helper)
  test_results.py test_runner.py test_runner_sync.py test_runner_integration.py
```

Build order: results → runner async core (+ fake sender) → sync facade → public API + integration.

---

## Task 1: Results model

**Files:**
- Create: `penpine/attack/results.py`
- Test: `tests/attack/test_results.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/attack/test_results.py
from penpine.attack.results import Attempt, Report
from penpine.attack.models import InjectionPoint, Payload, TestCase, Finding, Confidence


def _tc():
    return TestCase(point=InjectionPoint("param:a", "param", "a", "1"),
                    payload=Payload("x"), attack_type="t")


def test_attempt_ok_and_found():
    a = Attempt(test_case=_tc(), response=object())
    assert a.ok is True and a.found is False
    f = Finding("t", _tc().point, Payload("x"), Confidence.HIGH, "e")
    assert Attempt(test_case=_tc(), finding=f).found is True
    assert Attempt(test_case=_tc(), error=ValueError("x")).ok is False


def test_report_accessors_and_summary():
    point = InjectionPoint("param:a", "param", "a", "1")
    f = Finding("t", point, Payload("x"), Confidence.HIGH, "e")
    attempts = [
        Attempt(test_case=_tc(), finding=f, response=object()),
        Attempt(test_case=_tc(), error=ValueError("boom")),
        Attempt(test_case=_tc(), response=object()),
    ]
    r = Report(request=object(), attack_type="t", baseline=None, attempts=attempts)
    assert r.findings == [f]
    assert len(r.errors) == 1
    assert r.summary() == {"sent": 3, "failed": 1, "found": 1}
    assert len(r) == 3
    assert list(r)[0] is attempts[0]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/attack/test_results.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Write minimal implementation**

```python
# penpine/attack/results.py
"""Run results: per-test-case Attempt and the aggregate Report."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Attempt:
    test_case: object
    request: object | None = None
    response: object | None = None
    finding: object | None = None
    error: Exception | None = None
    elapsed_ms: float | None = None

    @property
    def ok(self) -> bool:
        return self.error is None

    @property
    def found(self) -> bool:
        return self.finding is not None


@dataclass
class Report:
    request: object
    attack_type: str | None
    baseline: object | None
    attempts: list = field(default_factory=list)

    @property
    def findings(self) -> list:
        return [a.finding for a in self.attempts if a.finding is not None]

    @property
    def errors(self) -> list:
        return [a for a in self.attempts if a.error is not None]

    def summary(self) -> dict:
        return {
            "sent": len(self.attempts),
            "failed": len(self.errors),
            "found": len(self.findings),
        }

    def __iter__(self):
        return iter(self.attempts)

    def __len__(self) -> int:
        return len(self.attempts)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/attack/test_results.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add penpine/attack/results.py tests/attack/test_results.py
git commit -c commit.gpgsign=false -m "feat: add attack run results (Attempt/Report)"
```

---

## Task 2: Runner async core + fake sender

**Files:**
- Create: `penpine/attack/runner.py`, `tests/attack/_fakes.py`
- Test: `tests/attack/test_runner.py`

- [ ] **Step 1: Create the test helper `tests/attack/_fakes.py`**

```python
# tests/attack/_fakes.py
"""Fake sender for runner tests (no sockets)."""
import re

from penpine.core.parse.http_parser import parse_response

_MARKER_RE = re.compile(rb"PENPINE_ECHO_[0-9a-fA-F]+")


class FakeSender:
    """async send(request). `script` is a list of raw bytes or callables(request)->bytes;
    the last entry repeats. Records sent requests on `.sent`."""

    def __init__(self, script):
        self._script = list(script)
        self._i = 0
        self.sent = []

    async def send(self, request):
        self.sent.append(request)
        item = self._script[min(self._i, len(self._script) - 1)]
        self._i += 1
        raw = item(request) if callable(item) else item
        return parse_response(raw)


def reflect(request):
    """Echo any PENPINE_ECHO_* marker found in the request back in the response body."""
    raw = request.serialize()
    match = _MARKER_RE.search(raw)
    body = match.group(0) if match else b"baseline"
    return b"HTTP/1.1 200 OK\r\nContent-Length: %d\r\n\r\n%s" % (len(body), body)
```

- [ ] **Step 2: Write the failing test**

```python
# tests/attack/test_runner.py
import pytest

from penpine.core.message import Request
from penpine.attack import registry
from penpine.attack.module import AttackModule
from penpine.attack.example import EchoGenerator, EchoValidator
from penpine.attack.generator import PayloadGenerator
from penpine.attack.validator import Validator
from penpine.attack.models import InjectionPoint, Payload, TestCase
from penpine.attack.analyze.analyzer import analyze
from penpine.attack.exceptions import AttackConfigError
from penpine.attack.runner import Runner
from tests.attack._fakes import FakeSender, reflect


@pytest.fixture(autouse=True)
def _clean_registry():
    registry.clear()
    yield
    registry.clear()


def xss_module():
    return AttackModule("xss", EchoGenerator(), EchoValidator(), applies_to=("param",))


async def test_happy_path_finds_reflection_on_tagged_point():
    registry.register(xss_module())
    runner = Runner(sender=FakeSender([reflect]))
    report = await runner.run(Request.from_url("http://h/?q=hi"), attack="xss")
    assert report.attack_type == "xss"
    assert report.baseline is not None
    assert report.findings                          # marker reflected -> Finding
    assert all(a.test_case.point.expr == "param:q" for a in report.attempts)
    assert report.attempts[0].finding.confidence.name == "HIGH"


async def test_no_applicable_points_yields_empty_report():
    registry.register(xss_module())
    runner = Runner(sender=FakeSender([reflect]))
    # numeric id -> analyzer tags sqli/idor, NOT xss -> no points selected
    report = await runner.run(Request.from_url("http://h/?id=7"), attack="xss")
    assert len(report) == 0
    assert report.findings == []


async def test_points_override_attacks_untagged_points():
    req = Request.from_url("http://h/?id=7")
    runner = Runner(sender=FakeSender([reflect]))
    report = await runner.run(req, module=xss_module(), points=analyze(req).all())
    assert report.attempts                          # attacked despite no xss tag


async def test_bring_your_own_test_cases_without_validator():
    req = Request.from_url("http://h/?a=1")
    point = InjectionPoint.from_locator(req.locate("param:a"))
    tc = TestCase(point=point, payload=Payload("X"), attack_type="custom")
    runner = Runner(sender=FakeSender([reflect]))
    report = await runner.run(req, test_cases=[tc])
    assert len(report) == 1
    assert report.attempts[0].finding is None       # no validator
    assert report.attempts[0].response is not None
    assert b"a=X" in report.attempts[0].request.serialize()   # payload inserted


async def test_error_isolation_records_errors_and_completes():
    registry.register(xss_module())

    class FailingSender:
        async def send(self, request):
            raise RuntimeError("net down")

    report = await Runner(sender=FailingSender()).run(
        Request.from_url("http://h/?q=hi"), attack="xss")
    assert report.baseline is None                  # baseline send failed, swallowed
    assert len(report) == 1
    assert report.attempts[0].error is not None
    assert report.summary()["failed"] == 1
    assert report.findings == []


async def test_baseline_passed_to_validator():
    captured = {}

    class G(PayloadGenerator):
        def generate(self, point, request):
            yield TestCase(point=point, payload=Payload("X"), attack_type="probe")

    class V(Validator):
        def evaluate(self, test_case, response, baseline):
            captured["baseline"] = baseline
            return None

    req = Request.from_url("http://h/?a=1")
    module = AttackModule("probe", G(), V(), applies_to=("param",))
    await Runner(sender=FakeSender([reflect])).run(
        req, module=module, points=analyze(req).all())
    assert captured["baseline"] is not None


async def test_unknown_attack_and_no_selector_raise():
    with pytest.raises(AttackConfigError):
        await Runner(sender=FakeSender([reflect])).run(
            Request.from_url("http://h/"), attack="nope")
    with pytest.raises(AttackConfigError):
        await Runner(sender=FakeSender([reflect])).run(Request.from_url("http://h/"))
```

- [ ] **Step 3: Run test to verify it fails**

Run: `python -m pytest tests/attack/test_runner.py -v`
Expected: FAIL — `penpine.attack.runner` missing.

- [ ] **Step 4: Write minimal implementation**

```python
# penpine/attack/runner.py
"""Runner: analyze -> generate -> send -> validate -> Report."""
from __future__ import annotations

import asyncio
import dataclasses
import time

from penpine.attack.analyze.analyzer import analyze
from penpine.attack.exceptions import AttackConfigError
from penpine.attack.registry import get as _registry_get
from penpine.attack.results import Attempt, Report
from penpine.transport.engine import Engine


class Runner:
    def __init__(self, sender=None, *, max_concurrency=10, capture_baseline=True):
        self._sender = sender if sender is not None else Engine()
        self._max_concurrency = max_concurrency
        self._capture_baseline = capture_baseline

    def _resolve_module(self, attack, module):
        if module is not None:
            return module
        if attack is not None:
            return _registry_get(attack)
        return None

    def _select_points(self, request, module, attack_type, points):
        if points is not None:
            return list(points)
        analysis = analyze(request)
        selected = analysis.for_attack(attack_type) if attack_type else analysis.all()
        return [p for p in selected if module is None or module.applies(p.kind)]

    async def run(self, request, *, attack=None, module=None, test_cases=None,
                  points=None, validator=None, sender=None):
        active_sender = sender if sender is not None else self._sender
        module = self._resolve_module(attack, module)
        attack_type = attack if attack is not None else (module.name if module else None)
        if validator is None and module is not None:
            validator = module.validator

        if test_cases is None:
            if module is None:
                raise AttackConfigError(
                    "run() requires one of attack=, module=, or test_cases=")
            cases = []
            for point in self._select_points(request, module, attack_type, points):
                cases.extend(module.generate(point, request))
            test_cases = cases
        else:
            test_cases = list(test_cases)

        baseline = None
        if self._capture_baseline:
            try:
                baseline = await active_sender.send(request)
            except Exception:
                baseline = None

        semaphore = asyncio.Semaphore(self._max_concurrency)

        async def _bounded(tc):
            async with semaphore:
                return await self._attempt(request, tc, validator, baseline, active_sender)

        attempts = list(await asyncio.gather(*(_bounded(tc) for tc in test_cases)))
        return Report(request=request, attack_type=attack_type,
                      baseline=baseline, attempts=attempts)

    async def _attempt(self, base, test_case, validator, baseline, sender):
        start = time.perf_counter()
        try:
            req = (test_case.request if test_case.request is not None
                   else base.replace_at(test_case.point.expr, test_case.payload.value))
        except Exception as exc:
            return Attempt(test_case=test_case, error=exc)

        sent_tc = dataclasses.replace(test_case, request=req)
        try:
            response = await sender.send(req)
        except Exception as exc:
            return Attempt(test_case=sent_tc, request=req, error=exc,
                           elapsed_ms=(time.perf_counter() - start) * 1000)

        finding = None
        if validator is not None:
            try:
                finding = validator.evaluate(sent_tc, response, baseline)
            except Exception as exc:
                return Attempt(test_case=sent_tc, request=req, response=response,
                               error=exc, elapsed_ms=(time.perf_counter() - start) * 1000)

        return Attempt(test_case=sent_tc, request=req, response=response,
                       finding=finding, elapsed_ms=(time.perf_counter() - start) * 1000)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest tests/attack/test_runner.py -v`
Expected: PASS (7 passed).

- [ ] **Step 6: Commit**

```bash
git add penpine/attack/runner.py tests/attack/_fakes.py tests/attack/test_runner.py
git commit -c commit.gpgsign=false -m "feat: add Runner async core (analyze/generate/send/validate)"
```

---

## Task 3: Sync facade

**Files:**
- Modify: `penpine/attack/runner.py`
- Test: `tests/attack/test_runner_sync.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/attack/test_runner_sync.py
import pytest

from penpine.core.message import Request
from penpine.attack import registry
from penpine.attack.module import AttackModule
from penpine.attack.example import EchoGenerator, EchoValidator
from penpine.attack.runner import Runner
from tests.attack._fakes import FakeSender, reflect


@pytest.fixture(autouse=True)
def _clean_registry():
    registry.clear()
    yield
    registry.clear()


def test_run_sync_returns_report_and_context_manager():
    registry.register(AttackModule("xss", EchoGenerator(), EchoValidator(),
                                   applies_to=("param",)))
    with Runner(sender=FakeSender([reflect])) as runner:
        report = runner.run_sync(Request.from_url("http://h/?q=hi"), attack="xss")
        assert report.findings
        assert report.summary()["sent"] >= 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/attack/test_runner_sync.py -v`
Expected: FAIL — `run_sync` missing.

- [ ] **Step 3: Write minimal implementation**

Add `import threading` to the imports at the top of `penpine/attack/runner.py` (with the other stdlib imports). In `Runner.__init__`, add at the end:

```python
        self._loop = None
        self._loop_thread = None
        self._loop_lock = threading.Lock()
```

Add these methods to `class Runner` (after `_attempt`):

```python
    def _ensure_loop(self):
        with self._loop_lock:
            if self._loop is None:
                self._loop = asyncio.new_event_loop()
                self._loop_thread = threading.Thread(
                    target=self._loop.run_forever, daemon=True)
                self._loop_thread.start()

    def run_sync(self, request, **kwargs):
        self._ensure_loop()
        future = asyncio.run_coroutine_threadsafe(
            self.run(request, **kwargs), self._loop)
        return future.result()

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

Run: `python -m pytest tests/attack/test_runner_sync.py -v`
Expected: PASS (1 passed).

- [ ] **Step 5: Commit**

```bash
git add penpine/attack/runner.py tests/attack/test_runner_sync.py
git commit -c commit.gpgsign=false -m "feat: add synchronous facade to Runner"
```

---

## Task 4: Public API + end-to-end integration

**Files:**
- Modify: `penpine/attack/__init__.py`, `penpine/__init__.py`
- Test: `tests/attack/test_runner_integration.py`, `tests/attack/test_public_api.py` (extend)

- [ ] **Step 1: Write the failing test**

```python
# tests/attack/test_runner_integration.py
import pytest

import penpine
from penpine.core.message import Request
from penpine.attack import Runner, Report, Attempt, registry, ECHO_MODULE
from tests.attack._fakes import FakeSender, reflect


@pytest.fixture(autouse=True)
def _clean_registry():
    registry.clear()
    yield
    registry.clear()


def test_runner_exposed_at_top_level():
    assert penpine.Runner is Runner


async def test_end_to_end_echo_module_via_registry():
    # EchoModule applies to param/json/form/header; attack by passing the module
    # directly (echo isn't an analyzer tag), over all points.
    from penpine.attack.analyze import analyze
    registry.register(ECHO_MODULE)
    req = Request.from_url("http://h/?token=abc")
    report = await Runner(sender=FakeSender([reflect])).run(
        req, module=registry.get("echo"), points=analyze(req).all())
    assert isinstance(report, Report)
    assert report.findings                       # reflecting sender -> echo finding
    assert all(isinstance(a, Attempt) for a in report)
    hit = report.findings[0]
    assert hit.attack_type == "echo"
    assert hit.request is not None               # runner set the sent request on the finding
```

```python
# tests/attack/test_public_api.py  (ADD to the existing file)
def test_runner_results_exported():
    from penpine.attack import Runner, Report, Attempt
    assert all([Runner, Report, Attempt])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/attack/test_runner_integration.py -v`
Expected: FAIL — `penpine.attack.Runner` / `penpine.Runner` missing.

- [ ] **Step 3: Write minimal implementation**

In `penpine/attack/__init__.py`, add after the existing analyze re-export line (`from penpine.attack.analyze import analyze, Analysis`):

```python
from penpine.attack.results import Attempt, Report
from penpine.attack.runner import Runner
```

Add `"Attempt", "Report", "Runner"` to the `__all__` list in `penpine/attack/__init__.py`.

In `penpine/__init__.py`, add after the existing data imports (before `__all__`):

```python
from penpine.attack.runner import Runner
```

Add `"Runner"` to the `__all__` list in `penpine/__init__.py`.

- [ ] **Step 4: Run the FULL suite**

Run: `python -m pytest -q`
Expected: PASS — all prior + L4c tests green (no failures, no errors).

- [ ] **Step 5: Commit**

```bash
git add penpine/attack/__init__.py penpine/__init__.py tests/attack/test_runner_integration.py tests/attack/test_public_api.py
git commit -c commit.gpgsign=false -m "feat: expose L4c Runner public API + end-to-end integration"
```

---

## Self-Review Notes (against the spec)

- **§3 module layout** → Tasks 1–2 create `results.py` and `runner.py`.
- **§4 results model** (Attempt.ok/found, Report.findings/errors/summary/iter/len) → Task 1.
- **§5 Runner** (resolve module/validator/attack_type; analyzer-guided selection ∩ applies; points override; baseline; concurrent bounded send; `_attempt` builds via replace_at and sets `test_case.request`; per-attempt isolation) → Task 2; sync facade → Task 3.
- **§6 public API** (Runner/Report/Attempt from `penpine.attack`; `penpine.Runner`) → Task 4.
- **§7 errors** (unknown attack / no selector → AttackConfigError; send/validator/baseline errors captured) → Task 2 (`test_error_isolation`, `test_unknown_attack_and_no_selector_raise`).
- **§8 testing** → reflecting `FakeSender` + `EchoModule`/`AttackModule("xss",…)`; happy path, no-points, override, BYO test cases, error isolation, baseline-to-validator, sync, integration.

**Deferred (per spec §2):** L3 Context capture / chaining; real modules (L4d).

**Import note for implementers:** `runner.py` imports the registry lookup directly (`from penpine.attack.registry import get as _registry_get`) and `analyze` from `penpine.attack.analyze.analyzer`, to avoid any dependence on partially-initialized package attributes. The `penpine/attack/__init__.py` runner/results re-exports go AFTER the existing analyze re-export line.
```
