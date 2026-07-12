# Flow Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a multi-step **Flow** primitive (`penpine.flow`) that runs an ordered sequence of requests across one or more identities, with per-step guards and step-local recovery, threading captured data through a shared context.

**Architecture:** A new L3.5 package `penpine/flow/` composing existing L3 `data` helpers (`render`, `build_mapping`, `capture`) and duck-typed senders (`Identity`/`SessionManager`/`Engine`). A `Flow` owns an ordered `list[Step]` and one flow-scoped `Context`; the engine renders each step's request against that context, sends via the step's actor, captures back into the context, and classifies each step into a `StepResult`. Fail-fast by default.

**Tech Stack:** Python 3.11+, stdlib `asyncio`, `dataclasses`. Tests: `pytest` + `pytest-asyncio` (`asyncio_mode=auto`), fake senders (no sockets).

## Global Constraints

- Python 3.11+; no third-party HTTP client (stdlib + `jsonpath-ng` only).
- Every async entry point has a synchronous `*_sync` facade.
- Public symbols re-exported through the package `__init__.py`; top-level user types added to `penpine/__init__.py`'s `__all__`.
- All exceptions derive from `penpine.exceptions.PenpineError`.
- Tests use fake senders — no sockets, no network.
- Lint/format gating: `ruff check .` and `ruff format --check .` must pass. Type check advisory: `mypy penpine`.
- Capture specs are a `list[Extract]` (from `penpine.data.extract`), NOT a dict.
- A sender is any object with `async send(request) -> Response`. An actor may additionally expose `.data` (a `DataProfile`); the engine reads it via `getattr(actor, "data", None)`.

---

### Task 1: Flow exceptions

**Files:**
- Create: `penpine/flow/__init__.py` (empty for now — package marker)
- Create: `penpine/flow/exceptions.py`
- Test: `tests/flow/__init__.py` (empty), `tests/flow/test_exceptions.py`

**Interfaces:**
- Consumes: `penpine.exceptions.PenpineError`
- Produces:
  - `FlowError(PenpineError)`
  - `StepError(FlowError)` with attributes `name: str`, `index: int | None`, `result: FlowResult | None` (result stored untyped — set by the engine later).

- [ ] **Step 1: Create empty package markers**

Create `penpine/flow/__init__.py` with a one-line docstring:

```python
"""Penpine L3.5 flow engine — multi-step scenarios over identities."""
```

Create `tests/flow/__init__.py` empty (no content).

- [ ] **Step 2: Write the failing test**

Create `tests/flow/test_exceptions.py`:

```python
import pytest

from penpine.exceptions import PenpineError
from penpine.flow.exceptions import FlowError, StepError


def test_flow_error_is_penpine_error():
    assert issubclass(FlowError, PenpineError)


def test_step_error_carries_name_index_and_result():
    err = StepError("login", index=2, result="sentinel")
    assert isinstance(err, FlowError)
    assert err.name == "login"
    assert err.index == 2
    assert err.result == "sentinel"
    assert "login" in str(err)


def test_step_error_defaults():
    err = StepError("activate")
    assert err.index is None
    assert err.result is None
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/flow/test_exceptions.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'penpine.flow.exceptions'`

- [ ] **Step 4: Write minimal implementation**

Create `penpine/flow/exceptions.py`:

```python
"""Flow-engine exception hierarchy."""

from __future__ import annotations

from penpine.exceptions import PenpineError


class FlowError(PenpineError):
    """Base class for flow-engine errors."""


class StepError(FlowError):
    """A flow step failed and was not recovered.

    Carries the partial ``FlowResult`` accumulated up to and including the
    failing step so a fail-fast caller still sees the progress made.
    """

    def __init__(self, name, *, index=None, result=None):
        self.name = name
        self.index = index
        self.result = result
        detail = f" (index {index})" if index is not None else ""
        super().__init__(f"flow step {name!r} failed{detail}")
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/flow/test_exceptions.py -v`
Expected: PASS (3 passed)

- [ ] **Step 6: Commit**

```bash
git add penpine/flow/__init__.py penpine/flow/exceptions.py tests/flow/__init__.py tests/flow/test_exceptions.py
git commit --no-gpg-sign -m "feat(flow): add flow exception hierarchy"
```

---

### Task 2: Result model

**Files:**
- Create: `penpine/flow/results.py`
- Test: `tests/flow/test_results.py`

**Interfaces:**
- Consumes: nothing (pure data).
- Produces:
  - `StepResult` dataclass: `step: str`, `actor`, `status: str` (`"ok"|"skipped"|"recovered"|"failed"`), `request=None`, `response=None`, `captured: list = []`, `recovery_ran: bool = False`, `error=None`, `elapsed_ms: float | None = None`.
  - `FlowResult` dataclass: `steps: list[StepResult]`, `context: dict`; properties `.ok`, `.failed_step`; methods `.step(name)`, `.summary()`; `__iter__`.

