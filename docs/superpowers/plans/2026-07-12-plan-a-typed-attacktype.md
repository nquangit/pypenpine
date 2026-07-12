# Plan A — Typed `AttackType` Vocabulary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the attack layer's string attack identifiers with a typed, importable `AttackType` enum, so the set of attack types is discoverable and typo-safe, and third-party modules have a canonical vocabulary.

**Architecture:** Introduce `AttackType` in the attack core. Migrate the analyzer rules, the data models (`TestCase`/`Finding`), every built-in module, and the `Runner` from strings to `AttackType`. Unify the two module shapes onto one typed `attack_type` field (dropping the differential-only `select_attack_type`), and make `Runner.run` accept an `AttackType` (category → signature modules) or a module class/instance. Full suite green on the typed vocabulary.

**Tech Stack:** Python 3.11+, stdlib `enum`/`dataclasses`, pytest (`asyncio_mode=auto`), fakes (no network).

## Global Constraints

- Python 3.11+; no third-party HTTP client.
- All exceptions derive from `penpine.exceptions.PenpineError`; attack errors are `AttackConfigError`/`AttackError`.
- Every async entry point keeps its `*_sync` facade.
- Public symbols re-exported through package `__init__.py`; `AttackType` reachable from `penpine.attack` and (optionally) top-level `penpine`.
- Tests use fakes; no sockets. Commits use `--no-gpg-sign`.
- Ruff lint+format gating (`ruff check .`, `ruff format --check .`); mypy advisory.
- `AttackType` string `.value`s are the serialized form ONLY; the library API is typed. `AttackType.from_str(s)` is the sole coercion point.
- Behavior parity except: (a) identifiers are typed; (b) `attack=AttackType.X` selects the registered **signature** modules of that category (non-`probe` modules), leaving differential/blind modules opt-in via explicit `module=`.
- Enum members must cover every tag the current rules emit: `sqli, xss, idor, ssrf, open-redirect, path-traversal, lfi, host-header, header-injection`, plus new `broken-access`.

---

### Task 1: `AttackType` enum

**Files:**
- Create: `penpine/attack/types.py`
- Test: `tests/attack/test_types.py`

**Interfaces:**
- Produces: `AttackType(Enum)` with members and string values as below; classmethod `from_str(value) -> AttackType` raising `AttackConfigError` on unknown; members are sortable for the analyzer via `.value`.

- [ ] **Step 1: Write the failing test**

Create `tests/attack/test_types.py`:

```python
import pytest

from penpine.attack.exceptions import AttackConfigError
from penpine.attack.types import AttackType


def test_members_cover_all_rule_tags_plus_broken_access():
    expected = {
        "sqli", "xss", "idor", "ssrf", "open-redirect",
        "path-traversal", "lfi", "host-header", "header-injection", "broken-access",
    }
    assert {t.value for t in AttackType} == expected


def test_from_str_roundtrips():
    for t in AttackType:
        assert AttackType.from_str(t.value) is t


def test_from_str_unknown_raises():
    with pytest.raises(AttackConfigError):
        AttackType.from_str("nope")


def test_values_are_sortable_for_deterministic_tagging():
    # analyzer sorts tags by value for stable output
    ordered = sorted(AttackType, key=lambda t: t.value)
    assert [t.value for t in ordered] == sorted(t.value for t in AttackType)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/attack/test_types.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'penpine.attack.types'`

- [ ] **Step 3: Write the implementation**

Create `penpine/attack/types.py`:

```python
"""AttackType: the canonical, typed attack-category vocabulary."""

from __future__ import annotations

from enum import Enum

from penpine.attack.exceptions import AttackConfigError


class AttackType(Enum):
    SQLI = "sqli"
    XSS = "xss"
    IDOR = "idor"
    SSRF = "ssrf"
    OPEN_REDIRECT = "open-redirect"
    PATH_TRAVERSAL = "path-traversal"
    LFI = "lfi"
    HOST_HEADER = "host-header"
    HEADER_INJECTION = "header-injection"
    BROKEN_ACCESS = "broken-access"

    @classmethod
    def from_str(cls, value: str) -> "AttackType":
        """Coerce a serialized string to an AttackType (CLI/config/report edge only)."""
        try:
            return cls(value)
        except ValueError:
            raise AttackConfigError(f"unknown attack type: {value!r}") from None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/attack/test_types.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add penpine/attack/types.py tests/attack/test_types.py
git commit --no-gpg-sign -m "feat(attack): add typed AttackType vocabulary"
```

---

### Task 2: Type the data models (`TestCase.attack_type`, `Finding.attack_type`)

**Files:**
- Modify: `penpine/attack/models.py`
- Test: `tests/attack/test_models.py` (update existing assertions to `AttackType`)

**Interfaces:**
- Consumes: `AttackType`.
- Produces: `TestCase.attack_type: AttackType`, `Finding.attack_type: AttackType`. (Structural types stay dataclasses; only the field type changes. `InjectionPoint.attack_types` stays a `tuple` — its *contents* become `AttackType` in Task 3.)

- [ ] **Step 1: Update the type annotations**

In `penpine/attack/models.py`, add the import at the top (after `from enum import IntEnum`):

```python
from penpine.attack.types import AttackType
```

Change `TestCase.attack_type` annotation from `attack_type: str` to:

```python
    attack_type: AttackType
```

Change `Finding.attack_type` annotation from `attack_type: str` to:

```python
    attack_type: AttackType
```

- [ ] **Step 2: Update the model tests**

In `tests/attack/test_models.py`, wherever a `TestCase(...)` or `Finding(...)` is constructed with a string attack type (e.g. `attack_type="sqli"` or a positional `"sqli"`), change it to the enum (`attack_type=AttackType.SQLI`, etc.) and add `from penpine.attack.types import AttackType`. Update any assertion comparing `.attack_type` to a string so it compares to the `AttackType` member.

- [ ] **Step 3: Run the model tests**

Run: `pytest tests/attack/test_models.py -v`
Expected: PASS (all model tests green with typed attack_type).

- [ ] **Step 4: Commit**

```bash
git add penpine/attack/models.py tests/attack/test_models.py
git commit --no-gpg-sign -m "refactor(attack): type TestCase/Finding attack_type as AttackType"
```

---

### Task 3: Migrate the analyzer to `AttackType`

**Files:**
- Modify: `penpine/attack/analyze/rules.py`, `penpine/attack/analyze/analyzer.py`, `penpine/attack/analyze/analysis.py`
- Test: `tests/attack/../core/test_candidates.py` is unaffected; update `tests/attack/` analyzer tests and any test asserting string tags.

**Interfaces:**
- Consumes: `AttackType`.
- Produces: each `ClassificationRule.match(point) -> set[AttackType]`; `analyze()` tags points with `tuple[AttackType, ...]` sorted by `.value`; `Analysis.for_attack(attack_type: AttackType)`, `Analysis.attack_types() -> set[AttackType]`.

- [ ] **Step 1: Write/adjust the failing test**

In the analyzer test file (the one exercising `analyze()` / rules — e.g. `tests/attack/test_*` or `tests/core/test_candidates.py`; locate with `grep -rl "for_attack\|attack_types" tests`), change expected string tags to `AttackType` members. Add a focused test:

```python
from penpine.attack.types import AttackType
from penpine.attack.analyze import analyze
from penpine.core.message import Request


def test_analyze_tags_points_with_attacktype_enum():
    analysis = analyze(Request.from_url("http://t/p?id=7&q=hi&next=http://e.com"))
    tags = analysis.attack_types()
    assert AttackType.SQLI in tags
    assert all(isinstance(t, AttackType) for p in analysis for t in p.attack_types)
    ids = analysis.for_attack(AttackType.SQLI)
    assert any(p.name == "id" for p in ids)
```

