# Module Ergonomics, Flow Login & README Refresh — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let `Runner`/`FlowRunner` run one OR many modules in a single call (and accept a module class without parens); add a `FlowLoginProvider` that logs in via a Flow; and refresh the README to the typed/aggregated API.

**Architecture:** Extend the two runners' module-resolution to accept single-or-list and class-or-instance, aggregating all attempts into one report. Add `FlowLoginProvider(AuthProvider)` that runs a login `Flow` with the engine as actor and maps captured-context keys to a `Session`. Fix the README's stale `AttackType` strings and document the new capabilities.

**Tech Stack:** Python 3.11+, stdlib `asyncio`/`dataclasses`, pytest (`asyncio_mode=auto`), fakes (no network).

## Global Constraints

- Python 3.11+; no third-party HTTP client.
- All exceptions derive from `penpine.exceptions.PenpineError`; misuse raises `AttackConfigError`/`LoginError`.
- Every async entry point keeps its `*_sync` facade.
- Nothing attacks implicitly; `Flow.run()` stays behaviorally unchanged.
- `Runner`/`FlowRunner` never raise out of the batch — send/build/validator errors land on the attempt's `.error`. Bounded concurrency via `asyncio.Semaphore`.
- Report `attack_type`: the single resolved module's `attack_type` when exactly one module runs; `None` when more than one runs. Each `Finding`/`FlowFinding` carries its own `attack_type`.
- Public symbols re-exported through the layer's `__init__.py`.
- Tests use fakes; no sockets. Ruff lint+format gating; mypy must stay clean. Commits use `--no-gpg-sign`.

## Key current-code facts (use exactly)

- `Runner._resolve_modules(self, attack, module)` currently: `module` single (class→instantiate) OR `attack`→`registry.by_type(attack, signature_only=True)`. `run()` already loops resolved modules and aggregates into one `Report`; `attack_type = attack if attack is not None else (modules[0].attack_type if len(modules)==1 else None)`.
- `FlowRunner.run(self, base_flow, *, module, targets=None)`: single instance; `_run_to_result` catches `StepError`→`.result`; per-variant try/except → `FlowAttempt.error`.
- Built-in signature modules are **instances** (`SQLI_MODULE`, `XSS_MODULE` in `penpine/attack/modules/{sqli,xss}.py`); differential/flow modules are **classes** (`BooleanSqliModule`, `SkipStepModule`, `CrossUserModule`).
- `AuthProvider.login(engine) -> Session`; `Session(token=None, cookies=[], headers=[], data={}, issued_at, expires_at=None)`. `LoginError` in `penpine.auth.exceptions`.
- `Flow(steps, *, actor=None, context=None, continue_on_error=False)` with public `.steps`, `.continue_on_error`; `StepError` (in `penpine.flow.exceptions`) carries `.name` and the partial `FlowResult` on `.result`; `FlowResult.context` is a dict.
- Flow test fakes: `tests/flow/_fakes.py` — `FakeActor(name=, script=, data=)` (async `send`, records `.sent`), `response(body, status, headers)`. Attack request fakes: `tests/attack/_fakes.py` — `FakeSender`.

---

### Task 1: `Runner` — accept a list on `attack=`/`module=`

**Files:**
- Modify: `penpine/attack/runner.py`
- Test: `tests/attack/test_runner.py`

**Interfaces:**
- Consumes: `AttackType`, `registry.by_type`, `AttackConfigError`.
- Produces: `Runner.run(request, *, attack=None, module=None, ...)` where `attack` is `AttackType | list[AttackType] | None` and `module` is a module class/instance or a list of them; `_resolve_modules` returns a flat list of instances; a bare class needing constructor args raises `AttackConfigError`. `Report.attack_type` is the sole module's type when one resolves, else `None`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/attack/test_runner.py`:

```python
from penpine.attack import registry
from penpine.attack.exceptions import AttackConfigError
from penpine.attack.modules import register_builtins
from penpine.attack.modules.sqli import SQLI_MODULE
from penpine.attack.modules.xss import XSS_MODULE
from penpine.attack.types import AttackType


async def test_run_accepts_a_list_of_module_instances():
    sender = FakeSender([b"HTTP/1.1 200 OK\r\nContent-Length: 8\r\n\r\nbaseline"])
    req = Request.from_url("http://t/item?q=hello")  # 'q' -> sqli + xss candidate
    report = await Runner(sender=sender).run(req, module=[SQLI_MODULE, XSS_MODULE])
    techniques = {a.test_case.payload.technique for a in report}
    assert "error-based" in techniques  # sqli ran
    assert "reflected" in techniques  # xss ran
    assert report.attack_type is None  # heterogeneous -> None


async def test_run_accepts_a_list_of_attack_types():
    registry.clear()
    register_builtins()
    try:
        sender = FakeSender([b"HTTP/1.1 200 OK\r\nContent-Length: 8\r\n\r\nbaseline"])
        req = Request.from_url("http://t/item?q=hello")
        report = await Runner(sender=sender).run(req, attack=[AttackType.SQLI, AttackType.XSS])
        techniques = {a.test_case.payload.technique for a in report}
        assert {"error-based", "reflected"} <= techniques
        assert report.attack_type is None
    finally:
        registry.clear()


async def test_run_single_module_keeps_its_attack_type():
    sender = FakeSender([b"HTTP/1.1 200 OK\r\nContent-Length: 8\r\n\r\nbaseline"])
    req = Request.from_url("http://t/item?q=hello")
    report = await Runner(sender=sender).run(req, module=[SQLI_MODULE])  # list of one
    assert report.attack_type is AttackType.SQLI
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/attack/test_runner.py -k "list_of_module or list_of_attack or single_module_keeps" -v`
Expected: FAIL — `_resolve_modules` treats a list as a single object (`isinstance(module, type)` is False, so it returns `[[...]]`), so `.attack_type`/`.generate` blow up or nothing is generated.

- [ ] **Step 3: Rewrite `_resolve_modules` + the `attack_type` line**

In `penpine/attack/runner.py`, replace `_resolve_modules` with:

```python
    def _instantiate(self, m):
        if isinstance(m, type):
            try:
                return m()
            except TypeError as exc:
                raise AttackConfigError(
                    f"module class {m.__name__} needs constructor arguments; "
                    f"pass an instance instead"
                ) from exc
        return m

    def _resolve_modules(self, attack, module):
        modules = []
        if module is not None:
            items = module if isinstance(module, (list, tuple)) else [module]
            modules += [self._instantiate(m) for m in items]
        if attack is not None:
            attacks = attack if isinstance(attack, (list, tuple)) else [attack]
            for a in attacks:
                modules += _registry_by_type(a, signature_only=True)
        return modules
```

Then in `run()`, replace the `attack_type = (...)` assignment with:

```python
        attack_type = modules[0].attack_type if len(modules) == 1 else None
```

Update the `attack` parameter annotation to `attack=None` (drop the now-inaccurate `AttackType | None`; a prose note in the docstring is enough) and adjust the docstring's first paragraph to say `attack` accepts an `AttackType` or a list of them and `module` accepts a module/class or a list of them.

- [ ] **Step 4: Run the tests**

Run: `pytest tests/attack/test_runner.py -v`
Expected: PASS (new tests plus all existing runner tests still green).

- [ ] **Step 5: Run lint + type check**

Run: `ruff check penpine/attack/runner.py tests/attack/test_runner.py && ruff format --check penpine/attack/runner.py tests/attack/test_runner.py && mypy penpine`
Expected: ruff clean; mypy clean (`Success`).

- [ ] **Step 6: Commit**

```bash
git add penpine/attack/runner.py tests/attack/test_runner.py
git commit --no-gpg-sign -m "feat(attack): Runner accepts a list of modules/attack types"
```

---

### Task 2: `FlowRunner` — class-or-instance, single-or-list

**Files:**
- Modify: `penpine/attack/flow/runner.py`
- Test: `tests/attack/flow/test_runner.py`

**Interfaces:**
- Consumes: `FlowAttempt`, `FlowReport`, `StepError`, `AttackConfigError`, `FlowAttackModule`, `FlowVariant`, `AttackType`.
- Produces: `FlowRunner.run(base_flow, *, module, targets=None)` where `module` is a `FlowAttackModule` class/instance or a list of them; `_resolve_modules(module)` returns instances (classes instantiated no-arg; a class needing args raises `AttackConfigError`); one shared baseline; all modules' variants aggregate into one `FlowReport`; `attack_type` is the sole module's type when one runs, else `None`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/attack/flow/test_runner.py`:

```python
from penpine.attack.exceptions import AttackConfigError
from penpine.attack.flow.modules.cross_user import CrossUserModule
from penpine.attack.flow.modules.skip_step import SkipStepModule