- [ ] **Step 1: Write the failing test**

Create `tests/flow/test_results.py`:

```python
import pytest

from penpine.flow.results import FlowResult, StepResult


def make(status, name="s"):
    return StepResult(step=name, actor=None, status=status)


def test_step_result_defaults():
    r = StepResult(step="login", actor=None, status="ok")
    assert r.captured == []
    assert r.recovery_ran is False
    assert r.error is None
    assert r.elapsed_ms is None


def test_flow_result_ok_true_when_no_failure():
    fr = FlowResult(steps=[make("ok"), make("skipped"), make("recovered")], context={})
    assert fr.ok is True
    assert fr.failed_step is None


def test_flow_result_ok_false_with_failure():
    failed = make("failed", "boom")
    fr = FlowResult(steps=[make("ok"), failed], context={})
    assert fr.ok is False
    assert fr.failed_step is failed


def test_flow_result_step_lookup_and_iter():
    a, b = make("ok", "a"), make("ok", "b")
    fr = FlowResult(steps=[a, b], context={"k": "v"})
    assert fr.step("b") is b
    assert list(fr) == [a, b]
    with pytest.raises(KeyError):
        fr.step("missing")


def test_flow_result_summary_counts():
    fr = FlowResult(
        steps=[make("ok"), make("ok"), make("skipped"), make("recovered"), make("failed")],
        context={},
    )
    assert fr.summary() == {"ran": 3, "skipped": 1, "recovered": 1, "failed": 1}
```

Note: `summary()["ran"]` counts steps that actually sent — status `ok` or `recovered`.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/flow/test_results.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'penpine.flow.results'`

- [ ] **Step 3: Write minimal implementation**

Create `penpine/flow/results.py`:

```python
"""Flow run results: per-step StepResult and the aggregate FlowResult."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field


@dataclass
class StepResult:
    step: str
    actor: object
    status: str  # "ok" | "skipped" | "recovered" | "failed"
    request: object | None = None
    response: object | None = None
    captured: list = field(default_factory=list)
    recovery_ran: bool = False
    error: Exception | None = None
    elapsed_ms: float | None = None


@dataclass
class FlowResult:
    steps: list
    context: dict

    @property
    def ok(self) -> bool:
        return all(s.status != "failed" for s in self.steps)

    @property
    def failed_step(self):
        return next((s for s in self.steps if s.status == "failed"), None)

    def step(self, name: str):
        for s in self.steps:
            if s.step == name:
                return s
        raise KeyError(name)

    def summary(self) -> dict:
        counts = Counter(s.status for s in self.steps)
        return {
            "ran": counts.get("ok", 0) + counts.get("recovered", 0),
            "skipped": counts.get("skipped", 0),
            "recovered": counts.get("recovered", 0),
            "failed": counts.get("failed", 0),
        }

    def __iter__(self):
        return iter(self.steps)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/flow/test_results.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add penpine/flow/results.py tests/flow/test_results.py
git commit --no-gpg-sign -m "feat(flow): add StepResult and FlowResult"
```

---

### Task 3: Step, Recovery, StepOutcome

**Files:**
- Create: `penpine/flow/step.py`
- Test: `tests/flow/test_step.py`

**Interfaces:**
- Consumes: `penpine.flow.exceptions.FlowError`.
- Produces:
  - `StepOutcome` dataclass: `ctx`, `actor`, `response=None`, `error=None`.
  - `Recovery` dataclass: `when` (callable `StepOutcome -> bool`), `do` (a `Flow`), `retry: bool = True`.
  - `Step` class: `Step(name, *, actor=None, request=None, action=None, capture=None, guard=None, recovery=None)`. Raises `FlowError` unless exactly one of `request`/`action` is set. Stores all args as attributes of the same name.

- [ ] **Step 1: Write the failing test**

Create `tests/flow/test_step.py`:

```python
import pytest

from penpine.core.message import Request
from penpine.flow.exceptions import FlowError
from penpine.flow.step import Recovery, Step, StepOutcome


def test_step_stores_fields():
    req = Request.from_url("http://h/")
    s = Step("login", request=req, capture=["x"], actor="alice")
    assert s.name == "login"
    assert s.request is req
    assert s.action is None
    assert s.capture == ["x"]
    assert s.actor == "alice"
    assert s.guard is None
    assert s.recovery is None


def test_step_action_variant():
    fn = lambda fc: None
    s = Step("probe", action=fn)
    assert s.action is fn
    assert s.request is None


def test_step_requires_exactly_one_of_request_or_action():
    with pytest.raises(FlowError):
        Step("bad")  # neither
    with pytest.raises(FlowError):
        Step("bad", request=Request.from_url("http://h/"), action=lambda fc: None)  # both


def test_step_outcome_defaults():
    o = StepOutcome(ctx="c", actor="a")
    assert o.response is None
    assert o.error is None


def test_recovery_defaults_retry_true():
    r = Recovery(when=lambda o: True, do="subflow")
    assert r.retry is True
    assert r.do == "subflow"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/flow/test_step.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'penpine.flow.step'`

- [ ] **Step 3: Write minimal implementation**

Create `penpine/flow/step.py`:

```python
"""Step, Recovery, and StepOutcome — the flow's declarative units."""

