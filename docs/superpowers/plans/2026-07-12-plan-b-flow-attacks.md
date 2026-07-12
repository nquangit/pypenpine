# Plan B — Flow-Aware Attacks Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add flow-structural attacks — a `FlowAttackModule` contract, mutation helpers, a `FlowRunner`, flow-specific results, and two modules (skip-a-step broken-access-control, cross-user IDOR) — built on the merged Flow engine and the typed `AttackType` vocabulary.

**Architecture:** A new `penpine/attack/flow/` package (L4-flow) that depends on `penpine.flow` and `penpine.attack` (for `AttackType`/`Confidence`). A `FlowAttackModule` mutates a base `Flow` into variant flows and validates each variant's `FlowResult` against a baseline `FlowResult` (a "differential over flows"). `FlowRunner` orchestrates baseline → mutate → run-variants → validate → `FlowReport`, never invoked implicitly. One small additive change to the Flow engine exposes `Flow.actor`/`Flow.continue_on_error` so variant flows can be reconstructed.

**Tech Stack:** Python 3.11+, stdlib `asyncio`/`dataclasses`, pytest (`asyncio_mode=auto`), fakes (no network).

## Global Constraints

- Python 3.11+; no third-party HTTP client. All exceptions derive from `penpine.exceptions.PenpineError`.
- Every async entry point has a `*_sync` facade.
- Nothing attacks implicitly: attacking a flow is always an explicit `FlowRunner` call; `Flow.run()` never attacks.
- `FlowRunner` never raises out of its batch — a variant that errors is recorded on its attempt (mirrors `Runner`).
- Attack categories are the typed `AttackType` enum (already merged): `AttackType.BROKEN_ACCESS` (skip-a-step), `AttackType.IDOR` (cross-user). Confidence reuses `penpine.attack.models.Confidence`.
- Public symbols re-exported through `penpine/attack/flow/__init__.py`; `FlowRunner` reachable at top-level `penpine`.
- Tests use fakes (the flow test fakes at `tests/flow/_fakes.py`: `FakeActor`, `response`). No sockets.
- Ruff lint+format gating; mypy advisory. Commits use `--no-gpg-sign`.
- The base flow and variant flows carry their own actors (per `Step`); `FlowRunner` does not take a global sender. Cross-user identities are the module's config.

## Key API facts (from the merged code — use these exactly)

- `Flow(steps, *, actor=None, context=None, continue_on_error=False)`; `.steps` (property, returns a list copy), `.step(name)`, `async run()`, `run_sync()`. Privates `_actor`, `_ctx`, `_continue_on_error`, `async _execute(ctx, default_actor)`.
- `Step(name, *, actor=None, request=None, action=None, capture=None, guard=None, recovery=None)` — attributes of the same names; validates exactly-one-of request/action.
- `FlowResult(steps, context)`: `.ok`, `.failed_step`, `.step(name)` (raises `KeyError`), `.summary()`, iterable. `StepResult(step, actor, status, request, response, captured, recovery_ran, error, elapsed_ms)` where `status ∈ {"ok","skipped","recovered","failed"}`.
- Fail-fast: `Flow.run()` raises `penpine.flow.exceptions.StepError` (which carries the partial `FlowResult` on `.result`) at the first `failed` step unless `continue_on_error=True`.
- `Context(initial: dict | None)` from `penpine.data.context`; `Context.to_dict()`.
- `AttackType` from `penpine.attack.types`; `Confidence` from `penpine.attack.models`.

---

### Task 1: Flow engine accessors + package skeleton

**Files:**
- Modify: `penpine/flow/flow.py`
- Create: `penpine/attack/flow/__init__.py` (empty-ish marker), `tests/attack/flow/__init__.py`
- Test: `tests/flow/test_accessors.py`

