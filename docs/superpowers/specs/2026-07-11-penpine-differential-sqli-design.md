# Penpine — Differential (Blind) SQLi: Boolean + Time-Based (Design Spec)

**Date:** 2026-07-11
**Status:** Approved for implementation planning
**Scope:** Boolean-based and time-based blind SQL-injection detection via an active-prober extension to the L4c Runner. Sub-project E of Tier 3 (value-first order). **Library-only** — driven entirely from code via `Runner.run(attack=...)`; no CLI involvement.

---

## 1. Context

The L4c Runner validates each generated test case's **single** response against one baseline (`validator.evaluate(test_case, response, baseline)`) and never exposes latency to validators. Blind SQLi cannot be expressed this way: boolean-based must compare a TRUE vs a FALSE response, and time-based must measure and confirm response latency across several sends. Both require an actor that drives multiple round-trips and decides between them. This spec adds an **active-prober** module type and a Runner branch for it, then two concrete modules.

This is the framework's originally-deferred "differential SQLi" follow-up (documented in the L4c/L4d specs). It is used purely from code:
```python
register_builtins()
report = await Runner(sender=identity).run(request, attack="sqli-time")
```

Depends on (all existing):
- L4c `Runner` (`run`/`run_sync`, per-point send, `Report`/`Attempt`, `_select_points`, bounded concurrency).
- L4a `InjectionPoint`, `Payload`, `TestCase`, `Finding`, `Confidence`; `registry.register`/`get`; `analyze(request).for_attack(tag)`.
- L0 `Request.replace_at(expr, value)`, `Response.status_code`, `Response.body.raw`.

**Decisions (this round):**
- Runner integration via an **active-prober interface** (`async probe(point, request, sender, *, baseline)`), not a group-validator or a separate runner.
- **Time-based:** baseline latency → delayed probe → confirm (2nd delayed send) → fast control; `N=3` s; DBs MySQL + PostgreSQL + MSSQL.
- **Boolean-based:** three-way anchored — TRUE ≈ baseline **and** FALSE ≠ baseline (`_similar` = status + body-length tolerance).
- Differential modules register by name but are **excluded from `BUILTIN_MODULES`** (they are slow/intrusive; opt-in by name only).
- Timing is via an **injectable clock** (default `time.perf_counter`) so tests are deterministic and never sleep.

## 2. Goals & Non-Goals

**Goals**
- A `DifferentialModule` prober type and a Runner branch that probes each selected point and returns a `Report` (one `Attempt` per point).
- `BooleanSqliModule` (`sqli-boolean`) and `TimeSqliModule` (`sqli-time`) producing `HIGH` findings only on confirmed differentials.
- Constructor-injectable payloads/thresholds/clock; registration by name; exclusion from the default signature set.
- Fully unit-testable with fake senders + a fake clock — no network, no real sleeping.

**Non-Goals (documented follow-ups)**
- Oracle / SQLite time payloads (Oracle syntax fiddly; SQLite has no sleep).
- Data exfiltration (extract-via-boolean/bitwise), stacked-query/UNION, second-order.
- Any CLI surface (this is library-only by project philosophy).
- Statistical/correlation timing models (single confirmed delay + control is v1).

## 3. Module Layout

```
penpine/attack/modules/differential.py   # new — DifferentialModule, _similar, Boolean/Time modules, payload constants
penpine/attack/runner.py                 # modified — differential branch (detect probe, per-point probe loop)
penpine/attack/modules/__init__.py       # modified — DIFFERENTIAL_MODULES, register both lists, exports
```
No changes to `penpine/cli/`, the analyzer, or the existing signature modules.

## 4. Prober interface + Runner branch

### 4.1 `DifferentialModule` (in `differential.py`)
```python
class DifferentialModule:
    name = "differential"
    applies_to: tuple = ()
    select_attack_type: str | None = None  # analyzer tag for point selection (e.g. "sqli")

    def applies(self, kind: str) -> bool:
        return not self.applies_to or kind in self.applies_to

    async def probe(self, point, request, sender, *, baseline=None):
        raise NotImplementedError  # -> Finding | None
```
`select_attack_type` decouples the analyzer tag used for point selection (`"sqli"`) from the module `name` (`"sqli-boolean"`), because the analyzer tags points `sqli`, not `sqli-boolean`.