from __future__ import annotations

from dataclasses import dataclass

from penpine.flow.exceptions import FlowError


@dataclass
class StepOutcome:
    """Read-only view passed to Recovery.when after a step is attempted."""

    ctx: object
    actor: object
    response: object | None = None
    error: object | None = None


@dataclass
class Recovery:
    when: object  # Callable[[StepOutcome], bool]
    do: object  # a Flow, run with the parent's shared context
    retry: bool = True


class Step:
    def __init__(
        self,
        name,
        *,
        actor=None,
        request=None,
        action=None,
        capture=None,
        guard=None,
        recovery=None,
    ):
        if (request is None) == (action is None):
            raise FlowError(
                f"step {name!r} requires exactly one of `request` or `action`"
            )
        self.name = name
        self.actor = actor
        self.request = request
        self.action = action
        self.capture = capture
        self.guard = guard
        self.recovery = recovery
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/flow/test_step.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add penpine/flow/step.py tests/flow/test_step.py
git commit --no-gpg-sign -m "feat(flow): add Step, Recovery, StepOutcome"
```

---

### Task 4: Flow engine core (linear, guard, capture threading, fail-fast, run_sync)

**Files:**
- Create: `penpine/flow/flow.py`
- Create: `tests/flow/_fakes.py`
- Test: `tests/flow/test_flow.py`

**Interfaces:**
- Consumes: `render`, `build_mapping`, `capture` from `penpine.data`; `Context` from `penpine.data.context`; `StepResult`, `FlowResult`, `StepError`.
- Produces:
  - `Flow(steps, *, actor=None, context=None, continue_on_error=False)` with `.steps`, `.step(name)`, `async run()`, `run_sync()`, and internal `async _execute(ctx, default_actor)`, `async _run_step(step, ctx, default_actor)`, `async _attempt(step, ctx, actor)`.
  - `_run_step` returns a `StepResult` classified `skipped`/`ok`/`failed`.

Scope for this task: the **request path only** — guard-skip, send/render/capture, classify ok/failed, fail-fast vs `continue_on_error`. Recovery (Task 5) and the `action` escape hatch (Task 6) are added by later tasks that replace `_run_step`/`_attempt`; do NOT implement them here. Write the code exactly as shown.

- [ ] **Step 1: Add the flow test fake**

Create `tests/flow/_fakes.py`:

```python
"""Fake sender for flow tests (no sockets)."""

from penpine.core.parse.http_parser import parse_response
from penpine.data.profile import DataProfile


def response(body=b"ok", status=b"200 OK", headers=b""):
    head = b"HTTP/1.1 %s\r\n%sContent-Length: %d\r\n\r\n%s" % (
        status,
        headers,
        len(body),
        body,
    )
    return parse_response(head)


class FakeActor:
    """async send(request). `script` is a list of Response objects or
    callables(request)->Response; the last entry repeats. Records sent
    requests on `.sent`. Optional `.data` (DataProfile) for template merge."""

    def __init__(self, name="actor", script=None, data=None):
        self.name = name
        self._script = list(script or [response()])
        self._i = 0
        self.sent = []
        self.data = DataProfile(name, dict(data or {}))

    async def send(self, request):
        self.sent.append(request)
        item = self._script[min(self._i, len(self._script) - 1)]
        self._i += 1
        return item(request) if callable(item) else item
```

- [ ] **Step 2: Write the failing test**

Create `tests/flow/test_flow.py`:

```python
import pytest

from penpine.core.message import Request
from penpine.data.extract import Extract
from penpine.flow.exceptions import StepError
from penpine.flow.flow import Flow
from penpine.flow.results import FlowResult
from penpine.flow.step import Step
from tests.flow._fakes import FakeActor, response


async def test_linear_happy_path_threads_captured_data():
    actor = FakeActor(
        script=[
            response(b'{"token":"abc"}', headers=b"Content-Type: application/json\r\n"),
            response(b"done"),
        ]
    )
    flow = Flow(
        actor=actor,
        steps=[
            Step("login", request=Request.from_url("http://t/login"),
                 capture=[Extract("token", json="$.token")]),
            Step("act", request=Request.from_url("http://t/do?tok={{token}}")),
        ],
    )
    result = await flow.run()
    assert isinstance(result, FlowResult)
    assert [s.status for s in result] == ["ok", "ok"]
    assert result.context["token"] == "abc"
    # second request was rendered with the captured token
    assert b"tok=abc" in actor.sent[1].serialize()


