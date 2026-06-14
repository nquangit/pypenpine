# Penpine — L4c: Runner & Validation Harness (Design Spec)

**Date:** 2026-06-13
**Status:** Approved for implementation planning
**Scope:** This spec covers **L4c only** — the attack runner that ties analysis, generation, sending, and validation together. Third of four L4 sub-projects.

---

## 1. Context

L4c is the keystone: it realizes the headline UX — *pick an attack type, the tool analyzes the request, generates the appropriate payloads, inserts them, runs them, and validates the results* — and supports bringing your own modules or test cases.

It composes every prior layer:
- L0: `Request.replace_at(expr, value)`, `Request.serialize()`, `Response`.
- L1/L2/L3: a **sender** — any object exposing `async send(request) -> Response` (`Engine`, `SessionManager`, or `Identity`).
- L4a: `registry.get`, `AttackModule` (`generate`/`evaluate`/`applies`), `TestCase`, `Finding`, `AttackConfigError`.
- L4b: `analyze(request) -> Analysis` and `Analysis.for_attack(name)`.

**L4c decisions (this round):**
- Point selection is **analyzer-guided** (`for_attack(type)` ∩ `module.applies`) with an override.
- A run returns a **full `Report`** (one `Attempt` per test case + findings).
- v1 is **single-shot** (multi-step chaining / L3 capture deferred).
- Entry point is a **`Runner` class** with `run` / `run_sync`.
- `sender` is **duck-typed** (`async send(request)`); defaults to a plain `Engine()`.
- `run()` requires one of `attack` / `module` / `test_cases`.

## 2. Goals & Non-Goals

**Goals**
- A `Runner` that, given a base request and a chosen attack (by name, module, or explicit test cases), produces a `Report`.
- Analyzer-guided point selection with explicit override.
- Concurrent, per-attempt-isolated sending via a duck-typed sender, with a captured baseline for validators.
- A full result model (`Attempt`/`Report`) with findings, errors, timing, and a summary.
- A synchronous facade.
- Fully unit-testable with fake senders (no sockets).

**Non-Goals (deferred)**
- Automatic L3 `Context` capture / multi-step chaining (user threads data between runs).
- Real attack modules / payloads (L4d).
- Persistent reporting / serialization of `Report` to disk.

## 3. Module Layout

```
penpine/attack/
  results.py    # Attempt, Report
  runner.py     # Runner
```
(Flat modules in the existing `penpine/attack/` package — no new subpackage.)

## 4. Results Model (`results.py`)

```python
@dataclass
class Attempt:
    test_case: TestCase
    request: object | None = None      # the actual sent Request (also set on test_case.request)
    response: object | None = None     # Response, or None if the send errored
    finding: object | None = None      # Finding, or None (no detection / no validator)
    error: Exception | None = None
    elapsed_ms: float | None = None

    @property
    def ok(self) -> bool:              # send (and validation) succeeded
        return self.error is None

    @property
    def found(self) -> bool:
        return self.finding is not None


@dataclass
class Report:
    request: object                    # base request
    attack_type: str | None
    baseline: object | None            # baseline Response (or None)
    attempts: list = field(default_factory=list)

    @property
    def findings(self) -> list:        # [a.finding for a in attempts if a.finding]
        ...
    @property
    def errors(self) -> list:          # [a for a in attempts if a.error]
        ...
    def summary(self) -> dict:         # {"sent": N, "failed": N, "found": N}
        ...
    def __iter__(self): ...            # iterate attempts
    def __len__(self): ...
```

## 5. Runner (`runner.py`)

```python
class Runner:
    def __init__(self, sender=None, *, max_concurrency=10, capture_baseline=True):
        # sender defaults to a plain Engine()
        ...

    async def run(self, request, *, attack=None, module=None, test_cases=None,
                  points=None, validator=None, sender=None) -> Report: ...

    def run_sync(self, request, **kwargs) -> Report: ...
    def close(self) -> None: ...
    def __enter__ / __exit__
```

`run()` algorithm:
1. **Resolve module/validator/attack_type.** `module = module or (registry.get(attack) if attack else None)`. `registry.get` raises `AttackConfigError` on an unknown name. `attack_type = attack or (module.name if module else None)`. `validator = validator or (module.validator if module else None)`.
2. **Determine test cases.** If `test_cases` is provided, use `list(test_cases)`. Else require a module (`AttackConfigError` if none) and generate:
   - **Select points:** `points` arg if given; else `analyze(request).for_attack(attack_type)`, then filter to `module.applies(p.kind)`.
   - **Generate:** `test_cases = [tc for p in selected for tc in module.generate(p, request)]`.