def _twostep_flow():
    return Flow(
        actor=FakeActor(script=[response(b"ok")]),
        steps=[
            Step("a", request=Request.from_url("http://t/a")),
            Step("b", request=Request.from_url("http://t/b")),
        ],
    )


async def test_flowrunner_accepts_a_class():
    report = await FlowRunner().run(_twostep_flow(), module=SkipStepModule)  # class, no parens
    assert isinstance(report, FlowReport)
    assert report.attack_type is AttackType.BROKEN_ACCESS  # one module -> its type


async def test_flowrunner_bare_class_needing_args_raises():
    with pytest.raises(AttackConfigError):
        await FlowRunner().run(_twostep_flow(), module=CrossUserModule)  # needs owner/attacker


async def test_flowrunner_runs_a_list_of_modules_into_one_report():
    class _Stub(FlowAttackModule):
        attack_type = AttackType.IDOR
        name = "stub"

        def mutate(self, base_flow, baseline_result, targets):
            yield FlowVariant(flow=_twostep_flow(), target="stub-v")

        def validate(self, variant, variant_result, baseline_result):
            return None

    base = _twostep_flow()
    skip_only = await FlowRunner().run(_twostep_flow(), module=SkipStepModule)
    n_skip = skip_only.summary()["variants"]

    report = await FlowRunner().run(base, module=[SkipStepModule, _Stub()])
    assert report.summary()["variants"] == n_skip + 1  # skip's variants + stub's one
    assert report.attack_type is None  # heterogeneous
```

(`FlowAttackModule`, `FlowVariant`, `FlowReport`, `AttackType`, `Flow`, `Step`, `Request`, `FakeActor`, `response`, `pytest` are already imported in this file from earlier tasks; add only the new imports shown above.)

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/attack/flow/test_runner.py -k "accepts_a_class or bare_class or list_of_modules" -v`
Expected: FAIL — `run()` calls `module.mutate` on a class/list directly, raising `AttributeError`/`TypeError`.

- [ ] **Step 3: Rewrite `FlowRunner`**

Replace the body of `penpine/attack/flow/runner.py` from the imports through `run()` with:

```python
"""FlowRunner: baseline -> mutate -> run variants -> validate -> FlowReport."""

from __future__ import annotations

import asyncio

from penpine.attack.exceptions import AttackConfigError
from penpine.attack.flow.results import FlowAttempt, FlowReport
from penpine.flow.exceptions import StepError


class FlowRunner:
    """Runs a base flow's baseline, then each module's variants, then validates each.

    Variants share the base flow's actor(s). Concurrent variant runs
    (max_concurrency > 1) interleave every real `await actor.send(...)`, so
    against a STATEFUL actor (a SessionManager/Engine holding cookies,
    tokens, or a live connection) they can clobber each other's session
    state. Use an isolatable/stateless actor, or set max_concurrency=1, for
    stateful actors.
    """

    def __init__(self, *, max_concurrency=10):
        self._max_concurrency = max_concurrency

    def _resolve_modules(self, module):
        items = module if isinstance(module, (list, tuple)) else [module]
        out = []
        for m in items:
            if isinstance(m, type):
                try:
                    out.append(m())
                except TypeError as exc:
                    raise AttackConfigError(
                        f"module class {m.__name__} needs constructor arguments; "
                        f"pass an instance instead"
                    ) from exc
            else:
                out.append(m)
        return out

    async def _run_to_result(self, flow):
        """Run a flow, returning its FlowResult (full, or the partial from a fail-fast)."""
        try:
            return await flow.run()
        except StepError as exc:
            return exc.result

    async def _run_variant(self, mod, variant, baseline, semaphore):
        async with semaphore:
            try:
                result = await self._run_to_result(variant.flow)
            except Exception as exc:  # noqa: BLE001 - recorded on the attempt, never leaks
                return FlowAttempt(variant=variant, error=exc)
            try:
                finding = mod.validate(variant, result, baseline)
            except Exception as exc:  # noqa: BLE001
                return FlowAttempt(variant=variant, variant_result=result, error=exc)
            return FlowAttempt(variant=variant, variant_result=result, finding=finding)

    async def run(self, base_flow, *, module, targets=None) -> FlowReport:
        modules = self._resolve_modules(module)
        baseline = await self._run_to_result(base_flow)
        semaphore = asyncio.Semaphore(self._max_concurrency)

        tasks = []
        for mod in modules:
            for variant in mod.mutate(base_flow, baseline, targets):
                tasks.append(self._run_variant(mod, variant, baseline, semaphore))
        attempts = list(await asyncio.gather(*tasks))

        attack_type = modules[0].attack_type if len(modules) == 1 else None
        return FlowReport(
            base_flow=base_flow,
            attack_type=attack_type,
            baseline=baseline,
            attempts=attempts,
        )

    def run_sync(self, base_flow, **kwargs) -> FlowReport:
        return asyncio.run(self.run(base_flow, **kwargs))
```