async def test_guard_skips_step():
    actor = FakeActor(script=[response(b"x")])
    flow = Flow(
        actor=actor,
        steps=[
            Step("activate", request=Request.from_url("http://t/activate"),
                 guard=lambda ctx: ctx.has("needs_activation")),
            Step("login", request=Request.from_url("http://t/login")),
        ],
    )
    result = await flow.run()
    assert [s.status for s in result] == ["skipped", "ok"]
    assert len(actor.sent) == 1  # only login sent


async def test_fail_fast_raises_step_error_with_partial_result():
    def boom(request):
        raise RuntimeError("network down")

    actor = FakeActor(script=[response(b"ok"), boom])
    flow = Flow(
        actor=actor,
        steps=[
            Step("first", request=Request.from_url("http://t/a")),
            Step("second", request=Request.from_url("http://t/b")),
            Step("third", request=Request.from_url("http://t/c")),
        ],
    )
    with pytest.raises(StepError) as ei:
        await flow.run()
    err = ei.value
    assert err.name == "second"
    assert err.index == 1
    assert [s.status for s in err.result] == ["ok", "failed"]  # third never ran


async def test_continue_on_error_records_and_proceeds():
    def boom(request):
        raise RuntimeError("nope")

    actor = FakeActor(script=[response(b"ok"), boom, response(b"ok")])
    flow = Flow(
        actor=actor,
        continue_on_error=True,
        steps=[
            Step("a", request=Request.from_url("http://t/a")),
            Step("b", request=Request.from_url("http://t/b")),
            Step("c", request=Request.from_url("http://t/c")),
        ],
    )
    result = await flow.run()
    assert [s.status for s in result] == ["ok", "failed", "ok"]
    assert isinstance(result.step("b").error, RuntimeError)
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/flow/test_flow.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'penpine.flow.flow'`

- [ ] **Step 4: Write the engine**

Create `penpine/flow/flow.py`:

```python
"""Flow: an ordered, conditional, recoverable sequence of requests."""

from __future__ import annotations

import asyncio
import time

from penpine.data.capture import capture
from penpine.data.context import Context
from penpine.data.template import build_mapping, render
from penpine.flow.exceptions import FlowError, StepError
from penpine.flow.results import FlowResult, StepResult


class Flow:
    def __init__(self, steps, *, actor=None, context=None, continue_on_error=False):
        self._steps = list(steps)
        self._actor = actor
        self._ctx = context if context is not None else Context()
        self._continue_on_error = continue_on_error

    @property
    def steps(self):
        return list(self._steps)

    def step(self, name):
        for s in self._steps:
            if s.name == name:
                return s
        raise KeyError(name)

    async def run(self) -> FlowResult:
        return await self._execute(self._ctx, self._actor)

    def run_sync(self) -> FlowResult:
        return asyncio.run(self.run())

    async def _execute(self, ctx, default_actor) -> FlowResult:
        results = []
        for i, step in enumerate(self._steps):
            result = await self._run_step(step, ctx, default_actor)
            results.append(result)
            if result.status == "failed" and not self._continue_on_error:
                partial = FlowResult(steps=results, context=ctx.to_dict())
                raise StepError(step.name, index=i, result=partial)
        return FlowResult(steps=results, context=ctx.to_dict())

    async def _attempt(self, step, ctx, actor):
        start = time.perf_counter()
        request = response = error = None
        captured = []
        try:
            raw = step.request(ctx) if callable(step.request) else step.request
            request = render(
                raw, build_mapping(context=ctx, data=getattr(actor, "data", None))
            )
            response = await actor.send(request)
            if step.capture and response is not None:
                captured = list(capture(ctx, response, step.capture).keys())
        except Exception as exc:  # noqa: BLE001 - recorded on the StepResult, never leaked mid-step
            error = exc
        elapsed_ms = (time.perf_counter() - start) * 1000
        return request, response, error, captured, elapsed_ms

    async def _run_step(self, step, ctx, default_actor):
        actor = step.actor or default_actor
        if actor is None:
            raise FlowError(f"step {step.name!r} has no actor to send with")

        if step.guard is not None and not step.guard(ctx):
            return StepResult(step=step.name, actor=actor, status="skipped")

        request, response, error, captured, elapsed_ms = await self._attempt(step, ctx, actor)
        status = "failed" if error is not None else "ok"
        return StepResult(
            step=step.name, actor=actor, status=status, request=request,
            response=response, captured=captured, recovery_ran=False,
            error=error, elapsed_ms=elapsed_ms,
        )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/flow/test_flow.py -v`
Expected: PASS (4 passed)

- [ ] **Step 6: Run lint/format**

Run: `ruff check penpine/flow tests/flow && ruff format --check penpine/flow tests/flow`
Expected: no errors. If format check fails, run `ruff format penpine/flow tests/flow` and re-check.

- [ ] **Step 7: Commit**

```bash
git add penpine/flow/flow.py tests/flow/_fakes.py tests/flow/test_flow.py
git commit --no-gpg-sign -m "feat(flow): add Flow engine (linear, guard, capture, fail-fast)"
```

---

### Task 5: Recovery behavior

**Files:**
- Modify: `penpine/flow/flow.py` (replace `_run_step` with the recovery-aware version; add one import)
- Test: `tests/flow/test_recovery.py`

**Interfaces:**
- Consumes: `Flow`, `Step`, `Recovery`, `StepOutcome`, and the Task 4 fakes.
- Produces: a recovery-aware `_run_step(step, ctx, default_actor, *, allow_recovery=True)` that, when `step.recovery.when(outcome)` fires, runs `recovery.do` as a sub-flow sharing the context and retries the step once (`allow_recovery=False`), classifying `recovered`/`failed`.

This is a genuine TDD task: write the failing recovery tests first, then replace `_run_step`.

- [ ] **Step 1: Write the failing test**

Create `tests/flow/test_recovery.py`:

```python
import pytest