### 4.2 Runner branch (`runner.py`)
In `run()`, after `module = self._resolve_module(attack, module)` and `attack_type = attack or module.name`, detect a differential module by duck-typing `hasattr(module, "probe")`. If so, take the differential path (the signature `generate`/`validate`/`test_cases` path is untouched otherwise):
- **Select points:** `selection_tag = getattr(module, "select_attack_type", None) or attack or module.name`; `self._select_points(request, module, selection_tag, points)`. (`select_attack_type` MUST take priority over `attack` — the module is named `sqli-boolean` but the analyzer tags points `sqli`, so `run(attack="sqli-boolean")` must still select `sqli`-tagged points.)
- **Baseline:** capture as today (swallowed to `None` on error) when `capture_baseline`.
- **Probe per point** under the existing `asyncio.Semaphore`: `await self._probe_attempt(request, point, module, baseline, active_sender)`.
- Return `Report(request, attack_type, baseline, attempts)` — `attack_type` remains the module name for reporting.

```python
async def _probe_attempt(self, request, point, module, baseline, sender):
    placeholder = TestCase(point=point, payload=Payload("<differential>"), attack_type=module.name)
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
Per-point error isolation (one failing point never aborts the run); `Report.summary()` reports `sent` = points probed, `found` = findings, `failed` = errored points.

## 5. `_similar` (response comparison)

```python
def _similar(a, b, *, tolerance) -> bool:
    if a is None or b is None:
        return False
    if a.status_code != b.status_code:
        return False
    return abs(len(a.body.raw) - len(b.body.raw)) <= tolerance
