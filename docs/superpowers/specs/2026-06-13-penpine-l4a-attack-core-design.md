# Penpine — L4a: Attack Core & Contracts (Design Spec)

**Date:** 2026-06-13
**Status:** Approved for implementation planning
**Scope:** This spec covers **L4a only** — the attack framework's core data model and plugin contracts. It is the first of four L4 sub-projects.

---

## 1. Context

L4 (the attack framework) is decomposed into four sub-projects, each its own spec→plan→build cycle:

| Sub | Name | Responsibility |
|---|---|---|
| **L4a** | **Attack core & contracts** *(this spec)* | data model + plugin contracts + one example module |
| L4b | Injection-point analyzer | classify L0 `injection_candidates` → applicable attack types |
| L4c | Runner & validation harness | analyze → generate → insert → send (L1/L2, L3 `Context`) → validate → collect `Finding`s |
| L4d | Concrete attack modules | real SQLi/XSS/etc. generators + oracles |

**Build order:** L4a → L4b → L4c → L4d.

L4a depends only on L0 (`Request`, `Response`, `ResolvedLocator`, `PenpineError`). L1–L3 are consumed by the runner (L4c), not here.

**L4a decisions (this round):**
- Generators are **point-aware** and yield `TestCase`s.
- Validators receive **`(test_case, response, baseline)`**.
- Modules are selected by a **name registry** and/or passed as **direct instances**.
- `register` raises on a duplicate name unless `replace=True`.
- The runner (L4c) guarantees `test_case.request` is the sent request before `evaluate`.

## 2. Goals & Non-Goals

**Goals**
- A small, frozen data model: `InjectionPoint`, `Payload`, `TestCase`, `Finding`, `Confidence`.
- Abstract plugin contracts: `PayloadGenerator.generate(point, request)` and `Validator.evaluate(test_case, response, baseline)`.
- `AttackModule` bundling a generator + validator + metadata (`applies_to`, `description`), subclassable.
- A module-global `registry` (register/get/list/unregister/clear) with duplicate protection.
- An `EchoModule` example proving the contracts compose end-to-end.
- Typed errors; fully unit-testable with no network.

**Non-Goals (later sub-projects)**
- Filling `InjectionPoint.attack_types` via classification (L4b).
- Building/sending requests, baseline capture, concurrency, result aggregation (L4c).
- Real attack payloads/oracles (L4d).

## 3. Module Layout

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
```

## 4. Errors

```
AttackError(PenpineError)
└── AttackConfigError   # unknown/duplicate module, invalid module spec
```

## 5. Data Model (`models.py`)

```python
@dataclass(frozen=True)
class InjectionPoint:
    expr: str                              # locator expression, e.g. "param:id"
    kind: str                              # "param" | "header" | "json" | ...
    name: str                              # param/header/field name ("" for request-line parts)
    value: object = None                   # current value at the point
    attack_types: tuple[str, ...] = ()     # filled by the L4b analyzer

    @classmethod
    def from_locator(cls, loc) -> "InjectionPoint": ...
```
`from_locator` builds `expr` from an L0 `ResolvedLocator`: for request-line kinds (`method`/`target`/`version`) `expr = loc.kind`; otherwise `expr = f"{loc.kind}:{loc.name}"`. Copies `kind`, `name`, `value`.

```python
@dataclass(frozen=True)
class Payload:
    value: str
    technique: str = ""                    # e.g. "error-based", "reflected"
    meta: dict = field(default_factory=dict)


@dataclass(frozen=True)
class TestCase:
    point: InjectionPoint
    payload: Payload
    attack_type: str
    request: "Request | None" = None       # generator-built request, else runner builds via replace_at
    marker: str | None = None              # unique token for reflection detection
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
    request: "Request | None" = None
    response: "Response | None" = None
    meta: dict = field(default_factory=dict)
```

`TestCase.request` semantics: if a generator sets it, the runner sends that request verbatim; if `None`, the runner builds the request from the base via `base.replace_at(point.expr, payload.value)`. Either way, the runner sets `test_case.request` to the actual sent request (via `dataclasses.replace`) before calling `evaluate`, so a `Finding` can reference exactly what was sent.

## 6. Plugin Contracts

```python
# generator.py
class PayloadGenerator(ABC):
    @abstractmethod
    def generate(self, point: InjectionPoint, request) -> Iterable[TestCase]:
        """Yield TestCases for this injection point on this base request."""