- [ ] **Step 4: Run the tests**

Run: `pytest tests/attack/flow -v`
Expected: PASS (new tests plus all existing flow-attack tests — the single-module path is unchanged in behavior).

- [ ] **Step 5: Lint + type check**

Run: `ruff check penpine/attack/flow tests/attack/flow && ruff format --check penpine/attack/flow tests/attack/flow && mypy penpine`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add penpine/attack/flow/runner.py tests/attack/flow/test_runner.py
git commit --no-gpg-sign -m "feat(attack-flow): FlowRunner accepts a module class or a list of modules"
```

---

### Task 3: `FlowLoginProvider`

**Files:**
- Modify: `penpine/auth/provider.py`, `penpine/auth/__init__.py`
- Test: `tests/auth/test_flow_login.py`

**Interfaces:**
- Consumes: `AuthProvider`, `Session`, `LoginError`, `Flow`, `StepError`, `time`.
- Produces: `FlowLoginProvider(flow, *, token_key=None, expires_key=None, cookie_keys=None, data_keys=None)`; `async login(engine) -> Session` runs the flow with `engine` as its actor and maps captured-context keys to a `Session`; a fail-fast `StepError` becomes a `LoginError`. Exported from `penpine.auth`.

- [ ] **Step 1: Write the failing tests**

Create `tests/auth/test_flow_login.py`:

```python
import pytest

from penpine.auth.exceptions import LoginError
from penpine.auth.provider import FlowLoginProvider
from penpine.core.message import Request
from penpine.data.extract import Extract
from penpine.flow.flow import Flow
from penpine.flow.step import Step
from tests.flow._fakes import FakeActor, response

_JSON = b"Content-Type: application/json\r\n"


async def test_single_step_flow_login_yields_token():
    engine = FakeActor(script=[response(b'{"access_token":"JWT123"}', headers=_JSON)])
    login = Flow(
        steps=[
            Step("submit", request=Request.from_url("http://t/login"),
                 capture=[Extract("tok", json="$.access_token")]),
        ]
    )
    provider = FlowLoginProvider(login, token_key="tok")
    session = await provider.login(engine)
    assert session.token == "JWT123"
    assert len(engine.sent) == 1


async def test_multistep_flow_login_threads_csrf():
    engine = FakeActor(
        script=[
            response(b'{"csrf":"C1"}', headers=_JSON),
            response(b'{"access_token":"JWT9"}', headers=_JSON),
        ]
    )
    login = Flow(
        steps=[
            Step("page", request=Request.from_url("http://t/login"),
                 capture=[Extract("csrf", json="$.csrf")]),
            Step("submit", request=Request.from_url("http://t/login?csrf={{csrf}}"),
                 capture=[Extract("tok", json="$.access_token")]),
        ]
    )
    provider = FlowLoginProvider(login, token_key="tok")
    session = await provider.login(engine)
    assert session.token == "JWT9"
    assert b"csrf=C1" in engine.sent[1].serialize()  # step 2 used step 1's capture