3. **Baseline.** If `capture_baseline`, `baseline = await _send(request, sender)`, swallowing any exception (→ `None`).
4. **Send concurrently.** Under an `asyncio.Semaphore(max_concurrency)`, run one `_attempt` per test case via `asyncio.gather` (order preserved).
5. **Report.** Return `Report(request, attack_type, baseline, attempts)`.

`_attempt(base, test_case, validator, baseline, sender)`:
1. Build the request: `test_case.request` if set, else `base.replace_at(test_case.point.expr, test_case.payload.value)`. A build error → `Attempt(error=...)`, no send.
2. Set the sent request on a copy: `sent_tc = dataclasses.replace(test_case, request=req)` (the L4a contract — validators/`Finding`s reference exactly what was sent).
3. `response = await _send(req, sender)`. A send error → `Attempt(request=req, error=..., elapsed_ms=...)`.
4. If `validator`: `finding = validator.evaluate(sent_tc, response, baseline)`. A validator error → `Attempt(request=req, response=response, error=..., ...)` (response kept).
5. Return `Attempt(test_case=sent_tc, request=req, response=response, finding=finding, elapsed_ms=...)`.

`_send(request, sender)` = `await (sender or self._sender).send(request)`.

**Per-attempt isolation:** `_attempt` never raises; all errors become an `Attempt.error`. One failing test case never aborts the batch.

**Sync facade:** `run_sync`/`close`/context manager use a lazily-started private event-loop thread (same pattern as `Engine`/`SessionManager`).

## 6. Public API

- `penpine/attack/__init__.py` re-exports `Runner`, `Report`, `Attempt`.
- `penpine/__init__.py` re-exports `Runner` (the attack entry point) and adds it to `__all__`.

## 7. Errors

- `AttackConfigError`: unknown `attack` name; `run()` called with none of `attack`/`module`/`test_cases`.
- All send/validator/build exceptions are captured per `Attempt` (`error=...`), never raised out of `run`.
- Baseline send failure is swallowed (`baseline=None`).

## 8. Testing Strategy (TDD)

All unit-level, no sockets. Senders are `FakeEngine`-style stubs exposing `async send(request)`; a **reflecting** sender echoes any `PENPINE_ECHO_*` marker found in the serialized request into the response body so `EchoModule`/`EchoValidator` produce findings.

- **results:** `Attempt.ok`/`found`; `Report.findings`/`errors`/`summary`/`len`/iter on a hand-built report.
- **happy path (analyzer-guided):** register `AttackModule("xss", EchoGenerator(), EchoValidator(), applies_to=("param",))`; `run(Request.from_url("http://h/?q=hi"), attack="xss", sender=reflecting)` → `param:q` selected (analyzer tags it xss), generated, sent, reflected → a `Finding`; `report.findings` non-empty; baseline captured.
- **no applicable points:** `run` on a request with no points tagged for the attack → `Report` with zero attempts.
- **points override:** `run(req, module=..., points=analyze(req).all())` attacks points the analyzer didn't tag.
- **bring-your-own test cases:** `run(req, test_cases=[tc], validator=v)` sends those and validates; with no validator, attempts have `finding=None` but record responses.
- **error isolation:** a sender that raises on a specific request → that `Attempt.error` is set, others succeed, `run` completes; `report.summary()["failed"] == 1`.
- **baseline to validator:** a validator asserting it received a non-None baseline.
- **unknown attack:** `run(req, attack="nope")` → `AttackConfigError`; `run(req)` (nothing) → `AttackConfigError`.
- **sync facade:** `run_sync` returns a `Report`.

## 9. Dependencies

- Runtime: none beyond L0–L4b (stdlib `asyncio`/`time`/`threading`/`dataclasses`). Python 3.11+.
- Dev/test: `pytest`, `pytest-asyncio` (configured).

## 10. Forward Hooks

- L4d ships real `AttackModule`s (sqli/xss/...) registered under names matching L4b's tag vocabulary, so `runner.run(req, attack="sqli")` works end-to-end without extra wiring.
- Multi-step chaining (capture from one run feeding the next) is a clean follow-up layered on the existing `Report` + L3 `Context`/`Identity.capture`, without changing `run()`'s signature.
