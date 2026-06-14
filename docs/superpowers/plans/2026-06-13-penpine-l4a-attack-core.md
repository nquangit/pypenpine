# Penpine L4a — Attack Core & Contracts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build L4a of Penpine — the attack framework's core data model (`InjectionPoint`/`Payload`/`TestCase`/`Finding`/`Confidence`), plugin contracts (`PayloadGenerator`/`Validator` ABCs), `AttackModule`, a name `registry`, and an `EchoModule` example proving the contracts compose.

**Architecture:** Pure, network-free contracts that L4b (analyzer), L4c (runner), and L4d (modules) build on. Frozen dataclasses for the model; ABCs for the two plugin points; a module-global registry with duplicate protection; one trivial reflection-detecting example module. Depends only on L0.

**Tech Stack:** Python 3.11+, stdlib `dataclasses`/`enum`/`abc`/`secrets`, `pytest`. Depends on L0–L3 (on `main`); only L0 is used here.

---

## File Structure

```
penpine/attack/
  __init__.py     # public exports
  exceptions.py   # AttackError hierarchy
  models.py       # InjectionPoint, Payload, TestCase, Finding, Confidence
  generator.py    # PayloadGenerator ABC
  validator.py    # Validator ABC
  module.py       # AttackModule
  registry.py     # register / get / list_modules / unregister / clear
  example.py      # EchoModule
tests/attack/
  ... mirrors the above
```

Build order: scaffolding → exceptions → models → contracts → AttackModule → registry → example + public API.

---

## Task 0: Scaffolding

**Files:**
- Create: `penpine/attack/__init__.py`, `tests/attack/__init__.py`

- [ ] **Step 1: Create empty package inits**

Create empty files: `penpine/attack/__init__.py`, `tests/attack/__init__.py`.

- [ ] **Step 2: Verify suite still green**

Run: `python -m pytest -q`
Expected: `204 passed` (L0–L3 unaffected).

- [ ] **Step 3: Commit**

```bash
git add penpine/attack tests/attack
git commit -c commit.gpgsign=false -m "chore: scaffold L4a attack package"
```

---

## Task 1: Exceptions

**Files:**
- Create: `penpine/attack/exceptions.py`
- Test: `tests/attack/test_exceptions.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/attack/test_exceptions.py
from penpine.exceptions import PenpineError
from penpine.attack.exceptions import AttackError, AttackConfigError


def test_hierarchy():
    assert issubclass(AttackConfigError, AttackError)
    assert issubclass(AttackError, PenpineError)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/attack/test_exceptions.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Write minimal implementation**

```python
# penpine/attack/exceptions.py
"""Attack-layer exceptions."""
from __future__ import annotations

from penpine.exceptions import PenpineError


class AttackError(PenpineError):
    """Base class for attack-framework failures."""


class AttackConfigError(AttackError):
    """Unknown/duplicate module or invalid module configuration."""
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/attack/test_exceptions.py -v`
Expected: PASS (1 passed).

- [ ] **Step 5: Commit**

```bash
git add penpine/attack/exceptions.py tests/attack/test_exceptions.py
git commit -c commit.gpgsign=false -m "feat: add attack exception hierarchy"
```

---

## Task 2: Data model

**Files:**
- Create: `penpine/attack/models.py`
- Test: `tests/attack/test_models.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/attack/test_models.py
from penpine.core.message import Request
from penpine.attack.models import (
    InjectionPoint, Payload, TestCase, Finding, Confidence,
)


def test_from_locator_param():
    loc = Request.from_url("http://h/p?a=1").locate("param:a")
    point = InjectionPoint.from_locator(loc)
    assert point.expr == "param:a"
    assert point.kind == "param"
    assert point.name == "a"
    assert point.value == "1"
    assert point.attack_types == ()


def test_from_locator_request_line_kind():
    loc = Request.from_url("http://h/p").locate("method")
    point = InjectionPoint.from_locator(loc)
    assert point.expr == "method"
    assert point.kind == "method"
    assert point.name == ""
    assert point.value == "GET"


def test_from_locator_json():
    req = Request.from_raw(
        b'POST / HTTP/1.1\r\nHost: h\r\nContent-Type: application/json\r\n'
        b'Content-Length: 13\r\n\r\n{"user":"ann"}')
    loc = req.locate("json:$.user")
    point = InjectionPoint.from_locator(loc)
    assert point.expr == "json:$.user"
    assert point.kind == "json"


