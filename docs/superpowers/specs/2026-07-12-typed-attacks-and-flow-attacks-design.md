# Typed Attack Vocabulary & Flow-Aware Attacks — Design

**Date:** 2026-07-12
**Status:** Approved
**Builds on:** the merged Flow engine (`penpine/flow/`, L3.5) and the existing
attack layer (`penpine/attack/`).
**Delivery:** one design, **two implementation plans** — Plan A (typed `AttackType`
vocabulary) then Plan B (flow-aware attacks built on it).

## Problem & motivation

Two standing directives from the user (see also the project memory):

1. **Type attack identifiers; stop using bare strings.** Today attacks are
   referenced by string: `Runner().run(attack="sqli")`, analyzer tags like
   `attack_types=("sqli","xss")`, and `select_attack_type="sqli"`. Strings are
   undiscoverable (you can't import the set of valid types), typos fail only at
   runtime, and third-party modules have no canonical vocabulary to conform to.

2. **Attack the flow, not just single requests.** The existing attack layer
   operates on one request and its injection points. Real business-logic and
   access-control bugs live in multi-step flows: skipping an authorization/gate
   step and still reaching a protected outcome (broken access control), or one
   user reaching another user's resource (IDOR). The merged Flow engine makes
   flows first-class; attacks should be able to target them.

Overarching principle (already true, preserved here): **nothing attacks by
default.** Users compose requests and flows and run them normally; attacking is a
separate, explicit action where the user specifies what / which type / where. By
default an attack targets all analyzer-/target-selected points; the user may
restrict them.

## Current state (what exists)

- `AttackModule(name, generator, validator, applies_to, description)`. Two shapes:
  signature modules (`PayloadGenerator` -> `TestCase`s, `Validator` judges the
  response vs a baseline) and active "differential" modules (expose
  `probe(point, request, sender, baseline=)` and drive their own sends).
- Module registry keyed by `module.name` (string). `Runner.run(attack="sqli")`
  resolves via the registry.
- Analyzer (`penpine/attack/analyze/`): `DEFAULT_RULES` tag each `InjectionPoint`
  with string `attack_types`; `select_attack_type` links a differential module to
  the category it consumes.
- `BUILTIN_MODULES` (signature: sqli, xss, traversal, redirect) vs
  `DIFFERENTIAL_MODULES` (blind: sqli-boolean, sqli-time) are already separated;
  differential modules are excluded from the default set.
- Flow engine (`penpine/flow/`): immutable `Step`s, a `Flow` with a shared
  `Context`, `FlowResult`/`StepResult`, `run`/`run_sync`. `Runner` never raises
  out of a batch; flows fail fast by default.

---

# Plan A — Typed `AttackType` vocabulary

A self-contained refactor of the existing attack layer. Lands with the whole
suite green (migrated to `AttackType`) before Plan B builds on it.

## Two vocabularies, kept distinct

- **Attack-type category** — what a point is a *candidate for*; a closed,
  enumerable set. Becomes the `AttackType` enum.
- **Module identity** — a concrete implementation; open/extensible. Stays a
  string `name` (registry key / human label). Several modules may serve one
  category (error/boolean/time all serve `SQLI`).

## `AttackType` enum

New enum in the attack core (e.g. `penpine/attack/types.py`), values chosen from
the current analyzer tags plus one new category for skip-a-step:

```python
class AttackType(Enum):
    SQLI = "sqli"
    XSS = "xss"
    PATH_TRAVERSAL = "path-traversal"
    OPEN_REDIRECT = "open-redirect"
    SSRF = "ssrf"
    IDOR = "idor"
    HEADER_INJECTION = "header-injection"
    BROKEN_ACCESS = "broken-access"   # new, for skip-a-step (Plan B)

    @classmethod
    def from_str(cls, value: str) -> "AttackType": ...  # coercion at the edge
```

The string values are retained **only** as the serialized form and for the
`from_str` coercion helper used at CLI/config/report boundaries. The library API
is typed.

## Changes across the attack layer

- **Modules** declare a typed `attack_type: AttackType` field (in addition to the
  string `name`). `select_attack_type` on differential modules becomes
  `AttackType | None`.
- **Analyzer**: `ClassificationRule.match` returns `set[AttackType]`;
  `InjectionPoint.attack_types` becomes `tuple[AttackType, ...]`;
  `Analysis.for_attack(attack_type: AttackType)` and `Analysis.attack_types`
  operate on `AttackType`.
- **`Runner.run`** signature: `attack: AttackType | None` (category) or `module=`
  (an `AttackModule` class or instance). Point selection filters by the typed
  `attack_type`. Passing a **class** instantiates it (a no-arg constructor is the
  built-in convention; instances are passed through).
- **Category -> which modules** (resolves the "three modules serve SQLI"
  ambiguity, reusing the existing default/differential split): `attack=AttackType.SQLI`
  runs the registered **signature** modules whose `attack_type == SQLI` — precisely
  the registered modules with that `attack_type` that are **not** probe-based
  (a probe-based/differential module exposes `probe`; today `SQLI_MODULE` has no
  probe while `sqli-boolean`/`sqli-time` do). Differential/blind modules stay
  opt-in via explicit `module=`. This keeps the "nothing surprising runs
  automatically" property.
- **Registry** keeps string-`name` lookup for CLI/config convenience but is no
  longer the primary path — `Runner` accepts modules directly. `list_modules()`
  and a new way to list by `attack_type` support discoverability.

## Migration

Every built-in module, the analyzer rules, the `Runner`, and the attack tests
move from strings to `AttackType`. Existing call sites like `attack="sqli"`
become `attack=AttackType.SQLI`. The refactor is complete when the full suite
passes on the typed vocabulary. No behavior change beyond the identifier type and
the category->default-modules selection rule.

---

# Plan B — Flow-aware attacks

New package **`penpine/attack/flow/`** (L4-flow): depends on both the Flow engine
and the attack core (for `AttackType`, `Confidence`), modifies neither. Never
invoked implicitly — attacking a flow is always an explicit `FlowRunner` call.

## `FlowAttackModule` contract

The flow-level parallel to `PayloadGenerator` + `Validator`:

```python
class FlowAttackModule(ABC):
    attack_type: AttackType
    name: str

    @abstractmethod
    def mutate(self, base_flow, baseline_result, targets) -> Iterable[FlowVariant]:
        """Yield variant flows (mutations of base_flow), each tagged with what it changed."""

    @abstractmethod
    def validate(self, variant, variant_result, baseline_result) -> FlowFinding | None:
        """Judge one variant's FlowResult against the baseline."""
```

`FlowVariant` = `(flow: Flow, target: str, meta: dict)` — `target` is a
human-readable description of the mutation (a dropped step name; "bob accesses
alice's `create`").

**Targets generalize "where to attack."** For flow attacks, targets are **steps**
(skip-a-step) and **identities** (cross-user), not injection points. Default =
every applicable step / actor-swap; the user restricts via `steps=[...]` or an
identity pair.

## Mutation helpers (`mutators.py`)

Pure functions returning new immutable `Flow`s (mirroring `Request` copy-on-write;
they never mutate the base):

- `drop_step(flow, name_or_index) -> Flow`
- `swap_actor(flow, step_names, actor) -> Flow`
- `seed_context(flow, values: dict) -> Flow` (returns a flow whose `Context` is
  pre-seeded — used to transplant one identity's captured data into another's run)

## `FlowRunner`

Parallel to `Runner`; never implicit:

1. Run the base flow once -> **baseline `FlowResult`** (+ final context).
2. `module.mutate(base_flow, baseline_result, targets)` -> variant flows.
3. Run each variant with bounded concurrency (like `Runner`), capturing its
   `FlowResult`. **Never raises out of the batch** — a variant that errors is
   recorded on its attempt, matching `Runner`'s contract.
4. `module.validate(...)` each -> `FlowFinding`s.
5. Return a **`FlowReport`**.

`run()` / `run_sync()` parity. The base flow and its variants **carry their own
actors** (each `Step`'s identity), so `FlowRunner` does not take a global sender
the way `Runner` does — it just runs the flows it's given. Attack-specific
identities are the module's config (e.g. `CrossUserModule` is constructed with the
owner and attacker identities and uses them to build the variant).

## Result model (`results.py`)

Flow-specific, not overloading the request-shaped `Finding` (which is bound to an
`InjectionPoint`):

```python
@dataclass
class FlowFinding:
    attack_type: AttackType
    target: str                    # the mutation that triggered it
    confidence: Confidence         # reuse the existing enum
    evidence: str
    baseline_result: object        # FlowResult
    variant_result: object         # FlowResult

@dataclass
class FlowReport:
    base_flow: object
    attack_type: AttackType | None
    baseline: object               # baseline FlowResult
    attempts: list                 # one per variant: outcome / FlowFinding / error
    # .findings, .errors, .summary(), __iter__  (mirrors Report)
```

## Module 1 — `SkipStepModule` (`attack_type = BROKEN_ACCESS`)

- **mutate**: for each targeted step, yield a variant with that step dropped
  (`drop_step`). Default targets = every step except the goal; `steps=[...]`
  restricts.
- **goal detection**: a **goal step** represents the protected outcome — defaults
  to the **last step**, overridable by a named step or a custom
  `success(FlowResult) -> bool` predicate. A finding fires when the baseline goal
  succeeded AND, with step *k* dropped, the goal step **still succeeds comparably**
  (e.g. same 2xx class). Dropping a step that breaks the goal (the secure case)
  yields nothing.
- **confidence**: HIGH when the variant goal response closely matches the
  baseline's; MEDIUM when it merely succeeds.

## Module 2 — `CrossUserModule` (`attack_type = IDOR`)

- **config**: an **owner** identity (A), an **attacker** identity (B), and which
  steps are the "access" steps (default: the steps that consume a value A
  captured).
- **mutate**: one variant that runs the access steps as B (`swap_actor`) while
  **seeding B's variant context with A's captured values** (`seed_context` from
  the baseline result's context) — B attempts to reach A's resource.
- **detection default**: a finding fires when the swapped step under B **succeeds
  where denial was expected** (2xx instead of 401/403/404); to cut false positives
  on public resources, HIGH confidence requires **B's response body to match A's**
  for that resource, MEDIUM on a bare 2xx. Overridable by a custom predicate.

Both defaults follow "attack all targeted points by default, or specify," and
both are explicit about false positives (goal comparison; body-match refinement).

## Goal marking — config over engine change

Skip-a-step's goal is resolved **in `SkipStepModule`'s config** (default = the
base flow's last step; or a named step; or a custom predicate). The Flow engine
is **not** modified. A `Step.goal: bool = False` flag is noted as a possible
ergonomic follow-up, not part of this work.

## Packaging

```
penpine/attack/flow/
  __init__.py        # re-exports FlowRunner, FlowAttackModule, FlowFinding, FlowReport, the modules
  module.py          # FlowAttackModule, FlowVariant
  mutators.py        # drop_step, swap_actor, seed_context
  runner.py          # FlowRunner
  results.py         # FlowFinding, FlowReport
  modules/
    skip_step.py     # SkipStepModule
    cross_user.py    # CrossUserModule
```

`AttackType` (from Plan A) is shared by request and flow attacks. Top-level
`penpine` may re-export `FlowRunner` and `AttackType`.

## Testing (both plans; no network, fakes like today)

- **Plan A**: existing attack/analyzer/runner tests migrated to `AttackType`;
  a test that `attack=AttackType.SQLI` selects signature SQLI modules and NOT the
  differential ones; `from_str` coercion round-trips.
- **Plan B**: fake-actor flows drive the modules —
  - skip-a-step **finds** the missing-gate case (goal still succeeds with a step
    dropped) and **stays silent** on the secure case (goal breaks);
  - cross-user **finds** B-reaches-A (swapped step 2xx + body match) and **stays
    silent** when B is correctly denied (403/404);
  - `FlowRunner` never raises out of a batch (a variant error is recorded);
  - `run_sync` parity;
  - mutation helpers return new flows without mutating the base.

## Non-goals (deferred)

- Additional flow attacks beyond skip-a-step and cross-user (e.g. step-reorder,
  replay, parameter-tampering across steps).
- `Step.goal` flag in the Flow engine (noted as a follow-up).
- Flow-aware **testing/targeting** of request-level injection points at a chosen
  step (the separate "flow-aware testing" spec — `Flow.prefix(k)`/checkpoint
  snapshotting). This design is about *flow-structural* attacks, not injecting
  payloads mid-flow.
- Auto-discovery of "which step is a gate" — the user designates goal/access
  steps (with sensible defaults).

## Rollout

1. **Plan A** (typed `AttackType`): enum + module/analyzer/Runner migration +
   test migration. Ships independently, full suite green.
2. **Plan B** (flow-aware attacks): `penpine/attack/flow/` package + the two
   modules + tests, on top of Plan A and the merged Flow engine.