- [ ] **Step 2: Run it to verify it fails**

Run: `pytest tests/attack -k analyze -v` (or the located file)
Expected: FAIL — rules return strings, so `isinstance(t, AttackType)` is False / `AttackType.SQLI in tags` is False.

- [ ] **Step 3: Migrate `rules.py`**

In `penpine/attack/analyze/rules.py`, add the import at the top:

```python
from penpine.attack.types import AttackType
```

Replace every returned string-set literal in the rule `match` methods with `AttackType` members, exactly:

| Rule | Old return | New return |
|------|-----------|-----------|
| `StringContextRule` | `{"sqli", "xss"}` | `{AttackType.SQLI, AttackType.XSS}` |
| `NumericValueRule` | `{"sqli", "idor"}` | `{AttackType.SQLI, AttackType.IDOR}` |
| `IdentifierNameRule` | `{"idor", "sqli"}` | `{AttackType.IDOR, AttackType.SQLI}` |
| `UrlValueRule` | `{"ssrf", "open-redirect"}` | `{AttackType.SSRF, AttackType.OPEN_REDIRECT}` |
| `RedirectNameRule` | `{"open-redirect", "ssrf"}` | `{AttackType.OPEN_REDIRECT, AttackType.SSRF}` |
| `FileNameOrPathRule` | `{"path-traversal", "lfi"}` | `{AttackType.PATH_TRAVERSAL, AttackType.LFI}` |
| `PathSegmentRule` | `{"path-traversal", "idor"}` | `{AttackType.PATH_TRAVERSAL, AttackType.IDOR}` |
| `HostHeaderRule` | `{"host-header", "ssrf"}` | `{AttackType.HOST_HEADER, AttackType.SSRF}` |
| `ProxyHeaderRule` | `{"ssrf", "header-injection"}` | `{AttackType.SSRF, AttackType.HEADER_INJECTION}` |
| `SearchNameRule` | `{"xss", "sqli"}` | `{AttackType.XSS, AttackType.SQLI}` |

Leave the empty-`set()` returns as-is.

- [ ] **Step 4: Migrate `analyzer.py` (sort by value — enums are not orderable)**

In `penpine/attack/analyze/analyzer.py`, change:

```python
        points.append(dataclasses.replace(base, attack_types=tuple(sorted(tags))))
```
to:

```python
        points.append(
            dataclasses.replace(base, attack_types=tuple(sorted(tags, key=lambda t: t.value)))
        )
```

- [ ] **Step 5: Migrate `analysis.py` type hints**

In `penpine/attack/analyze/analysis.py`, update the annotation on `for_attack` from `attack_type: str` to `attack_type: "AttackType"` and add a `TYPE_CHECKING` import (or a plain import at top):

```python
from penpine.attack.types import AttackType
```
and change the signature to `def for_attack(self, attack_type: AttackType) -> list:`. The body (`attack_type in p.attack_types`) is unchanged. `attack_types(self)` now returns a `set[AttackType]` — no code change, just the contents.

- [ ] **Step 6: Run the analyzer tests**