def test_payload_and_testcase_defaults():
    p = Payload("' OR 1=1--", technique="boolean")
    assert p.value == "' OR 1=1--"
    assert p.technique == "boolean"
    assert p.meta == {}
    point = InjectionPoint("param:a", "param", "a", "1")
    tc = TestCase(point=point, payload=p, attack_type="sqli")
    assert tc.request is None
    assert tc.marker is None
    assert tc.meta == {}


def test_confidence_ordering():
    assert Confidence.HIGH > Confidence.LOW
    assert Confidence.MEDIUM == Confidence(2)


def test_finding_defaults():
    point = InjectionPoint("param:a", "param", "a", "1")
    f = Finding(attack_type="sqli", point=point, payload=Payload("x"),
                confidence=Confidence.HIGH, evidence="sql error in body")
    assert f.request is None
    assert f.response is None
    assert f.meta == {}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/attack/test_models.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Write minimal implementation**

```python
# penpine/attack/models.py
"""Attack-framework data model. Pure data, no network."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum

_REQUEST_LINE_KINDS = {"method", "target", "version"}


@dataclass(frozen=True)
class InjectionPoint:
    expr: str                              # locator expression, e.g. "param:id"
    kind: str
    name: str = ""
    value: object = None
    attack_types: tuple = ()               # filled by the L4b analyzer

    @classmethod
    def from_locator(cls, loc) -> "InjectionPoint":
        kind = loc.kind
        name = getattr(loc, "name", "") or ""
        expr = kind if kind in _REQUEST_LINE_KINDS else f"{kind}:{name}"
        return cls(expr=expr, kind=kind, name=name, value=getattr(loc, "value", None))


@dataclass(frozen=True)
class Payload:
    value: str
    technique: str = ""
    meta: dict = field(default_factory=dict)


@dataclass(frozen=True)
class TestCase:
    point: InjectionPoint
    payload: Payload
    attack_type: str
    request: object | None = None          # generator-built request; else runner builds via replace_at
    marker: str | None = None
    meta: dict = field(default_factory=dict)


class Confidence(IntEnum):
    LOW = 1
    MEDIUM = 2
    HIGH = 3


@dataclass
class Finding:
    attack_type: str
    point: InjectionPoint
    payload: Payload
    confidence: Confidence
    evidence: str
    request: object | None = None
    response: object | None = None
    meta: dict = field(default_factory=dict)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/attack/test_models.py -v`
Expected: PASS (6 passed).

- [ ] **Step 5: Commit**

```bash
git add penpine/attack/models.py tests/attack/test_models.py
git commit -c commit.gpgsign=false -m "feat: add attack data model (point/payload/testcase/finding)"
```

---

## Task 3: Plugin contracts (ABCs)

**Files:**
- Create: `penpine/attack/generator.py`, `penpine/attack/validator.py`
- Test: `tests/attack/test_contracts.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/attack/test_contracts.py
import pytest

from penpine.attack.generator import PayloadGenerator
from penpine.attack.validator import Validator
from penpine.attack.models import InjectionPoint, Payload, TestCase, Finding, Confidence


def test_abcs_cannot_be_instantiated():
    with pytest.raises(TypeError):
        PayloadGenerator()
    with pytest.raises(TypeError):
        Validator()


def test_concrete_generator_and_validator_work():
    point = InjectionPoint("param:a", "param", "a", "1")

    class G(PayloadGenerator):
        def generate(self, point, request):
            yield TestCase(point=point, payload=Payload("X"), attack_type="t")

    class V(Validator):
        def evaluate(self, test_case, response, baseline):
            return Finding(attack_type="t", point=test_case.point,
                           payload=test_case.payload, confidence=Confidence.LOW,
                           evidence="ok")

    cases = list(G().generate(point, object()))
    assert len(cases) == 1 and cases[0].attack_type == "t"
    finding = V().evaluate(cases[0], object(), None)
    assert finding.confidence == Confidence.LOW
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/attack/test_contracts.py -v`
Expected: FAIL — modules missing.

- [ ] **Step 3: Write minimal implementation**