from penpine.core.message import Request
from penpine.flow.flow import Flow
from penpine.flow.step import Recovery, Step
from tests.flow._fakes import FakeActor, response


async def test_recovery_runs_subflow_then_retry_succeeds():
    # login returns 409 (needs activation) first, then 200 after activation ran.
    login_actor = FakeActor(
        script=[response(b"needs activation", status=b"409 Conflict"), response(b"ok")]
    )
    activate_actor = FakeActor(script=[response(b"activated")])

    activation = Flow(actor=activate_actor,
                      steps=[Step("activate", request=Request.from_url("http://t/activate"))])

    flow = Flow(
        actor=login_actor,
        steps=[
            Step(
                "login",
                request=Request.from_url("http://t/login"),
                recovery=Recovery(
                    when=lambda o: o.response is not None and o.response.status_code == 409,
                    do=activation,
                    retry=True,
                ),
            ),
        ],
    )
    result = await flow.run()
    assert result.step("login").status == "recovered"
    assert result.step("login").recovery_ran is True
    assert len(login_actor.sent) == 2  # initial + retry
    assert len(activate_actor.sent) == 1  # recovery subflow ran once


async def test_recovery_exhausted_when_condition_persists():
    # login always returns 409; recovery runs, retry still 409 -> failed.
    login_actor = FakeActor(script=[response(b"needs activation", status=b"409 Conflict")])
    activate_actor = FakeActor(script=[response(b"activated")])
    activation = Flow(actor=activate_actor,
                      steps=[Step("activate", request=Request.from_url("http://t/activate"))])

    flow = Flow(
        actor=login_actor,
        steps=[
            Step(
                "login",
                request=Request.from_url("http://t/login"),
                recovery=Recovery(
                    when=lambda o: o.response is not None and o.response.status_code == 409,
                    do=activation,
                    retry=True,
                ),
            ),
        ],
    )
    with pytest.raises(Exception):  # StepError, fail-fast
        await flow.run()
    # retry attempted exactly once beyond the original
    assert len(login_actor.sent) == 2


async def test_recovery_on_exception_then_retry_succeeds():
    def boom(request):
        raise RuntimeError("transient")

    actor = FakeActor(script=[boom, response(b"ok")])
    healer = Flow(actor=FakeActor(script=[response(b"healed")]),
                  steps=[Step("heal", request=Request.from_url("http://t/heal"))])
    flow = Flow(
        actor=actor,
        steps=[
            Step(
                "call",
                request=Request.from_url("http://t/call"),
                recovery=Recovery(when=lambda o: o.error is not None, do=healer, retry=True),
            )
        ],
    )
    result = await flow.run()
    assert result.step("call").status == "recovered"