```

```python
# validator.py
class Validator(ABC):
    @abstractmethod
    def evaluate(self, test_case: TestCase, response, baseline) -> "Finding | None":
        """Return a Finding if the attack succeeded, else None.
        `baseline` is the unmodified request's response (may be None)."""
```

Generators are point-aware (can tailor payloads to `point.kind` / value type). Validators see the attack `response` and an optional `baseline` (enables boolean/time/length-diff oracles).

## 7. AttackModule + Registry

```python
# module.py
class AttackModule:
    def __init__(self, name: str, generator: PayloadGenerator, validator: Validator,
                 *, applies_to: tuple[str, ...] = (), description: str = ""):
        ...
    def generate(self, point, request):                 # -> Iterable[TestCase]
        return self.generator.generate(point, request)
    def evaluate(self, test_case, response, baseline=None):  # -> Finding | None
        return self.validator.evaluate(test_case, response, baseline)
    def applies(self, kind: str) -> bool:
        return not self.applies_to or kind in self.applies_to
```
`applies_to` is the set of locator kinds the module is relevant for (empty = all); `applies(kind)` is used by L4b/L4c to skip irrelevant points. `AttackModule` is subclassable for fully custom modules.

```python
# registry.py  (module-global dict)
def register(module: AttackModule, *, replace: bool = False) -> None
    # raises AttackConfigError if module.name already registered and not replace
def get(name: str) -> AttackModule
    # raises AttackConfigError if unknown
def unregister(name: str) -> None
def list_modules() -> list[str]
def clear() -> None       # test isolation
```

## 8. Example Module (`example.py`)

`EchoModule` proves the contracts compose:
- `EchoGenerator.generate(point, request)` yields a single `TestCase(point, Payload("PENPINE_ECHO_<rand>", technique="echo"), attack_type="echo", marker="PENPINE_ECHO_<rand>")` — a unique marker per call.
- `EchoValidator.evaluate(test_case, response, baseline)` returns `Finding(attack_type="echo", point, payload, Confidence.HIGH, evidence="marker reflected in response body", request=test_case.request, response=response)` when `test_case.marker.encode()` is in `response.body.raw`, else `None`.
- A module instance `ECHO_MODULE = AttackModule("echo", EchoGenerator(), EchoValidator(), applies_to=("param","json","form","header"), description="reflection echo probe")`.

It is NOT auto-registered at import (no import-time global mutation); tests/users register it explicitly.

## 9. Testing Strategy (TDD)

All unit-level, no network.

- **models:** `InjectionPoint.from_locator` builds `expr` for `param`/`json`/`header`/request-line kinds; `Payload`/`TestCase`/`Finding` construct with defaults; `Confidence` ordering (`HIGH > LOW`).
- **contracts:** `PayloadGenerator`/`Validator` cannot be instantiated directly (abstract); a concrete subclass works.
- **AttackModule:** `generate`/`evaluate` delegate to the wrapped generator/validator; `applies(kind)` (empty = all, else membership).
- **registry:** register then get; `list_modules`; `unregister`; duplicate name raises `AttackConfigError`; `replace=True` overwrites; `get` unknown raises; `clear` empties. Each test calls `clear()` (fixture) for isolation.
- **EchoModule:** generator yields a marked `TestCase`; validator returns a `HIGH` `Finding` when the marker is reflected and `None` otherwise; round-trip via `register(ECHO_MODULE)` → `get("echo")` → generate → evaluate against a synthetic reflecting `Response` (built with L0 `parse_response`).

## 10. Dependencies

- Runtime: none beyond L0 (stdlib `dataclasses`, `enum`, `abc`, `secrets`/`random` for the echo marker). Python 3.11+.
- Dev/test: `pytest`.

## 11. Forward Hooks

- L4b populates `InjectionPoint.attack_types` and emits `InjectionPoint`s from L0 candidates.
- L4c consumes `AttackModule`/`registry`, builds requests from `TestCase`s (honoring a pre-built `request` or `replace_at`), captures a baseline, sends concurrently via L1/L2 (`Identity`/`Engine`) threading L3 `Context`, sets `test_case.request`, and collects `Finding`s.
- L4d ships real `AttackModule`s registered under names like `"sqli"`, `"xss"`.