```python
# penpine/attack/generator.py
"""PayloadGenerator contract: point-aware, yields TestCases."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Iterable

from penpine.attack.models import InjectionPoint, TestCase


class PayloadGenerator(ABC):
    @abstractmethod
    def generate(self, point: InjectionPoint, request) -> Iterable[TestCase]:
        """Yield TestCases for this injection point on this base request."""
        raise NotImplementedError
```

```python
# penpine/attack/validator.py
"""Validator contract: judges an attack response against an optional baseline."""
from __future__ import annotations

from abc import ABC, abstractmethod

from penpine.attack.models import TestCase, Finding


class Validator(ABC):
    @abstractmethod
    def evaluate(self, test_case: TestCase, response, baseline) -> "Finding | None":
        """Return a Finding if the attack succeeded, else None.

        `baseline` is the unmodified request's response (may be None).
        """
        raise NotImplementedError
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/attack/test_contracts.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add penpine/attack/generator.py penpine/attack/validator.py tests/attack/test_contracts.py
git commit -c commit.gpgsign=false -m "feat: add PayloadGenerator and Validator contracts"
```

---

## Task 4: AttackModule

**Files:**
- Create: `penpine/attack/module.py`
- Test: `tests/attack/test_module.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/attack/test_module.py
from penpine.attack.module import AttackModule
from penpine.attack.generator import PayloadGenerator
from penpine.attack.validator import Validator
from penpine.attack.models import InjectionPoint, Payload, TestCase, Finding, Confidence


class G(PayloadGenerator):
    def generate(self, point, request):
        yield TestCase(point=point, payload=Payload("X"), attack_type="t")


class V(Validator):
    def evaluate(self, test_case, response, baseline):
        return Finding(attack_type="t", point=test_case.point,
                       payload=test_case.payload, confidence=Confidence.HIGH,
                       evidence="hit")


def test_module_delegates_generate_and_evaluate():
    m = AttackModule("t", G(), V())
    point = InjectionPoint("param:a", "param", "a", "1")
    cases = list(m.generate(point, object()))
    assert len(cases) == 1
    finding = m.evaluate(cases[0], object())     # baseline defaults to None
    assert finding.confidence == Confidence.HIGH


def test_applies_to_filter():
    m = AttackModule("t", G(), V(), applies_to=("param", "json"))
    assert m.applies("param") is True
    assert m.applies("header") is False
    # empty applies_to -> applies to all
    assert AttackModule("u", G(), V()).applies("anything") is True


def test_metadata():
    m = AttackModule("t", G(), V(), applies_to=("param",), description="desc")
    assert m.name == "t"
    assert m.applies_to == ("param",)
    assert m.description == "desc"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/attack/test_module.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Write minimal implementation**

```python
# penpine/attack/module.py
"""AttackModule: bundles a generator + validator + metadata."""
from __future__ import annotations

from penpine.attack.generator import PayloadGenerator
from penpine.attack.validator import Validator


class AttackModule:
    def __init__(self, name: str, generator: PayloadGenerator, validator: Validator,
                 *, applies_to: tuple = (), description: str = ""):
        self.name = name
        self.generator = generator
        self.validator = validator
        self.applies_to = tuple(applies_to)
        self.description = description

    def generate(self, point, request):
        return self.generator.generate(point, request)

    def evaluate(self, test_case, response, baseline=None):
        return self.validator.evaluate(test_case, response, baseline)

    def applies(self, kind: str) -> bool:
        return not self.applies_to or kind in self.applies_to
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/attack/test_module.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add penpine/attack/module.py tests/attack/test_module.py
git commit -c commit.gpgsign=false -m "feat: add AttackModule bundling generator+validator"
```

---

## Task 5: Registry

**Files:**
- Create: `penpine/attack/registry.py`
- Test: `tests/attack/test_registry.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/attack/test_registry.py
import pytest

from penpine.attack import registry
from penpine.attack.module import AttackModule
from penpine.attack.generator import PayloadGenerator
from penpine.attack.validator import Validator
from penpine.attack.exceptions import AttackConfigError


class G(PayloadGenerator):
    def generate(self, point, request):
        return []


class V(Validator):
    def evaluate(self, test_case, response, baseline):
        return None


@pytest.fixture(autouse=True)
def _clean_registry():
    registry.clear()
    yield
    registry.clear()


def module(name):
    return AttackModule(name, G(), V())