async def test_recovery_without_retry_marks_recovered():
    actor = FakeActor(script=[response(b"needs activation", status=b"409 Conflict")])
    activation = Flow(actor=FakeActor(script=[response(b"activated")]),
                      steps=[Step("activate", request=Request.from_url("http://t/activate"))])
    flow = Flow(
        actor=actor,
        steps=[
            Step(
                "login",
                request=Request.from_url("http://t/login"),
                recovery=Recovery(
                    when=lambda o: o.response.status_code == 409, do=activation, retry=False
                ),
            )
        ],
    )
    result = await flow.run()
    assert result.step("login").status == "recovered"
    assert len(actor.sent) == 1  # no retry
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/flow/test_recovery.py -v`
Expected: FAIL — the current `_run_step` has no recovery, so `test_recovery_runs_subflow_then_retry_succeeds` fails on `status == "recovered"` (it is `"failed"`), and the 409 cases raise `StepError` instead of recovering.

- [ ] **Step 3: Add the `StepOutcome` import**

In `penpine/flow/flow.py`, add to the imports block:

```python
from penpine.flow.step import StepOutcome
```

- [ ] **Step 4: Replace `_run_step` with the recovery-aware version**

Replace the entire `_run_step` method in `penpine/flow/flow.py` with:

```python
    async def _run_step(self, step, ctx, default_actor, *, allow_recovery=True):
        actor = step.actor or default_actor
        if actor is None:
            raise FlowError(f"step {step.name!r} has no actor to send with")

        if step.guard is not None and not step.guard(ctx):
            return StepResult(step=step.name, actor=actor, status="skipped")

        request, response, error, captured, elapsed_ms = await self._attempt(step, ctx, actor)
        outcome = StepOutcome(ctx=ctx, actor=actor, response=response, error=error)

        triggered = step.recovery is not None and step.recovery.when(outcome)

        if not triggered:
            status = "failed" if error is not None else "ok"
            return StepResult(
                step=step.name, actor=actor, status=status, request=request,
                response=response, captured=captured, recovery_ran=False,
                error=error, elapsed_ms=elapsed_ms,
            )

        # A recovery condition fired.
        if not allow_recovery:
            # Already inside a retry — cannot recover again.
            return StepResult(
                step=step.name, actor=actor, status="failed", request=request,
                response=response, captured=captured, recovery_ran=True,
                error=error, elapsed_ms=elapsed_ms,
            )

        try:
            await step.recovery.do._execute(ctx, default_actor)
        except FlowError:
            return StepResult(
                step=step.name, actor=actor, status="failed", request=request,
                response=response, captured=captured, recovery_ran=True,
                error=error, elapsed_ms=elapsed_ms,
            )

        if step.recovery.retry:
            retry = await self._run_step(step, ctx, default_actor, allow_recovery=False)
            retry.recovery_ran = True
            if retry.status == "ok":
                retry.status = "recovered"
            return retry

        return StepResult(
            step=step.name, actor=actor, status="recovered", request=request,
            response=response, captured=captured, recovery_ran=True,
            error=error, elapsed_ms=elapsed_ms,
        )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/flow/test_recovery.py tests/flow/test_flow.py -v`
Expected: PASS (all — recovery tests plus the Task 4 tests still green).

- [ ] **Step 6: Run lint/format**

Run: `ruff check penpine/flow tests/flow && ruff format --check penpine/flow tests/flow`
Expected: no errors (fix with `ruff format` if needed).

- [ ] **Step 7: Commit**

```bash
git add penpine/flow/flow.py tests/flow/test_recovery.py
git commit --no-gpg-sign -m "feat(flow): add step-local recovery (subflow + retry-once)"
```

---

### Task 6: Escape-hatch action step

**Files:**
- Modify: `penpine/flow/flow.py` (add `FlowContext`, add `import inspect`, add the `action` branch to `_attempt`, relax the actor-required check in `_run_step`)
- Test: `tests/flow/test_action.py`

**Interfaces:**
- Consumes: `Flow`, `Step`.
- Produces:
  - `FlowContext(ctx, actor)` with `async send(request, *, actor=None)` (renders against the shared context, sends via the target).
  - `_attempt` gains an `action` branch: when `step.action` is set, it calls `step.action(FlowContext(ctx, actor))`, awaiting the result if it is awaitable.
  - `_run_step`'s actor-required check becomes `if actor is None and step.action is None:` so pure-action steps need no actor.

This is a genuine TDD task: write the failing action tests first, then add the code.

- [ ] **Step 1: Write the failing test**

Create `tests/flow/test_action.py`:

```python
from penpine.core.message import Request
from penpine.flow.flow import Flow, FlowContext
from penpine.flow.step import Step
from tests.flow._fakes import FakeActor, response


async def test_sync_action_step_runs():
    calls = []

    def action(fc):
        assert isinstance(fc, FlowContext)
        fc.ctx.set("flag", "set-by-action")
        calls.append(fc)
        return None

    flow = Flow(steps=[Step("compute", action=action)])
    result = await flow.run()
    assert result.step("compute").status == "ok"
    assert result.context["flag"] == "set-by-action"
    assert len(calls) == 1