**Interfaces:**
- Produces: `Flow.actor` (read-only property → the flow's default actor) and `Flow.continue_on_error` (read-only property → the bool). Needed so mutation helpers can reconstruct a variant `Flow` from a base.

- [ ] **Step 1: Write the failing test**

Create `tests/flow/test_accessors.py`:

```python
from penpine.core.message import Request
from penpine.flow.flow import Flow
from penpine.flow.step import Step
from tests.flow._fakes import FakeActor


def test_flow_exposes_actor_and_continue_on_error():
    actor = FakeActor()
    flow = Flow(
        actor=actor,
        continue_on_error=True,
        steps=[Step("a", request=Request.from_url("http://t/a"))],
    )
    assert flow.actor is actor
    assert flow.continue_on_error is True


def test_flow_defaults_actor_none_continue_false():
    flow = Flow(steps=[Step("a", request=Request.from_url("http://t/a"))], actor=FakeActor())
    assert flow.continue_on_error is False
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/flow/test_accessors.py -v`
Expected: FAIL — `AttributeError: 'Flow' object has no attribute 'actor'`.

- [ ] **Step 3: Add the properties**

In `penpine/flow/flow.py`, add these two properties to `class Flow` (right after the existing `steps` property):

```python
    @property
    def actor(self):
        return self._actor

    @property
    def continue_on_error(self):
        return self._continue_on_error
```

- [ ] **Step 4: Create the package markers**

Create `penpine/attack/flow/__init__.py` with a docstring only (full re-exports come in Task 8):

```python
"""Penpine L4-flow: flow-structural attacks (skip-a-step, cross-user IDOR)."""
```

Create `tests/attack/flow/__init__.py` empty.

- [ ] **Step 5: Run the test**

Run: `pytest tests/flow/test_accessors.py -v`
Expected: PASS (2 passed).

- [ ] **Step 6: Commit**

```bash
git add penpine/flow/flow.py penpine/attack/flow/__init__.py tests/flow/test_accessors.py tests/attack/flow/__init__.py
git commit --no-gpg-sign -m "feat(flow): expose Flow.actor/continue_on_error for variant reconstruction"
```

---

### Task 2: `FlowAttackModule` contract + `FlowVariant`

**Files:**
- Create: `penpine/attack/flow/module.py`
- Test: `tests/attack/flow/test_module.py`

**Interfaces:**
- Produces:
  - `FlowVariant` dataclass: `flow`, `target: str`, `meta: dict = {}`.
  - `FlowAttackModule(ABC)`: class attrs `attack_type: AttackType`, `name: str`; abstract `mutate(self, base_flow, baseline_result, targets) -> Iterable[FlowVariant]` and `validate(self, variant, variant_result, baseline_result) -> FlowFinding | None`.

- [ ] **Step 1: Write the failing test**

Create `tests/attack/flow/test_module.py`:

```python
import pytest

from penpine.attack.flow.module import FlowAttackModule, FlowVariant
from penpine.attack.types import AttackType


def test_flow_variant_defaults():
    v = FlowVariant(flow="F", target="drop:login")
    assert v.flow == "F"
    assert v.target == "drop:login"
    assert v.meta == {}


def test_flow_attack_module_is_abstract():
    with pytest.raises(TypeError):
        FlowAttackModule()  # abstract mutate/validate


def test_concrete_subclass_instantiates():
    class M(FlowAttackModule):
        attack_type = AttackType.BROKEN_ACCESS
        name = "m"

        def mutate(self, base_flow, baseline_result, targets):
            return []

        def validate(self, variant, variant_result, baseline_result):
            return None

    m = M()
    assert m.attack_type is AttackType.BROKEN_ACCESS
    assert list(m.mutate(None, None, None)) == []
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/attack/flow/test_module.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'penpine.attack.flow.module'`.

- [ ] **Step 3: Implement**

Create `penpine/attack/flow/module.py`:

```python
"""FlowAttackModule contract + FlowVariant."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable
from dataclasses import dataclass, field


@dataclass
class FlowVariant:
    flow: object
    target: str
    meta: dict = field(default_factory=dict)


class FlowAttackModule(ABC):
    attack_type = None
    name = ""

    @abstractmethod
    def mutate(self, base_flow, baseline_result, targets) -> Iterable[FlowVariant]:
        """Yield variant flows (mutations of base_flow) tagged with what changed."""
        raise NotImplementedError

    @abstractmethod
    def validate(self, variant, variant_result, baseline_result):
        """Return a FlowFinding if the variant reveals a vulnerability, else None."""
        raise NotImplementedError
```

- [ ] **Step 4: Run the test**

Run: `pytest tests/attack/flow/test_module.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add penpine/attack/flow/module.py tests/attack/flow/test_module.py
git commit --no-gpg-sign -m "feat(attack-flow): add FlowAttackModule contract and FlowVariant"
```

---

### Task 3: Mutation helpers

**Files:**
- Create: `penpine/attack/flow/mutators.py`
- Test: `tests/attack/flow/test_mutators.py`

**Interfaces:**
- Consumes: `Flow`, `Step`, `Context`.
- Produces (all return NEW immutable flows; never mutate the base):
  - `drop_step(flow, name_or_index) -> Flow`
  - `swap_actor(flow, step_names, actor) -> Flow`
  - `seed_context(flow, values: dict) -> Flow`

- [ ] **Step 1: Write the failing test**

Create `tests/attack/flow/test_mutators.py`:

```python
from penpine.attack.flow.mutators import drop_step, seed_context, swap_actor
from penpine.core.message import Request
from penpine.flow.flow import Flow
from penpine.flow.step import Step
from tests.flow._fakes import FakeActor


def _base():
    return Flow(
        actor=FakeActor(name="alice"),
        continue_on_error=True,
        steps=[
            Step("login", request=Request.from_url("http://t/login")),
            Step("act", request=Request.from_url("http://t/act")),
            Step("confirm", request=Request.from_url("http://t/confirm")),
        ],
    )


def test_drop_step_by_name_returns_new_flow_without_it():
    base = _base()
    variant = drop_step(base, "act")
    assert [s.name for s in variant.steps] == ["login", "confirm"]
    # base unchanged
    assert [s.name for s in base.steps] == ["login", "act", "confirm"]
    # config carried over
    assert variant.actor is base.actor
    assert variant.continue_on_error is True


def test_drop_step_by_index():
    variant = drop_step(_base(), 0)
    assert [s.name for s in variant.steps] == ["act", "confirm"]


def test_swap_actor_replaces_actor_on_named_steps_only():
    base = _base()
    bob = FakeActor(name="bob")
    variant = swap_actor(base, ["act", "confirm"], bob)
    names_to_actor = {s.name: s.actor for s in variant.steps}
    assert names_to_actor["login"] is None          # untouched (used flow default)
    assert names_to_actor["act"] is bob
    assert names_to_actor["confirm"] is bob
    # base steps unchanged
    assert all(s.actor is None for s in base.steps)


def test_seed_context_preseeds_the_flow_context():
    base = _base()
    variant = seed_context(base, {"doc_id": "42"})
    # the variant's context starts with the seeded value
    assert variant._ctx.get("doc_id") == "42"
    assert [s.name for s in variant.steps] == ["login", "act", "confirm"]
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/attack/flow/test_mutators.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'penpine.attack.flow.mutators'`.

- [ ] **Step 3: Implement**

Create `penpine/attack/flow/mutators.py`:

```python
"""Pure flow mutations: return new immutable Flows, never mutate the base."""

from __future__ import annotations

from penpine.data.context import Context
from penpine.flow.flow import Flow
from penpine.flow.step import Step


def _with_actor(step, actor):
    return Step(
        step.name,
        actor=actor,
        request=step.request,
        action=step.action,
        capture=step.capture,
        guard=step.guard,
        recovery=step.recovery,
    )


def drop_step(flow, name_or_index) -> Flow:
    steps = flow.steps
    if isinstance(name_or_index, int):
        steps = [s for i, s in enumerate(steps) if i != name_or_index]
    else:
        steps = [s for s in steps if s.name != name_or_index]
    return Flow(steps=steps, actor=flow.actor, continue_on_error=flow.continue_on_error)


def swap_actor(flow, step_names, actor) -> Flow:
    names = set(step_names)
    steps = [_with_actor(s, actor) if s.name in names else s for s in flow.steps]
    return Flow(steps=steps, actor=flow.actor, continue_on_error=flow.continue_on_error)


def seed_context(flow, values) -> Flow:
    return Flow(
        steps=flow.steps,
        actor=flow.actor,
        context=Context(dict(values)),
        continue_on_error=flow.continue_on_error,
    )
```

- [ ] **Step 4: Run the test**

Run: `pytest tests/attack/flow/test_mutators.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add penpine/attack/flow/mutators.py tests/attack/flow/test_mutators.py
git commit --no-gpg-sign -m "feat(attack-flow): add drop_step/swap_actor/seed_context mutators"
```

---

### Task 4: Result model (`FlowFinding`, `FlowAttempt`, `FlowReport`)

**Files:**
- Create: `penpine/attack/flow/results.py`
- Test: `tests/attack/flow/test_results.py`

**Interfaces:**
- Consumes: `AttackType`, `Confidence`.
- Produces:
  - `FlowFinding(attack_type, target, confidence, evidence, baseline_result, variant_result)`.
  - `FlowAttempt(variant, variant_result=None, finding=None, error=None)` with `.found`, `.ok` properties.
  - `FlowReport(base_flow, attack_type, baseline, attempts=[])` with `.findings`, `.errors`, `.summary()`, `__iter__`.

- [ ] **Step 1: Write the failing test**

Create `tests/attack/flow/test_results.py`:

```python
from penpine.attack.flow.results import FlowAttempt, FlowFinding, FlowReport
from penpine.attack.models import Confidence
from penpine.attack.types import AttackType


def _finding():
    return FlowFinding(
        attack_type=AttackType.BROKEN_ACCESS,
        target="drop:authz",
        confidence=Confidence.HIGH,
        evidence="goal still succeeded",
        baseline_result="B",
        variant_result="V",
    )


def test_attempt_flags():
    ok = FlowAttempt(variant="v", variant_result="r", finding=_finding())
    assert ok.found is True
    assert ok.ok is True
    err = FlowAttempt(variant="v", error=RuntimeError("x"))
    assert err.found is False
    assert err.ok is False


def test_report_aggregates():
    f = _finding()
    report = FlowReport(
        base_flow="F",
        attack_type=AttackType.BROKEN_ACCESS,
        baseline="B",
        attempts=[
            FlowAttempt(variant="a", variant_result="r", finding=f),
            FlowAttempt(variant="b", variant_result="r", finding=None),
            FlowAttempt(variant="c", error=RuntimeError("x")),
        ],
    )
    assert report.findings == [f]
    assert len(report.errors) == 1
    assert report.summary() == {"variants": 3, "failed": 1, "found": 1}
    assert len(list(report)) == 3
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/attack/flow/test_results.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'penpine.attack.flow.results'`.

- [ ] **Step 3: Implement**

Create `penpine/attack/flow/results.py`:

```python
"""Flow-attack results: FlowFinding, per-variant FlowAttempt, aggregate FlowReport."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class FlowFinding:
    attack_type: object          # AttackType
    target: str
    confidence: object           # Confidence
    evidence: str
    baseline_result: object      # FlowResult
    variant_result: object       # FlowResult


@dataclass
class FlowAttempt:
    variant: object
    variant_result: object | None = None
    finding: object | None = None
    error: Exception | None = None

    @property
    def ok(self) -> bool:
        return self.error is None

    @property
    def found(self) -> bool:
        return self.finding is not None


@dataclass
class FlowReport:
    base_flow: object
    attack_type: object | None
    baseline: object
    attempts: list = field(default_factory=list)

    @property
    def findings(self) -> list:
        return [a.finding for a in self.attempts if a.finding is not None]

    @property
    def errors(self) -> list:
        return [a for a in self.attempts if a.error is not None]

    def summary(self) -> dict:
        return {
            "variants": len(self.attempts),
            "failed": len(self.errors),
            "found": len(self.findings),
        }

    def __iter__(self):
        return iter(self.attempts)
```

- [ ] **Step 4: Run the test**

Run: `pytest tests/attack/flow/test_results.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add penpine/attack/flow/results.py tests/attack/flow/test_results.py
git commit --no-gpg-sign -m "feat(attack-flow): add FlowFinding/FlowAttempt/FlowReport"
```

---

### Task 5: `FlowRunner`

**Files:**
- Create: `penpine/attack/flow/runner.py`
- Test: `tests/attack/flow/test_runner.py`

**Interfaces:**
- Consumes: `FlowReport`, `FlowAttempt`, `StepError` (from `penpine.flow.exceptions`), a `FlowAttackModule`.
- Produces: `FlowRunner(*, max_concurrency=10)` with `async run(base_flow, *, module, targets=None) -> FlowReport` and `run_sync(...)`.
  - Captures the baseline by running `base_flow` (a fail-fast `StepError` is caught and its partial `FlowResult` used).
  - Calls `module.mutate(base_flow, baseline, targets)`; runs each variant flow the same defensive way; calls `module.validate(...)`; aggregates into `FlowReport`. NEVER raises out of the batch — a variant run or validator error is recorded on that `FlowAttempt.error`.

- [ ] **Step 1: Write the failing test**

Create `tests/attack/flow/test_runner.py`:

```python
import pytest

from penpine.attack.flow.module import FlowAttackModule, FlowVariant
from penpine.attack.flow.results import FlowFinding, FlowReport
from penpine.attack.flow.runner import FlowRunner
from penpine.attack.models import Confidence
from penpine.attack.types import AttackType
from penpine.core.message import Request
from penpine.flow.flow import Flow
from penpine.flow.step import Step
from tests.flow._fakes import FakeActor, response


def _flow():
    return Flow(
        actor=FakeActor(script=[response(b"ok")]),
        steps=[Step("a", request=Request.from_url("http://t/a"))],
    )


class _StubModule(FlowAttackModule):
    attack_type = AttackType.BROKEN_ACCESS
    name = "stub"

    def __init__(self, *, n_variants=2, find_on=(), raise_on=()):
        self._n = n_variants
        self._find_on = set(find_on)
        self._raise_on = set(raise_on)

    def mutate(self, base_flow, baseline_result, targets):
        for i in range(self._n):
            yield FlowVariant(flow=_flow(), target=f"v{i}", meta={})

    def validate(self, variant, variant_result, baseline_result):
        if variant.target in self._raise_on:
            raise ValueError("validator boom")
        if variant.target in self._find_on:
            return FlowFinding(
                attack_type=self.attack_type,
                target=variant.target,
                confidence=Confidence.MEDIUM,
                evidence="stub",
                baseline_result=baseline_result,
                variant_result=variant_result,
            )
        return None


async def test_runner_runs_baseline_mutates_and_validates():
    report = await FlowRunner().run(_flow(), module=_StubModule(n_variants=3, find_on=["v1"]))
    assert isinstance(report, FlowReport)
    assert report.summary() == {"variants": 3, "failed": 0, "found": 1}
    assert report.findings[0].target == "v1"


async def test_runner_never_raises_on_validator_error():
    report = await FlowRunner().run(_flow(), module=_StubModule(n_variants=2, raise_on=["v0"]))
    assert report.summary()["failed"] == 1
    assert isinstance(report.errors[0].error, ValueError)


def test_run_sync_parity():
    report = FlowRunner().run_sync(_flow(), module=_StubModule(n_variants=1, find_on=["v0"]))
    assert report.summary() == {"variants": 1, "failed": 0, "found": 1}
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/attack/flow/test_runner.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'penpine.attack.flow.runner'`.

- [ ] **Step 3: Implement**

Create `penpine/attack/flow/runner.py`:

```python
"""FlowRunner: baseline -> mutate -> run variants -> validate -> FlowReport."""

from __future__ import annotations

import asyncio

from penpine.attack.flow.results import FlowAttempt, FlowReport
from penpine.flow.exceptions import StepError


class FlowRunner:
    def __init__(self, *, max_concurrency=10):
        self._max_concurrency = max_concurrency

    async def _run_to_result(self, flow):
        """Run a flow, returning its FlowResult (full, or the partial from a fail-fast)."""
        try:
            return await flow.run()
        except StepError as exc:
            return exc.result

    async def run(self, base_flow, *, module, targets=None) -> FlowReport:
        baseline = await self._run_to_result(base_flow)
        variants = list(module.mutate(base_flow, baseline, targets))
        semaphore = asyncio.Semaphore(self._max_concurrency)

        async def _attempt(variant):
            async with semaphore:
                try:
                    result = await self._run_to_result(variant.flow)
                except Exception as exc:  # noqa: BLE001 - recorded on the attempt, never leaks
                    return FlowAttempt(variant=variant, error=exc)
                try:
                    finding = module.validate(variant, result, baseline)
                except Exception as exc:  # noqa: BLE001
                    return FlowAttempt(variant=variant, variant_result=result, error=exc)
                return FlowAttempt(variant=variant, variant_result=result, finding=finding)

        attempts = list(await asyncio.gather(*(_attempt(v) for v in variants)))
        return FlowReport(
            base_flow=base_flow,
            attack_type=getattr(module, "attack_type", None),
            baseline=baseline,
            attempts=attempts,
        )

    def run_sync(self, base_flow, **kwargs) -> FlowReport:
        return asyncio.run(self.run(base_flow, **kwargs))
```

- [ ] **Step 4: Run the test**

Run: `pytest tests/attack/flow/test_runner.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Run lint/format**

Run: `ruff check penpine/attack/flow tests/attack/flow && ruff format --check penpine/attack/flow tests/attack/flow`
Expected: clean (run `ruff format` if needed).

- [ ] **Step 6: Commit**

```bash
git add penpine/attack/flow/runner.py tests/attack/flow/test_runner.py
git commit --no-gpg-sign -m "feat(attack-flow): add FlowRunner (baseline/mutate/validate, never-raise-batch)"
```

---

### Task 6: `SkipStepModule` (broken access control)

**Files:**
- Create: `penpine/attack/flow/modules/__init__.py`, `penpine/attack/flow/modules/skip_step.py`
- Test: `tests/attack/flow/test_skip_step.py`

**Interfaces:**
- Consumes: `FlowAttackModule`, `FlowVariant`, `FlowFinding`, `drop_step`, `AttackType`, `Confidence`.
- Produces: `SkipStepModule(*, goal=None, success=None)`:
  - `attack_type = AttackType.BROKEN_ACCESS`, `name = "skip-step"`.
  - `mutate`: goal defaults to the base flow's last step name; targets default to every step except the goal; yields a `drop_step` variant per target (meta carries `dropped` and `goal`).
  - `validate`: a finding fires when the baseline goal succeeded AND the variant goal still succeeds (goal `StepResult.status ∈ {"ok","recovered"}` with a 2xx response), i.e. dropping the step didn't stop the protected outcome. HIGH confidence if the variant goal response closely matches the baseline's (same status + same body bytes), else MEDIUM. A custom `success(FlowResult)->bool` predicate overrides the goal-status check.

- [ ] **Step 1: Write the failing test**

Create `tests/attack/flow/test_skip_step.py`:

```python
from penpine.attack.flow.modules.skip_step import SkipStepModule
from penpine.attack.flow.runner import FlowRunner
from penpine.attack.types import AttackType
from penpine.core.message import Request
from penpine.flow.flow import Flow
from penpine.flow.step import Step
from tests.flow._fakes import FakeActor, response


def _flow(confirm_needs_authz):
    # 'authz' gates 'confirm'. When confirm_needs_authz is True, the fake actor
    # returns 200 for confirm ONLY if the authz step ran first (secure);
    # when False, confirm returns 200 regardless (broken access control).
    state = {"authz_ran": False}

    def authz(request):
        state["authz_ran"] = True
        return response(b"authorized")

    def confirm(request):
        ok = (not confirm_needs_authz) or state["authz_ran"]
        return response(b"done") if ok else response(b"denied", status=b"403 Forbidden")

    class ScriptedActor(FakeActor):
        async def send(self, req):
            self.sent.append(req)
            if req.target.startswith("/authz"):
                return authz(req)
            if req.target.startswith("/confirm"):
                return confirm(req)
            return response(b"ok")

    return Flow(
        actor=ScriptedActor(),
        steps=[
            Step("login", request=Request.from_url("http://t/login")),
            Step("authz", request=Request.from_url("http://t/authz")),
            Step("confirm", request=Request.from_url("http://t/confirm")),
        ],
    )


async def test_finds_broken_access_when_goal_survives_dropped_gate():
    # confirm does NOT actually require authz -> dropping authz still yields 200 -> finding
    report = await FlowRunner().run(_flow(confirm_needs_authz=False), module=SkipStepModule())
    targets = {f.target for f in report.findings}
    assert "authz" in targets  # dropping the authz gate still reached a 200 confirm
    assert all(f.attack_type is AttackType.BROKEN_ACCESS for f in report.findings)


async def test_silent_when_dropping_gate_breaks_goal():
    # confirm truly requires authz -> dropping authz makes confirm 403 -> no finding for authz
    report = await FlowRunner().run(_flow(confirm_needs_authz=True), module=SkipStepModule())
    targets = {f.target for f in report.findings}
    assert "authz" not in targets
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/attack/flow/test_skip_step.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'penpine.attack.flow.modules.skip_step'`.

- [ ] **Step 3: Implement**

Create `penpine/attack/flow/modules/__init__.py`:

```python
"""Built-in flow-attack modules."""
```

Create `penpine/attack/flow/modules/skip_step.py`:

```python
"""Skip-a-step: drop a step and see whether the protected outcome still occurs."""

from __future__ import annotations

from penpine.attack.flow.module import FlowAttackModule, FlowVariant
from penpine.attack.flow.mutators import drop_step
from penpine.attack.flow.results import FlowFinding
from penpine.attack.models import Confidence
from penpine.attack.types import AttackType


def _is_2xx(response) -> bool:
    return response is not None and 200 <= getattr(response, "status_code", 0) < 300


class SkipStepModule(FlowAttackModule):
    attack_type = AttackType.BROKEN_ACCESS
    name = "skip-step"

    def __init__(self, *, goal=None, success=None):
        self._goal = goal
        self._success = success

    def mutate(self, base_flow, baseline_result, targets):
        steps = base_flow.steps
        goal = self._goal or (steps[-1].name if steps else None)
        names = list(targets) if targets is not None else [s.name for s in steps if s.name != goal]
        for name in names:
            yield FlowVariant(
                flow=drop_step(base_flow, name),
                target=name,
                meta={"dropped": name, "goal": goal},
            )

    def validate(self, variant, variant_result, baseline_result):
        goal = variant.meta["goal"]
        if not self._goal_ok(baseline_result, goal):
            return None  # baseline goal didn't succeed -> nothing to compare
        if not self._goal_ok(variant_result, goal):
            return None  # dropping the step broke the goal (secure)
        confidence = (
            Confidence.HIGH
            if self._goal_matches(baseline_result, variant_result, goal)
            else Confidence.MEDIUM
        )
        return FlowFinding(
            attack_type=self.attack_type,
            target=variant.target,
            confidence=confidence,
            evidence=(
                f"goal step {goal!r} still succeeded with step {variant.target!r} removed"
            ),
            baseline_result=baseline_result,
            variant_result=variant_result,
        )

    def _goal_ok(self, result, goal) -> bool:
        if self._success is not None:
            return bool(self._success(result))
        try:
            sr = result.step(goal)
        except KeyError:
            return False  # goal step never ran
        return sr.status in ("ok", "recovered") and _is_2xx(sr.response)

    def _goal_matches(self, baseline_result, variant_result, goal) -> bool:
        try:
            b = baseline_result.step(goal).response
            v = variant_result.step(goal).response
        except KeyError:
            return False
        if b is None or v is None:
            return False
        return b.status_code == v.status_code and b.body.raw == v.body.raw
```

- [ ] **Step 4: Run the test**

Run: `pytest tests/attack/flow/test_skip_step.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Run lint/format**

Run: `ruff check penpine/attack/flow tests/attack/flow && ruff format --check penpine/attack/flow tests/attack/flow`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add penpine/attack/flow/modules/ tests/attack/flow/test_skip_step.py
git commit --no-gpg-sign -m "feat(attack-flow): add SkipStepModule (broken access control)"
```

---

### Task 7: `CrossUserModule` (IDOR)

**Files:**
- Create: `penpine/attack/flow/modules/cross_user.py`
- Test: `tests/attack/flow/test_cross_user.py`

**Interfaces:**
- Consumes: `FlowAttackModule`, `FlowVariant`, `FlowFinding`, `swap_actor`, `seed_context`, `AttackType`, `Confidence`.
- Produces: `CrossUserModule(*, owner, attacker, access_steps=None)`:
  - `attack_type = AttackType.IDOR`, `name = "cross-user"`.
  - `mutate`: builds ONE variant that runs the access steps as `attacker` (`swap_actor`) with the variant context seeded from the baseline (owner) result's captured context (`seed_context`). Access steps default to every step that ran strictly after the first step that captured a value in the baseline; if none captured, defaults to the last step.
  - `validate`: a finding fires when a swapped access step under the attacker succeeds where denial was expected — `StepResult.status ∈ {"ok","recovered"}` and a 2xx response. HIGH confidence when the attacker's response body matches the owner's baseline response for that step, MEDIUM otherwise.

- [ ] **Step 1: Write the failing test**

Create `tests/attack/flow/test_cross_user.py`:

```python
from penpine.attack.flow.modules.cross_user import CrossUserModule
from penpine.attack.flow.runner import FlowRunner
from penpine.attack.types import AttackType
from penpine.core.message import Request
from penpine.data.extract import Extract
from penpine.flow.flow import Flow
from penpine.flow.step import Step
from tests.flow._fakes import FakeActor, response


def _owned_doc_actor(*, enforce_owner):
    # 'create' (/docs) returns a doc id; 'access' (/docs/<id>) returns the doc.
    # When enforce_owner is True the actor returns 403 for a non-owner (name != 'alice').
    class DocActor(FakeActor):
        async def send(self, req):
            self.sent.append(req)
            if req.target.startswith("/docs/"):  # access step: /docs/<id>
                if enforce_owner and self.name != "alice":
                    return response(b"forbidden", status=b"403 Forbidden")
                return response(b"secret-doc-body")
            # create step: /docs
            return response(b'{"id":"42"}', headers=b"Content-Type: application/json\r\n")

    return DocActor


def _flow(actor):
    return Flow(
        actor=actor,
        steps=[
            Step("create", request=Request.from_url("http://t/docs"),
                 capture=[Extract("doc_id", json="$.id")]),
            Step("access", request=Request.from_url("http://t/docs/{{doc_id}}")),
        ],
    )


async def test_finds_idor_when_attacker_reaches_owner_resource():
    DocActor = _owned_doc_actor(enforce_owner=False)  # no ownership check -> IDOR
    alice = DocActor(name="alice")
    bob = DocActor(name="bob")
    module = CrossUserModule(owner=alice, attacker=bob, access_steps=["access"])
    report = await FlowRunner().run(_flow(alice), module=module)
    assert report.summary()["found"] == 1
    assert report.findings[0].attack_type is AttackType.IDOR


async def test_silent_when_attacker_is_denied():
    DocActor = _owned_doc_actor(enforce_owner=True)  # ownership enforced -> no IDOR
    alice = DocActor(name="alice")
    bob = DocActor(name="bob")
    module = CrossUserModule(owner=alice, attacker=bob, access_steps=["access"])
    report = await FlowRunner().run(_flow(alice), module=module)
    assert report.summary()["found"] == 0
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/attack/flow/test_cross_user.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'penpine.attack.flow.modules.cross_user'`.

- [ ] **Step 3: Implement**

Create `penpine/attack/flow/modules/cross_user.py`:

```python
"""Cross-user IDOR: replay a flow's access steps as a different identity."""

from __future__ import annotations

from penpine.attack.flow.module import FlowAttackModule, FlowVariant
from penpine.attack.flow.mutators import seed_context, swap_actor
from penpine.attack.flow.results import FlowFinding
from penpine.attack.models import Confidence
from penpine.attack.types import AttackType


def _is_2xx(response) -> bool:
    return response is not None and 200 <= getattr(response, "status_code", 0) < 300


class CrossUserModule(FlowAttackModule):
    attack_type = AttackType.IDOR
    name = "cross-user"

    def __init__(self, *, owner, attacker, access_steps=None):
        self._owner = owner
        self._attacker = attacker
        self._access_steps = access_steps

    def mutate(self, base_flow, baseline_result, targets):
        access = (
            list(targets)
            if targets is not None
            else (self._access_steps or self._infer_access_steps(base_flow, baseline_result))
        )
        variant_flow = swap_actor(base_flow, access, self._attacker)
        variant_flow = seed_context(variant_flow, baseline_result.context)
        yield FlowVariant(
            flow=variant_flow,
            target=f"{self._actor_name(self._attacker)} accesses {access}",
            meta={"access_steps": access},
        )

    def validate(self, variant, variant_result, baseline_result):
        for name in variant.meta["access_steps"]:
            try:
                sr = variant_result.step(name)
            except KeyError:
                continue
            if sr.status in ("ok", "recovered") and _is_2xx(sr.response):
                confidence = (
                    Confidence.HIGH
                    if self._body_matches(baseline_result, sr, name)
                    else Confidence.MEDIUM
                )
                return FlowFinding(
                    attack_type=self.attack_type,
                    target=variant.target,
                    confidence=confidence,
                    evidence=(
                        f"{self._actor_name(self._attacker)} reached step {name!r} "
                        f"(status {sr.response.status_code}) that should be owner-only"
                    ),
                    baseline_result=baseline_result,
                    variant_result=variant_result,
                )
        return None

    def _infer_access_steps(self, base_flow, baseline_result) -> list:
        names = [s.name for s in base_flow.steps]
        first_capture_idx = None
        for i, name in enumerate(names):
            try:
                sr = baseline_result.step(name)
            except KeyError:
                continue
            if sr.captured:
                first_capture_idx = i
                break
        if first_capture_idx is None:
            return names[-1:]  # no capture -> just the last step
        return names[first_capture_idx + 1 :]

    def _body_matches(self, baseline_result, variant_sr, name) -> bool:
        try:
            b = baseline_result.step(name).response
        except KeyError:
            return False
        v = variant_sr.response
        if b is None or v is None:
            return False
        return b.body.raw == v.body.raw

    @staticmethod
    def _actor_name(actor) -> str:
        return getattr(actor, "name", repr(actor))
```

- [ ] **Step 4: Run the test**

Run: `pytest tests/attack/flow/test_cross_user.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Run lint/format**

Run: `ruff check penpine/attack/flow tests/attack/flow && ruff format --check penpine/attack/flow tests/attack/flow`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add penpine/attack/flow/modules/cross_user.py tests/attack/flow/test_cross_user.py
git commit --no-gpg-sign -m "feat(attack-flow): add CrossUserModule (IDOR)"
```

---

### Task 8: Public exports + full regression + README

**Files:**
- Modify: `penpine/attack/flow/__init__.py`, `penpine/__init__.py`, `README.md`
- Test: `tests/attack/flow/test_public_api.py`, whole suite

**Interfaces:**
- Produces: `penpine.attack.flow` re-exports `FlowRunner, FlowAttackModule, FlowVariant, FlowFinding, FlowAttempt, FlowReport, SkipStepModule, CrossUserModule, drop_step, swap_actor, seed_context`; top-level `penpine.FlowRunner`.

- [ ] **Step 1: Write the failing test**

Create `tests/attack/flow/test_public_api.py`:

```python
import penpine
from penpine.attack.flow import (
    CrossUserModule,
    FlowAttackModule,
    FlowAttempt,
    FlowFinding,
    FlowReport,
    FlowRunner,
    FlowVariant,
    SkipStepModule,
    drop_step,
    seed_context,
    swap_actor,
)


def test_reexports_present():
    for obj in (
        FlowRunner, FlowAttackModule, FlowVariant, FlowFinding, FlowAttempt,
        FlowReport, SkipStepModule, CrossUserModule, drop_step, swap_actor, seed_context,
    ):
        assert obj is not None


def test_top_level_flowrunner():
    assert penpine.FlowRunner is FlowRunner
    assert "FlowRunner" in penpine.__all__
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/attack/flow/test_public_api.py -v`
Expected: FAIL — `ImportError` (re-exports not wired).

- [ ] **Step 3: Wire `penpine/attack/flow/__init__.py`**

Replace it with:

```python
"""Penpine L4-flow: flow-structural attacks (skip-a-step, cross-user IDOR)."""

from penpine.attack.flow.module import FlowAttackModule, FlowVariant
from penpine.attack.flow.modules.cross_user import CrossUserModule
from penpine.attack.flow.modules.skip_step import SkipStepModule
from penpine.attack.flow.mutators import drop_step, seed_context, swap_actor
from penpine.attack.flow.results import FlowAttempt, FlowFinding, FlowReport
from penpine.attack.flow.runner import FlowRunner

__all__ = [
    "FlowRunner",
    "FlowAttackModule",
    "FlowVariant",
    "FlowFinding",
    "FlowAttempt",
    "FlowReport",
    "SkipStepModule",
    "CrossUserModule",
    "drop_step",
    "swap_actor",
    "seed_context",
]
```

- [ ] **Step 4: Wire top-level `penpine/__init__.py`**

Add `from penpine.attack.flow.runner import FlowRunner` alongside the existing imports, and append `"FlowRunner"` to `__all__`.

- [ ] **Step 5: Run the export test + whole suite + gates**

Run: `pytest tests/attack/flow/test_public_api.py -v` → PASS.
Run: `pytest -q` → whole suite green (~460 passed, 1 skipped).
Run: `ruff check . && ruff format --check . && mypy penpine` → ruff clean; mypy advisory (no new errors from `penpine/attack/flow`).

- [ ] **Step 6: Add a README section**

After the "Flows — multi-step scenarios" section, add:

````markdown
### Attacking flows

Flow-structural attacks target the *shape* of a scenario, not injection points.
A `FlowRunner` runs the base flow as a baseline, mutates it, runs each variant,
and validates the result — you invoke it explicitly (a `Flow` never attacks on
its own).

```python
from penpine import FlowRunner
from penpine.attack.flow import SkipStepModule, CrossUserModule

# Broken access control: does dropping a step still reach the protected outcome?
report = FlowRunner().run_sync(flow, module=SkipStepModule())   # goal = last step
for f in report.findings:
    print(f.confidence.name, f.target, "->", f.evidence)

# Cross-user (IDOR): can bob reach a resource alice created?
idor = CrossUserModule(owner=alice, attacker=bob, access_steps=["access"])
report = FlowRunner().run_sync(alice_flow, module=idor)
```
````

- [ ] **Step 7: Commit**

```bash
git add penpine/attack/flow/__init__.py penpine/__init__.py tests/attack/flow/test_public_api.py README.md
git commit --no-gpg-sign -m "feat(attack-flow): wire public API; document flow attacks"
```

---

## Notes for the implementer

- **Variant flows run defensively:** `FlowRunner._run_to_result` catches a fail-fast `StepError` and uses its partial `FlowResult`, so a variant whose dropped/swapped step causes a downstream failure still yields an inspectable result (the secure case for skip-a-step).
- **Each variant is an independent `Flow` instance** with its own fresh `Context` (or a seeded one for cross-user), so concurrent variant runs share no mutable state.
- **`FlowRunner` never raises out of the batch** — a variant run error or a validator exception lands on `FlowAttempt.error`. Preserve this.
- **Nothing attacks implicitly** — `FlowRunner` is the only entry point; `Flow.run()` is untouched behaviorally (Task 1 only adds two read-only properties).
- **`AttackType` is closed** — both modules use existing members (`BROKEN_ACCESS`, `IDOR`); no enum change needed.