async def test_failed_login_flow_raises_login_error():
    # 401 with no token -> the required Extract fails -> step fails -> StepError -> LoginError
    engine = FakeActor(script=[response(b"nope", status=b"401 Unauthorized")])
    login = Flow(
        steps=[
            Step("submit", request=Request.from_url("http://t/login"),
                 capture=[Extract("tok", json="$.access_token")]),
        ]
    )
    provider = FlowLoginProvider(login, token_key="tok")
    with pytest.raises(LoginError):
        await provider.login(engine)


async def test_flow_login_maps_expires_and_data():
    engine = FakeActor(
        script=[response(b'{"access_token":"T","ttl":"3600","uid":"42"}', headers=_JSON)]
    )
    login = Flow(
        steps=[
            Step("submit", request=Request.from_url("http://t/login"),
                 capture=[Extract("tok", json="$.access_token"),
                          Extract("ttl", json="$.ttl"),
                          Extract("uid", json="$.uid")]),
        ]
    )
    provider = FlowLoginProvider(login, token_key="tok", expires_key="ttl", data_keys=["uid"])
    session = await provider.login(engine)
    assert session.token == "T"
    assert session.expires_at is not None and session.expires_at > 0
    assert session.data == {"uid": "42"}
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/auth/test_flow_login.py -v`
Expected: FAIL — `ImportError: cannot import name 'FlowLoginProvider'`.

- [ ] **Step 3: Implement `FlowLoginProvider`**

In `penpine/auth/provider.py`, add the imports near the top (after the existing imports):

```python
from penpine.flow.exceptions import StepError
from penpine.flow.flow import Flow
```

Append the class at the end of the file:

```python
class FlowLoginProvider(AuthProvider):
    """Log in by running a Flow and mapping its captured context to a Session.

    The login Flow is run with the provided `engine` as its actor (login has no
    auth yet), so its steps should rely on the flow's default actor rather than
    naming their own. Capture the token/expiry/cookies/data in the flow via
    `Extract`, then name the context keys here.
    """

    def __init__(self, flow, *, token_key=None, expires_key=None, cookie_keys=None, data_keys=None):
        self._flow = flow
        self._token_key = token_key
        self._expires_key = expires_key
        self._cookie_keys = list(cookie_keys or [])
        self._data_keys = list(data_keys or [])

    async def login(self, engine) -> Session:
        run_flow = Flow(
            steps=self._flow.steps,
            actor=engine,
            continue_on_error=self._flow.continue_on_error,
        )
        try:
            result = await run_flow.run()
        except StepError as exc:
            raise LoginError(f"login flow failed at step {exc.name!r}") from exc

        ctx = result.context
        token = ctx.get(self._token_key) if self._token_key else None
        expires_at = None
        if self._expires_key and self._expires_key in ctx:
            try:
                expires_at = time.time() + float(ctx[self._expires_key])
            except (TypeError, ValueError):
                expires_at = None
        cookies = [(k, ctx[k]) for k in self._cookie_keys if k in ctx]
        data = {k: ctx[k] for k in self._data_keys if k in ctx}
        return Session(token=token, cookies=cookies, data=data, expires_at=expires_at)