async def test_async_action_can_send_via_flow_context():
    actor = FakeActor(script=[response(b"pong")])

    async def action(fc):
        return await fc.send(Request.from_url("http://t/ping"), actor=actor)

    flow = Flow(steps=[Step("ping", action=action)])
    result = await flow.run()
    assert result.step("ping").status == "ok"
    assert len(actor.sent) == 1
    assert result.step("ping").response.body.text() == "pong"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/flow/test_action.py -v`
Expected: FAIL — `ImportError: cannot import name 'FlowContext'` (it does not exist yet).

- [ ] **Step 3: Add `import inspect` and the `FlowContext` class**

In `penpine/flow/flow.py`, add `import inspect` to the stdlib imports (next to `import asyncio` / `import time`). Then add the `FlowContext` class immediately above `class Flow:`:

```python
class FlowContext:
    """Passed to an escape-hatch step's `action` callable."""

    def __init__(self, ctx, actor):
        self.ctx = ctx
        self.actor = actor

    async def send(self, request, *, actor=None):
        target = actor or self.actor
        rendered = render(
            request, build_mapping(context=self.ctx, data=getattr(target, "data", None))
        )
        return await target.send(rendered)
```

- [ ] **Step 4: Add the `action` branch to `_attempt`**

Replace the `try:` block body in `_attempt` so it branches on `step.action`. The full method becomes:

```python
    async def _attempt(self, step, ctx, actor):
        start = time.perf_counter()
        request = response = error = None
        captured = []
        try:
            if step.action is not None:
                maybe = step.action(FlowContext(ctx, actor))
                response = await maybe if inspect.isawaitable(maybe) else maybe
            else:
                raw = step.request(ctx) if callable(step.request) else step.request
                request = render(
                    raw, build_mapping(context=ctx, data=getattr(actor, "data", None))
                )
                response = await actor.send(request)
            if step.capture and response is not None:
                captured = list(capture(ctx, response, step.capture).keys())
        except Exception as exc:  # noqa: BLE001 - recorded on the StepResult, never leaked mid-step
            error = exc
        elapsed_ms = (time.perf_counter() - start) * 1000
        return request, response, error, captured, elapsed_ms
```

- [ ] **Step 5: Relax the actor-required check in `_run_step`**

In `_run_step`, change the actor guard so pure-action steps need no actor:

```python
        actor = step.actor or default_actor
        if actor is None and step.action is None:
            raise FlowError(f"step {step.name!r} has no actor to send with")
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest tests/flow -v`
Expected: PASS (all flow tests, including the new action tests).

- [ ] **Step 7: Run lint/format**

Run: `ruff check penpine/flow tests/flow && ruff format --check penpine/flow tests/flow`
Expected: no errors.

- [ ] **Step 8: Commit**

```bash
git add penpine/flow/flow.py tests/flow/test_action.py
git commit --no-gpg-sign -m "feat(flow): add escape-hatch action steps and FlowContext"
```

---

### Task 7: Public API wiring, multi-actor integration, sync parity

**Files:**
- Modify: `penpine/flow/__init__.py`
- Modify: `penpine/__init__.py`
- Test: `tests/flow/test_public_api.py`, `tests/flow/test_integration.py`

**Interfaces:**
- Consumes: all flow symbols.
- Produces:
  - `penpine.flow` exports: `Flow`, `FlowContext`, `Step`, `Recovery`, `StepOutcome`, `StepResult`, `FlowResult`, `FlowError`, `StepError`.
  - Top-level `penpine` adds `Flow` and `Step` to imports and `__all__`.

- [ ] **Step 1: Write the failing tests**

Create `tests/flow/test_public_api.py`:

```python
import penpine
from penpine.flow import (
    Flow,
    FlowContext,
    FlowError,
    FlowResult,
    Recovery,
    Step,
    StepError,
    StepOutcome,
    StepResult,
)


def test_flow_package_reexports():
    assert all(
        obj is not None
        for obj in (Flow, FlowContext, Step, Recovery, StepOutcome, StepResult, FlowResult, FlowError, StepError)
    )


def test_top_level_exports():
    assert penpine.Flow is Flow
    assert penpine.Step is Step
    assert "Flow" in penpine.__all__
    assert "Step" in penpine.__all__
```

Create `tests/flow/test_integration.py`:

```python
from penpine.core.message import Request
from penpine.data.context import Context
from penpine.data.extract import Extract
from penpine.flow.flow import Flow
from penpine.flow.step import Step
from tests.flow._fakes import FakeActor, response


async def test_multi_actor_shared_context_threads_data():
    # alice creates a doc, bob accesses it using alice's captured id (IDOR shape).
    alice = FakeActor(
        name="alice",
        script=[response(b'{"id":"42"}', headers=b"Content-Type: application/json\r\n")],
    )
    bob = FakeActor(name="bob", script=[response(b"seen")])

    flow = Flow(
        actor=alice,
        steps=[
            Step("create", request=Request.from_url("http://t/docs"),
                 capture=[Extract("doc_id", json="$.id")]),
            Step("access", actor=bob,
                 request=Request.from_url("http://t/docs/{{doc_id}}")),
        ],
    )
    result = await flow.run()
    assert result.context["doc_id"] == "42"
    assert b"/docs/42" in bob.sent[0].serialize()
    assert alice.sent and bob.sent  # both actors used, one shared context