Run: `pytest tests/attack -k "analyze or candidate" -v` and the focused test from Step 1.
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add penpine/attack/analyze/ tests/
git commit --no-gpg-sign -m "refactor(attack): analyzer tags points with AttackType"
```

---

### Task 4: Migrate modules + registry to `AttackType`

**Files:**
- Modify: `penpine/attack/module.py`, `penpine/attack/registry.py`, `penpine/attack/modules/sqli.py`, `xss.py`, `traversal.py`, `redirect.py`, `differential.py`
- Test: `tests/attack/test_module.py`, `tests/attack/test_registry.py`, and each module test

**Interfaces:**
- Consumes: `AttackType`.
- Produces:
  - `AttackModule.__init__(..., attack_type: AttackType, ...)` — new required-ish field (keyword with no default is fine since all call sites are updated here). Stored as `self.attack_type`.
  - `DifferentialModule.attack_type: AttackType` class attribute; `select_attack_type` is REMOVED (unified into `attack_type`).
  - Each built-in module declares its `attack_type`. Findings/TestCases use `AttackType`.
  - `registry.by_type(attack_type: AttackType, *, signature_only: bool = False) -> list` — registered modules whose `attack_type == attack_type`, optionally excluding `probe`-based ones.

- [ ] **Step 1: Write the failing tests**

Add to `tests/attack/test_registry.py`:

```python
from penpine.attack.types import AttackType
from penpine.attack import registry
from penpine.attack.modules import register_builtins


def test_by_type_signature_only_excludes_probe_modules():
    registry.clear()
    register_builtins()
    sig = registry.by_type(AttackType.SQLI, signature_only=True)
    assert [m.name for m in sig] == ["sqli"]           # only the error-based module
    allsqli = {m.name for m in registry.by_type(AttackType.SQLI)}
    assert {"sqli", "sqli-boolean", "sqli-time"} <= allsqli
    registry.clear()
```

Add to `tests/attack/test_module.py` (or wherever `AttackModule` is unit-tested):

```python
from penpine.attack.types import AttackType


def test_attack_module_stores_attack_type():
    from penpine.attack.modules.sqli import SQLI_MODULE
    assert SQLI_MODULE.attack_type is AttackType.SQLI
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/attack/test_registry.py::test_by_type_signature_only_excludes_probe_modules tests/attack/test_module.py -v`
Expected: FAIL — `registry.by_type` missing; `AttackModule` has no `attack_type`.

- [ ] **Step 3: Add `attack_type` to `AttackModule`**

In `penpine/attack/module.py`, add `attack_type` to `__init__` (place it before `generator` so call sites read naturally, OR keyword — choose keyword to avoid reordering positional call sites). Use keyword-only:

```python
    def __init__(
        self,
        name: str,
        generator: PayloadGenerator,
        validator: Validator,
        *,
        attack_type,
        applies_to: tuple = (),
        description: str = "",
    ):
        self.name = name
        self.generator = generator
        self.validator = validator
        self.attack_type = attack_type
        self.applies_to = tuple(applies_to)
        self.description = description
```

- [ ] **Step 4: Add `registry.by_type`**

In `penpine/attack/registry.py`, add:

```python
def by_type(attack_type, *, signature_only: bool = False) -> list:
    mods = [m for m in _REGISTRY.values() if getattr(m, "attack_type", None) == attack_type]
    if signature_only:
        mods = [m for m in mods if not hasattr(m, "probe")]
    return mods