def test_register_and_get():
    m = module("sqli")
    registry.register(m)
    assert registry.get("sqli") is m


def test_get_unknown_raises():
    with pytest.raises(AttackConfigError):
        registry.get("nope")


def test_duplicate_raises_unless_replace():
    registry.register(module("sqli"))
    with pytest.raises(AttackConfigError):
        registry.register(module("sqli"))
    replacement = module("sqli")
    registry.register(replacement, replace=True)
    assert registry.get("sqli") is replacement


def test_list_and_unregister_and_clear():
    registry.register(module("a"))
    registry.register(module("b"))
    assert registry.list_modules() == ["a", "b"]
    registry.unregister("a")
    assert registry.list_modules() == ["b"]
    registry.clear()
    assert registry.list_modules() == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/attack/test_registry.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Write minimal implementation**

```python
# penpine/attack/registry.py
"""Module-global registry of attack modules, selectable by name."""
from __future__ import annotations

from penpine.attack.exceptions import AttackConfigError
from penpine.attack.module import AttackModule

_REGISTRY: dict[str, AttackModule] = {}


def register(module: AttackModule, *, replace: bool = False) -> None:
    if module.name in _REGISTRY and not replace:
        raise AttackConfigError(f"attack module already registered: {module.name!r}")
    _REGISTRY[module.name] = module


def get(name: str) -> AttackModule:
    try:
        return _REGISTRY[name]
    except KeyError:
        raise AttackConfigError(f"unknown attack module: {name!r}") from None


def unregister(name: str) -> None:
    _REGISTRY.pop(name, None)


def list_modules() -> list:
    return sorted(_REGISTRY)


def clear() -> None:
    _REGISTRY.clear()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/attack/test_registry.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add penpine/attack/registry.py tests/attack/test_registry.py
git commit -c commit.gpgsign=false -m "feat: add attack module registry"
```

---

## Task 6: EchoModule + public API

**Files:**
- Create: `penpine/attack/example.py`
- Modify: `penpine/attack/__init__.py`
- Test: `tests/attack/test_example.py`, `tests/attack/test_public_api.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/attack/test_example.py
import pytest

from penpine.core.message import Request
from penpine.core.parse.http_parser import parse_response
from penpine.attack import registry
from penpine.attack.example import EchoGenerator, EchoValidator, ECHO_MODULE
from penpine.attack.models import InjectionPoint


@pytest.fixture(autouse=True)
def _clean_registry():
    registry.clear()
    yield
    registry.clear()


def point():
    loc = Request.from_url("http://h/p?a=1").locate("param:a")
    return InjectionPoint.from_locator(loc)


def test_generator_yields_marked_testcase():
    cases = list(EchoGenerator().generate(point(), object()))
    assert len(cases) == 1
    tc = cases[0]
    assert tc.attack_type == "echo"
    assert tc.marker and tc.marker == tc.payload.value
    assert tc.marker.startswith("PENPINE_ECHO_")


def test_validator_detects_reflection():
    cases = list(EchoGenerator().generate(point(), object()))
    tc = cases[0]
    reflecting = parse_response(
        b"HTTP/1.1 200 OK\r\nContent-Length: %d\r\n\r\n%s"
        % (len(tc.marker), tc.marker.encode()))
    finding = EchoValidator().evaluate(tc, reflecting, None)
    assert finding is not None
    assert finding.attack_type == "echo"
    assert finding.confidence.name == "HIGH"
    assert finding.response is reflecting


def test_validator_no_reflection_returns_none():
    cases = list(EchoGenerator().generate(point(), object()))
    not_reflecting = parse_response(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nok")
    assert EchoValidator().evaluate(cases[0], not_reflecting, None) is None


def test_echo_module_round_trip_via_registry():
    registry.register(ECHO_MODULE)
    m = registry.get("echo")
    assert m.applies("param") is True
    tc = list(m.generate(point(), object()))[0]
    reflecting = parse_response(
        b"HTTP/1.1 200 OK\r\nContent-Length: %d\r\n\r\n%s"
        % (len(tc.marker), tc.marker.encode()))
    assert m.evaluate(tc, reflecting) is not None
```