def test_run_sync_matches_run():
    actor = FakeActor(script=[response(b"ok")])
    flow = Flow(actor=actor, steps=[Step("a", request=Request.from_url("http://t/a"))])
    result = flow.run_sync()  # plain sync call, no await
    assert result.step("a").status == "ok"
    assert result.summary() == {"ran": 1, "skipped": 0, "recovered": 0, "failed": 0}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/flow/test_public_api.py -v`
Expected: FAIL — `ImportError: cannot import name 'Flow' from 'penpine.flow'`

- [ ] **Step 3: Wire the flow package exports**

Replace `penpine/flow/__init__.py` with:

```python
"""Penpine L3.5 flow engine — multi-step scenarios over identities."""

from penpine.flow.exceptions import FlowError, StepError
from penpine.flow.flow import Flow, FlowContext
from penpine.flow.results import FlowResult, StepResult
from penpine.flow.step import Recovery, Step, StepOutcome

__all__ = [
    "Flow",
    "FlowContext",
    "Step",
    "Recovery",
    "StepOutcome",
    "StepResult",
    "FlowResult",
    "FlowError",
    "StepError",
]
```

- [ ] **Step 4: Wire the top-level exports**

In `penpine/__init__.py`, add the import (alphabetically near the other imports, after the `data` imports and before `logging`):

```python
from penpine.flow.flow import Flow
from penpine.flow.step import Step
```

And add `"Flow"` and `"Step"` to the `__all__` list (append after `"Runner"`).

- [ ] **Step 5: Run the tests**

Run: `pytest tests/flow/test_public_api.py tests/flow/test_integration.py -v`
Expected: PASS (4 passed)

- [ ] **Step 6: Run the full flow suite + lint + type check**

Run: `pytest tests/flow -v`
Expected: all pass.

Run: `ruff check penpine/flow tests/flow && ruff format --check penpine/flow tests/flow && mypy penpine`
Expected: ruff clean; mypy advisory (pre-existing behavior — no new errors from `penpine/flow`).

- [ ] **Step 7: Commit**

```bash
git add penpine/flow/__init__.py penpine/__init__.py tests/flow/test_public_api.py tests/flow/test_integration.py
git commit --no-gpg-sign -m "feat(flow): wire public API, add multi-actor + sync-parity integration tests"
```

---

### Task 8: Full-suite regression + README section

**Files:**
- Modify: `README.md` (add a "Flows" subsection under the L3/L4 material)
- Test: whole suite

**Interfaces:**
- Consumes: everything.
- Produces: documentation only.

- [ ] **Step 1: Run the whole suite**

Run: `pytest`
Expected: all pass (the existing ~400 plus the new flow tests). Fix any regression before proceeding.

- [ ] **Step 2: Add a README section**

Add this after the L3 identities section and before/around the L4 material in `README.md`:

````markdown
## Flows — multi-step scenarios

Chain requests into an ordered scenario with per-step guards and step-local
recovery. Steps share one flow-scoped context, so one actor's captured data
templates into another's request.

```python
from penpine import Flow, Step
from penpine.data.extract import Extract
from penpine.flow import Recovery

activation = Flow(actor=user, steps=[
    Step("activate", request=activate_req),
])

flow = Flow(actor=user, steps=[
    Step("login", request=login_req,
         capture=[Extract("token", json="$.access_token")],
         recovery=Recovery(
             when=lambda o: o.response.status_code == 409,   # needs activation
             do=activation, retry=True)),
    Step("transfer", request=Request.from_url("http://bank/xfer?tok={{token}}")),
])

result = flow.run_sync()
print(result.summary())              # {'ran': 2, 'skipped': 0, 'recovered': 0, 'failed': 0}
for step in result:
    print(step.step, step.status)
```

A step may name its own `actor` (any `Identity`/`SessionManager`/`Engine`), so a
flow can drive multiple identities against one shared context — the basis for
cross-user (IDOR) scenarios. By default a flow **fails fast**: the first
unrecovered step raises `StepError` with the partial `FlowResult` attached;
pass `continue_on_error=True` to record errors and keep going. Session-expiry
re-login is handled underneath by the L2 `SessionManager`, not the flow.
````

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit --no-gpg-sign -m "docs(flow): document the Flow engine in the README"
```

---

## Notes for the implementer

- **Do not re-implement session recovery.** 401 re-login and token refresh live in L2 and compose beneath any actor that is a `SessionManager`/`Identity`.
- **`capture` takes `list[Extract]`**, not a dict. The README's older `{...}` capture shorthand is not the real API.
- **Recovery is attempted once per step.** The retry runs with `allow_recovery=False`; a persistent triggering condition (or a second exception) on the retry classifies the step `failed`.
- **`run_sync` uses `asyncio.run`** and therefore must not be called from inside a running event loop (consistent with how the sync facades are used in tests and scripts).