```

- [ ] **Step 5: Migrate the signature modules**

In each of `sqli.py`, `xss.py`, `traversal.py`, `redirect.py`:
- add `from penpine.attack.types import AttackType`;
- in the generator's `yield TestCase(...)`, change `attack_type="sqli"` (etc.) to the enum member (`attack_type=AttackType.SQLI`, `AttackType.XSS`, `AttackType.PATH_TRAVERSAL`, `AttackType.OPEN_REDIRECT`);
- in the validator's `Finding(...)`, change the attack-type argument (first positional string, e.g. `Finding("sqli", ...)`) to the enum (`Finding(AttackType.SQLI, ...)`);
- in the `AttackModule(...)` construction, add `attack_type=AttackType.SQLI` (resp. XSS / PATH_TRAVERSAL / OPEN_REDIRECT) as a keyword argument.

Exact per file:
- `sqli.py`: `SqliGenerator` → `attack_type=AttackType.SQLI`; `SqliValidator` `Finding(AttackType.SQLI, ...)`; `SQLI_MODULE = AttackModule("sqli", SqliGenerator(), SqliValidator(), attack_type=AttackType.SQLI, applies_to=(...), description=...)`.
- `xss.py`: `attack_type=AttackType.XSS` in the TestCase; `Finding(AttackType.XSS, ...)`; `XSS_MODULE` gets `attack_type=AttackType.XSS`.
- `traversal.py`: TestCase currently uses `attack_type="path-traversal"` → `AttackType.PATH_TRAVERSAL`; `Finding(...)` first arg → `AttackType.PATH_TRAVERSAL`; module gets `attack_type=AttackType.PATH_TRAVERSAL`.
- `redirect.py`: `attack_type="open-redirect"` → `AttackType.OPEN_REDIRECT`; `Finding(...)` → `AttackType.OPEN_REDIRECT`; module gets `attack_type=AttackType.OPEN_REDIRECT`.

- [ ] **Step 6: Migrate the differential modules**

In `penpine/attack/modules/differential.py`:
- add `from penpine.attack.types import AttackType`;
- on `DifferentialModule`, replace the class attribute `select_attack_type: str | None = None` with `attack_type = None`;
- on `BooleanSqliModule` and `TimeSqliModule`, replace `select_attack_type = "sqli"` with `attack_type = AttackType.SQLI`;
- in each `Finding(attack_type="sqli-boolean", ...)` / `Finding(attack_type="sqli-time", ...)`, change the value to `attack_type=AttackType.SQLI` (the boolean/time distinction already lives in `payload=Payload(..., technique="boolean-blind"/"time-blind")`, so no information is lost).

- [ ] **Step 7: Run the module + registry tests**

Run: `pytest tests/attack/test_module.py tests/attack/test_registry.py tests/attack/test_results.py -v` and each module test (`pytest tests/attack -k "sqli or xss or traversal or redirect or differential" -v`).
Expected: PASS (update any test still asserting a string attack_type to the `AttackType` member as you go).

- [ ] **Step 8: Commit**

```bash
git add penpine/attack/module.py penpine/attack/registry.py penpine/attack/modules/ tests/attack/
git commit --no-gpg-sign -m "refactor(attack): modules declare typed attack_type; add registry.by_type"
```

---

### Task 5: Migrate the `Runner`

**Files:**
- Modify: `penpine/attack/runner.py`
- Test: `tests/attack/test_runner.py`, `test_runner_sync.py`, `test_runner_integration.py`, `test_runner_differential.py`, `test_runner_coverage.py`

**Interfaces:**
- Consumes: `AttackType`, `registry.by_type`, module `attack_type`.
- Produces: `Runner.run(request, *, attack: AttackType | None = None, module=None, test_cases=None, points=None, validator=None, sender=None)`:
  - `module=` may be an `AttackModule`/`DifferentialModule` **instance or class** (a class is instantiated no-arg).
  - `attack=` is an `AttackType`; it resolves to `registry.by_type(attack, signature_only=True)` (all signature modules of that category) — differential modules are opt-in via `module=`.
  - Runs each resolved module (probe path if it has `probe`, else generate→send→validate with that module's validator), aggregating all attempts into one `Report`. The explicit `test_cases=`/`validator=` path (no module) is unchanged.
  - Point selection uses each module's `attack_type`.

- [ ] **Step 1: Update/write the failing tests**

In `tests/attack/test_runner.py`, migrate existing calls `run(req, attack="sqli")` → `run(req, attack=AttackType.SQLI)` (add the import). Add these two concrete tests (they use the existing `tests/attack/_fakes.py` `FakeSender` and the module registry):

```python
from penpine.attack import registry
from penpine.attack.modules import register_builtins
from penpine.attack.modules.differential import BooleanSqliModule
from penpine.attack.runner import Runner
from penpine.attack.types import AttackType
from penpine.core.message import Request
from tests.attack._fakes import FakeSender