```
Default tolerance derived per baseline: `max(32, len(baseline.body.raw) // 20)` (~5%).

## 6. `BooleanSqliModule` (`sqli-boolean`)

- `name = "sqli-boolean"`, `select_attack_type = "sqli"`, `applies_to = ("param", "form", "json", "multipart", "cookie")`.
- `BOOLEAN_PAYLOAD_PAIRS` (default, injectable) — DB-agnostic context variants, each `(true, false)`:
  - `("' AND 1=1-- -", "' AND 1=2-- -")`
  - `("' AND '1'='1", "' AND '1'='2")`
  - `(" AND 1=1", " AND 1=2")` (numeric close)
  - `(") AND 1=1-- -", ") AND 1=2-- -")`
- **`probe`:** `base = baseline or await sender.send(request)`; `tol = max(32, len(base.body.raw)//20)`. For each `(t, f)` pair: `rt = await sender.send(request.replace_at(point.expr, t))`, `rf = await sender.send(request.replace_at(point.expr, f))`; if `_similar(rt, base, tolerance=tol) and not _similar(rf, base, tolerance=tol)` → return `Finding("sqli-boolean", point, Payload(t, technique="boolean-blind"), Confidence.HIGH, evidence=f"boolean-based blind SQLi: TRUE ({t!r}) matched baseline, FALSE ({f!r}) differed", request=<TRUE request>, response=rt)`. Else `None`.

## 7. `TimeSqliModule` (`sqli-time`)

- `name = "sqli-time"`, `select_attack_type = "sqli"`, `applies_to = ("param", "form", "json", "multipart", "cookie")`.
- Constructor: `TimeSqliModule(*, templates=None, delay=3, threshold=0.8, clock=time.perf_counter)`.
- `TIME_PAYLOAD_TEMPLATES` (default, injectable) — each contains `{n}`:
  - MySQL: `"' AND SLEEP({n})-- -"`, `" AND SLEEP({n})"`, `"' AND (SELECT 1 FROM (SELECT SLEEP({n}))x)-- -"`
  - PostgreSQL: `"' AND pg_sleep({n})-- -"`, `"';SELECT pg_sleep({n})-- -"`
  - MSSQL: `"'; WAITFOR DELAY '0:0:{n}'-- -"`, `" WAITFOR DELAY '0:0:{n}'"`
- **`probe`:**
  1. **Baseline latency** `base_lat` = min of two timed un-injected sends (`_timed(sender, request)`).
  2. For each template → `payload = template.format(n=self._delay)`; `t1 = await _timed(sender, request.replace_at(point.expr, payload))`. If `t1 - base_lat >= delay*threshold`:
     - **Confirm:** `t2 = await _timed(...)` (same payload). **Control:** the SAME matched template with zero delay — `control = template.format(n=0)`; `tc = await _timed(sender, request.replace_at(point.expr, control))`. This keeps the control in the same injection context so only the sleep, not the payload shape, explains a delay.
     - If `t2 - base_lat >= delay*threshold` **and** `tc - base_lat < delay*threshold` → return `Finding("sqli-time", point, Payload(payload, technique="time-blind"), Confidence.HIGH, evidence=f"time-based blind SQLi: {payload!r} delayed ~{t1-base_lat:.1f}s (confirmed {t2-base_lat:.1f}s), control fast", request=<payload request>, response=<confirming response>)`.
  3. Else `None`.
- `_timed(sender, req)`: `start = self._clock(); resp = await sender.send(req); return self._clock() - start, resp` (returns `(elapsed, response)`; probe uses both).
- The injected `clock` + a fake sender that advances that clock make time-based tests deterministic and instant.

## 8. Registration & exports (`modules/__init__.py`)

- Import `BooleanSqliModule`, `TimeSqliModule`, `DifferentialModule`, `_similar`, `BOOLEAN_PAYLOAD_PAIRS`, `TIME_PAYLOAD_TEMPLATES`, and the instances `BOOLEAN_SQLI_MODULE`, `TIME_SQLI_MODULE` from `differential`.
- `DIFFERENTIAL_MODULES = [BOOLEAN_SQLI_MODULE, TIME_SQLI_MODULE]`.
- `BUILTIN_MODULES` stays the four signature modules (unchanged).
- `register_builtins(*, replace=True)` registers `(*BUILTIN_MODULES, *DIFFERENTIAL_MODULES)` — so `sqli-boolean`/`sqli-time` resolve by name via `Runner.run(attack=...)`, while iterating `BUILTIN_MODULES` never fires them.
- Add all new names to `__all__`.
- The global `registry` stores by name and is duck-typed; differential modules coexist with `AttackModule`s.

## 9. Errors

- A `probe` raising → captured on the point's `Attempt.error` (per-point isolation); the run completes.
- A send failing inside a probe surfaces as the probe's own exception → the point's `Attempt.error` (the module does not swallow send errors unless it chooses to).
- No new exception types.

## 10. Testing Strategy (TDD)

All unit-level, no network, no real sleeping.

- **Runner differential branch:** a fake module with `probe` returning a `Finding` for a point → `Report.findings` non-empty, one `Attempt` per selected point; a `probe` raising → that `Attempt.error` set, others succeed; a `probe` returning `None` → no finding. Confirm `hasattr(probe)` routing does not affect signature modules (existing runner tests stay green).
- **`_similar`:** equal status + within-tolerance length → True; different status → False; length delta > tolerance → False; `None` operand → False.
- **BooleanSqliModule:** a fake sender scripted so the TRUE payload's response matches the baseline (status+length) and the FALSE payload's differs → `HIGH` finding referencing the TRUE payload; a sender returning identical responses for everything → `None`; the finding's `request`/`response` are the TRUE probe's.
- **TimeSqliModule:** a fake clock + a fake sender that advances the clock by ~`delay` for sleep payloads and ~0 for baseline/control → `HIGH` finding, and it required the confirmation (a sender that is slow once but fast on the confirm → `None`); a uniformly-slow endpoint (control also slow) → `None`; custom `delay`/`threshold` honored.
- **registration:** `register_builtins()` makes `registry.get("sqli-boolean")`/`get("sqli-time")` resolve; `sqli-boolean`/`sqli-time` are NOT in `BUILTIN_MODULES`; the four signature modules still are.
- **end-to-end (Runner + module):** `register_builtins()`; `Runner(sender=fake).run_sync(Request.from_url("http://h/?q=1"), attack="sqli-boolean")` with a boolean-injectable fake → a `sqli-boolean` `HIGH` finding on `param:q`.

## 11. Dependencies

Runtime: stdlib `asyncio`, `time`. No new dependencies. Python 3.11+.

## 12. Forward Hooks

- Oracle/SQLite time payloads and a statistical timing model extend `TimeSqliModule` via its injectable templates/threshold without touching the Runner.
- Boolean data-exfiltration (bitwise extract) is a larger module reusing the same prober interface.
- The `DifferentialModule` prober interface is reusable for other blind classes (blind command-injection, blind SSTI, OOB) later.