```

- [ ] **Step 4: Export it**

In `penpine/auth/__init__.py`, change the provider import line
`from penpine.auth.provider import AuthProvider, FormLoginProvider, JsonLoginProvider` to also import `FlowLoginProvider`, and add `"FlowLoginProvider"` to `__all__`.

- [ ] **Step 5: Run the tests**

Run: `pytest tests/auth/test_flow_login.py -v`
Expected: PASS (4 passed).

- [ ] **Step 6: Lint + type check**

Run: `ruff check penpine/auth tests/auth/test_flow_login.py && ruff format --check penpine/auth tests/auth/test_flow_login.py && mypy penpine`
Expected: clean.

- [ ] **Step 7: Commit**

```bash
git add penpine/auth/provider.py penpine/auth/__init__.py tests/auth/test_flow_login.py
git commit --no-gpg-sign -m "feat(auth): add FlowLoginProvider (log in via a Flow)"
```

---

### Task 4: README refresh + full regression

**Files:**
- Modify: `README.md`
- Test: whole suite

**Interfaces:** documentation only.

- [ ] **Step 1: Run the whole suite first (baseline green)**

Run: `pytest -q`
Expected: all pass. If not, STOP and report.

- [ ] **Step 2: Fix the stale `AttackType` strings**

In `README.md`, make these exact edits (the string forms no longer work after the `AttackType` migration):

- The quick-start snippet: add `from penpine import AttackType` to the imports, and change `attack="sqli",` to `attack=AttackType.SQLI,`.
- `analysis.for_attack("sqli")` → `analysis.for_attack(AttackType.SQLI)` (and ensure `AttackType` is imported in that snippet, e.g. `from penpine.attack.types import AttackType`).
- `report = Runner().run_sync(req, attack="sqli")` → `report = Runner().run_sync(req, attack=AttackType.SQLI)`.
- `report = Runner(sender=alice).run_sync(req, attack="xss")` → `attack=AttackType.XSS`.
- `report = Runner().run_sync(req, attack="sqli", points=analyze(req).all())` → `attack=AttackType.SQLI`.
- In the "Status & roadmap" line, `Runner.run(attack="sqli-boolean")` → `Runner().run_sync(req, module=BooleanSqliModule)` and `"sqli-time"` → `module=TimeSqliModule` (these are differential/blind modules, selected by class, not by category string).

- [ ] **Step 3: Add the new-capability snippets**

In the L4 "Run an attack end-to-end" area, after the single-attack example, add:

````markdown
Run several attacks in one call — pass a list of modules or attack types; all
results aggregate into one report:

```python
from penpine.attack.modules.sqli import SQLI_MODULE
from penpine.attack.modules.xss import XSS_MODULE

report = Runner().run_sync(req, module=[SQLI_MODULE, XSS_MODULE])
report = Runner().run_sync(req, attack=[AttackType.SQLI, AttackType.XSS])
for f in report.findings:
    print(f.attack_type, f.point.expr)   # each finding carries its own type
```
````

In the flow-attacks README section (added earlier), update the examples to show class-not-instance and a list, and add the `FlowLoginProvider`:

````markdown
```python
from penpine import FlowRunner
from penpine.attack.flow import SkipStepModule, CrossUserModule

report = FlowRunner().run_sync(flow, module=SkipStepModule)          # class, no parens
report = FlowRunner().run_sync(flow, module=[SkipStepModule, CrossUserModule(owner=alice, attacker=bob)])
```

### Custom logins

`JsonLoginProvider`/`FormLoginProvider` cover single-request logins. For a
multi-request or custom login, run a Flow — or subclass `AuthProvider`:

```python
from penpine.auth import FlowLoginProvider
from penpine.data.extract import Extract

login = Flow(steps=[
    Step("page",   request=get_login,  capture=[Extract("csrf", regex=r'csrf" value="(.+?)"')]),
    Step("submit", request=post_login, capture=[Extract("tok", json="$.access_token")]),  # uses {{csrf}}
])
profile = AuthProfile("admin", provider=FlowLoginProvider(login, token_key="tok"), scheme=BearerAuth())
```

Anything more exotic: subclass `AuthProvider` and implement `async login(self, engine)`
to send whatever requests you need and return a `Session`.
````

- [ ] **Step 4: Full regression + gates**

Run: `pytest -q && ruff check . && ruff format --check . && mypy penpine`
Expected: all pass; mypy `Success`.

- [ ] **Step 5: Commit**

```bash
git add README.md
git commit --no-gpg-sign -m "docs: refresh README for typed AttackType, multi-module runs, and FlowLoginProvider"
```

---

## Notes for the implementer

- **The request `Runner` already loops and aggregates** — Task 1 only teaches `_resolve_modules` to accept lists and simplifies the `attack_type` line. Don't rewrite `run()`'s loop.
- **`attack_type` rule is uniform**: one resolved module → its `attack_type`; more than one → `None`. Per-finding `attack_type` is always specific.
- **Never-raise-batch is preserved** in `FlowRunner` — `_run_variant` keeps the two guarded blocks; a config error (bad class, in `_resolve_modules`) is a caller error that is allowed to propagate, consistent with the request `Runner`.
- **`FlowLoginProvider` overrides the login flow's actor** with the engine and reconstructs the flow from the public `.steps`/`.continue_on_error`, leaving the original flow untouched. Each `login()` gets a fresh `Context` (so refresh re-logs-in cleanly).