async def test_run_by_category_uses_signature_module_not_differential():
    registry.clear()
    register_builtins()
    try:
        sender = FakeSender([b"HTTP/1.1 200 OK\r\nContent-Length: 8\r\n\r\nbaseline"])
        req = Request.from_url("http://t/item?q=hello")  # 'q' -> sqli candidate
        report = await Runner(sender=sender).run(req, attack=AttackType.SQLI)
        assert report.summary()["sent"] > 0
        # only the error-based signature module ran; no blind/differential probes
        techniques = {a.test_case.payload.technique for a in report}
        assert techniques == {"error-based"}
    finally:
        registry.clear()


async def test_run_accepts_a_module_class_and_instantiates_it():
    sender = FakeSender([b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nok"])
    req = Request.from_url("http://t/item?id=7")  # 'id' -> sqli candidate
    # pass the CLASS, not an instance — the Runner must instantiate it (probe path)
    report = await Runner(sender=sender).run(req, module=BooleanSqliModule)
    assert report.summary()["sent"] == 1  # one point ('id') probed, ran without error
    assert report.attack_type is AttackType.SQLI
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/attack/test_runner.py -v`
Expected: FAIL — string `attack="sqli"` no longer resolves (registry lookup by name is replaced), and the new tests reference not-yet-existing behavior.

- [ ] **Step 3: Rewrite `Runner` resolution + run loop**

Replace `_resolve_module` with `_resolve_modules` and rewrite `run` in `penpine/attack/runner.py`. Add the import `from penpine.attack.types import AttackType` and `from penpine.attack.registry import by_type as _registry_by_type`.

```python
    def _resolve_modules(self, attack, module):
        if module is not None:
            mod = module() if isinstance(module, type) else module
            return [mod]
        if attack is not None:
            return _registry_by_type(attack, signature_only=True)
        return []

    async def run(
        self,
        request,
        *,
        attack=None,
        module=None,
        test_cases=None,
        points=None,
        validator=None,
        sender=None,
    ):
        active_sender = sender if sender is not None else self._sender

        # Explicit test-cases path (no module).
        if test_cases is not None:
            cases = list(test_cases)
            baseline = await self._baseline(request, active_sender)
            attempts = await self._run_cases(request, cases, validator, baseline, active_sender)
            return Report(request=request, attack_type=None, baseline=baseline, attempts=attempts)

        modules = self._resolve_modules(attack, module)
        if not modules:
            raise AttackConfigError("run() requires one of attack=, module=, or test_cases=")

        baseline = await self._baseline(request, active_sender)
        attack_type = attack if attack is not None else (
            modules[0].attack_type if len(modules) == 1 else None
        )

        attempts = []
        for mod in modules:
            selected = self._select_points(request, mod, mod.attack_type, points)
            if hasattr(mod, "probe"):
                attempts += await self._run_probes(request, selected, mod, baseline, active_sender)
            else:
                cases = []
                for point in selected:
                    cases.extend(mod.generate(point, request))
                attempts += await self._run_cases(
                    request, cases, mod.validator, baseline, active_sender
                )

        return Report(
            request=request, attack_type=attack_type, baseline=baseline, attempts=attempts
        )

    async def _baseline(self, request, sender):
        if not self._capture_baseline:
            return None
        try:
            return await sender.send(request)
        except Exception:
            return None

    async def _run_cases(self, request, cases, validator, baseline, sender):
        semaphore = asyncio.Semaphore(self._max_concurrency)

        async def _bounded(tc):
            async with semaphore:
                return await self._attempt(request, tc, validator, baseline, sender)

        return list(await asyncio.gather(*(_bounded(tc) for tc in cases)))

    async def _run_probes(self, request, points, module, baseline, sender):
        semaphore = asyncio.Semaphore(self._max_concurrency)

        async def _bounded(point):
            async with semaphore:
                return await self._probe_attempt(request, point, module, baseline, sender)

        return list(await asyncio.gather(*(_bounded(p) for p in points)))
```

Keep `_select_points`, `_attempt`, `_probe_attempt`, `_ensure_loop`, `run_sync`, `close`, `__enter__`, `__exit__` — with one change in `_probe_attempt`: the placeholder `TestCase` uses the module's typed category, so change `attack_type=module.name` to `attack_type=module.attack_type`:

```python
        placeholder = TestCase(
            point=point, payload=Payload("<differential>"), attack_type=module.attack_type
        )
```

Delete the now-unused `from penpine.attack.registry import get as _registry_get` import if nothing else uses it, and update the `run` docstring to describe the typed `attack=`/`module=` contract.

- [ ] **Step 4: Run the runner tests**

Run: `pytest tests/attack/test_runner.py tests/attack/test_runner_sync.py tests/attack/test_runner_integration.py tests/attack/test_runner_differential.py tests/attack/test_runner_coverage.py -v`
Expected: PASS (migrate any remaining `attack="..."` string calls to `AttackType` as you hit them).

- [ ] **Step 5: Commit**

```bash
git add penpine/attack/runner.py tests/attack/
git commit --no-gpg-sign -m "refactor(attack): Runner selects by AttackType; category runs signature modules"
```

---

### Task 6: Public exports + full regression

**Files:**
- Modify: `penpine/attack/__init__.py`, `penpine/__init__.py`
- Test: `tests/attack/test_public_api.py`, whole suite

**Interfaces:**
- Produces: `AttackType` re-exported from `penpine.attack` (and its `__all__`); optionally `penpine.AttackType` at top level.

- [ ] **Step 1: Write the failing test**

Add to `tests/attack/test_public_api.py`:

```python
def test_attacktype_is_exported():
    import penpine.attack as A
    from penpine.attack.types import AttackType
    assert A.AttackType is AttackType
    assert "AttackType" in A.__all__


def test_attacktype_top_level():
    import penpine
    from penpine.attack.types import AttackType
    assert penpine.AttackType is AttackType
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/attack/test_public_api.py -k attacktype -v`
Expected: FAIL — `AttackType` not exported.

- [ ] **Step 3: Wire the exports**

In `penpine/attack/__init__.py`, add `from penpine.attack.types import AttackType` near the other imports and add `"AttackType"` to `__all__`.

In `penpine/__init__.py`, add `from penpine.attack.types import AttackType` and append `"AttackType"` to `__all__`.

- [ ] **Step 4: Run the export tests + whole suite**

Run: `pytest tests/attack/test_public_api.py -k attacktype -v`
Expected: PASS.

Run: `pytest -q`
Expected: whole suite passes (fix any remaining string-attack-type call sites in tests surfaced here — they should all be migrated).

Run: `ruff check . && ruff format --check . && mypy penpine`
Expected: ruff clean; mypy advisory (no new errors from the typed migration).

- [ ] **Step 5: Commit**

```bash
git add penpine/attack/__init__.py penpine/__init__.py tests/attack/test_public_api.py
git commit --no-gpg-sign -m "feat(attack): export AttackType; complete typed-vocabulary migration"
```

---

## Notes for the implementer

- **Two vocabularies stay distinct:** `AttackType` = category (closed, typed); `module.name` = module identity (string, registry key). A module maps to exactly one category via `attack_type`.
- **`Finding.attack_type` is now the category**, not the module name. Differential findings become `AttackType.SQLI` (was `"sqli-boolean"`/`"sqli-time"`); the technique survives in `payload.technique`.
- **`select_attack_type` is gone** — unified into `attack_type` on differential modules; the Runner's probe-path point selection uses `module.attack_type`.
- **Category selection runs signature modules only** (`by_type(..., signature_only=True)`), preserving "nothing blind runs automatically." Blind/differential modules are explicit `module=` (instance or class).
- As you migrate, some existing tests assert string attack types — update each to the `AttackType` member in the same task that breaks it, so every task ends green.