```python
# tests/attack/test_public_api.py
from penpine.attack import (
    InjectionPoint, Payload, TestCase, Finding, Confidence,
    PayloadGenerator, Validator, AttackModule,
    register, get, list_modules, unregister, clear,
    ECHO_MODULE, AttackError, AttackConfigError,
)


def test_public_exports_exist():
    assert all([InjectionPoint, Payload, TestCase, Finding, Confidence,
                PayloadGenerator, Validator, AttackModule,
                register, get, list_modules, unregister, clear,
                ECHO_MODULE, AttackError, AttackConfigError])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/attack/test_example.py tests/attack/test_public_api.py -v`
Expected: FAIL — example module / exports missing.

- [ ] **Step 3: Write minimal implementation**

```python
# penpine/attack/example.py
"""EchoModule: a trivial reflection-detecting module proving the contracts."""
from __future__ import annotations

import secrets

from penpine.attack.generator import PayloadGenerator
from penpine.attack.validator import Validator
from penpine.attack.module import AttackModule
from penpine.attack.models import Payload, TestCase, Finding, Confidence


class EchoGenerator(PayloadGenerator):
    def generate(self, point, request):
        marker = f"PENPINE_ECHO_{secrets.token_hex(4)}"
        yield TestCase(point=point, payload=Payload(marker, technique="echo"),
                       attack_type="echo", marker=marker)


class EchoValidator(Validator):
    def evaluate(self, test_case, response, baseline=None):
        if test_case.marker and test_case.marker.encode() in response.body.raw:
            return Finding(attack_type="echo", point=test_case.point,
                           payload=test_case.payload, confidence=Confidence.HIGH,
                           evidence="marker reflected in response body",
                           request=test_case.request, response=response)
        return None


ECHO_MODULE = AttackModule("echo", EchoGenerator(), EchoValidator(),
                           applies_to=("param", "json", "form", "header"),
                           description="reflection echo probe")
```

```python
# penpine/attack/__init__.py
"""Penpine L4a attack core & contracts."""
from penpine.attack.models import (
    InjectionPoint, Payload, TestCase, Finding, Confidence,
)
from penpine.attack.generator import PayloadGenerator
from penpine.attack.validator import Validator
from penpine.attack.module import AttackModule
from penpine.attack.registry import (
    register, get, list_modules, unregister, clear,
)
from penpine.attack.example import EchoGenerator, EchoValidator, ECHO_MODULE
from penpine.attack.exceptions import AttackError, AttackConfigError

__all__ = [
    "InjectionPoint", "Payload", "TestCase", "Finding", "Confidence",
    "PayloadGenerator", "Validator", "AttackModule",
    "register", "get", "list_modules", "unregister", "clear",
    "EchoGenerator", "EchoValidator", "ECHO_MODULE",
    "AttackError", "AttackConfigError",
]
```

- [ ] **Step 4: Run the FULL suite**

Run: `python -m pytest -q`
Expected: PASS — all L0–L3 + L4a tests green (no failures, no errors).

- [ ] **Step 5: Commit**

```bash
git add penpine/attack/example.py penpine/attack/__init__.py tests/attack/test_example.py tests/attack/test_public_api.py
git commit -c commit.gpgsign=false -m "feat: add EchoModule example + expose L4a public API"
```

---

## Self-Review Notes (against the spec)

- **§3 module layout** → Tasks 0–6 create every listed module.
- **§4 errors** → Task 1.
- **§5 data model** (InjectionPoint+from_locator, Payload, TestCase, Confidence ordering, Finding) → Task 2.
- **§6 contracts** (PayloadGenerator/Validator ABCs, abstract + concrete) → Task 3.
- **§7 AttackModule + registry** (delegation, applies, register/get/list/unregister/clear, duplicate-raises/replace) → Tasks 4, 5.
- **§8 EchoModule** (marker generator, reflection validator, not auto-registered) → Task 6.
- **§9 testing** → test-first throughout; EchoModule end-to-end via registry in Task 6.

**Deferred (per spec §2 Non-Goals):** filling `attack_types` (L4b), the runner/baseline/concurrency (L4c), real modules (L4d). No top-level `penpine.*` exports are added for L4a (contracts only); the user-facing entry point arrives with the L4c runner.

**Note for implementers:** registry tests use an `autouse` `clear()` fixture for isolation since the registry is module-global. `InjectionPoint.from_locator` is tested against real L0 `ResolvedLocator`s (via `Request.locate(...)`), not mocks.
```
