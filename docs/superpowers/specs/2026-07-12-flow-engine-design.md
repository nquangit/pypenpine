# Flow Engine — Design

**Date:** 2026-07-12
**Status:** Approved (foundation spec)
**Scope:** The multi-step **Flow** primitive only. Flow-aware *testing/targeting* and
flow-aware *attack modules* are follow-on specs that build on this foundation and are
out of scope here.

## Problem

penpine today operates on **individual requests**. `Runner` runs exactly one request
against one attack; `Engine`/`SessionManager`/`Identity` send one request at a time.
There is no way to express a **multi-step scenario** with ordering, conditions, and
recovery — e.g. a banking flow where the first login requires an *activation* step
before authentication, or where a step must re-run after a session ends.

Real pentesting scenarios are sequences: log in, create a resource, act on it, and
sometimes recover from an out-of-band condition (activation, re-auth) before resuming.
We need a first-class **Flow** that is:

- **Introspectable** — steps are reified data, so a later testing layer can target a
  specific step and fork the flow at that point.
- **Conditional** — a step can be skipped (guard) or trigger a recovery sub-flow.
- **Multi-actor** — different steps may be sent by different identities sharing one
  data context (foundation for cross-user IDOR testing).
- **Robust and easy to use** — sync/async parity, a typed result, and errors that
  never lose the partial progress made.

## Non-goals (explicitly deferred)

- Flow-aware **testing/targeting** (test step *k*, one injection point, or all steps ×
  all points) — separate spec (Spec 2).
- Flow-aware **attack modules** (skip-a-step business-logic checks, cross-user data
  transfer) — separate spec (Spec 3).
- Arbitrary **branching / looping / DAGs**, **parallel** steps. The core is linear.
- Re-implementing **session-lifecycle recovery** (401 re-login, token refresh) — this
  already exists in the L2 `SessionManager`/`RefreshScheduler` and composes underneath
  a flow automatically.

## Placement

A new package **`penpine/flow/`**, conceptually **L3.5**: above `penpine.data`
(identities/context), below the attack layer. It **composes** existing primitives and
does not modify L0–L2 internals. Public symbols are re-exported from
`penpine/flow/__init__.py`, and the top-level user-facing types (`Flow`, `Step`) are
added to `penpine/__init__.py`'s `__all__`.

## Design decisions (locked during brainstorming)

1. **Flow model:** reified list of `Step` objects, with an escape hatch (a step may
   wrap an arbitrary callable). Chosen over an imperative-script model and a pure
   declarative dict/YAML model because introspectability is required for the future
   testing layer, while the escape hatch preserves the code-first philosophy.
2. **Control flow:** linear steps + per-step **guard** (run/skip) + per-step
   **recovery** (predicate → sub-flow → retry-once). No branching/looping in the core.
3. **Recovery is step-local.** Session-expiry recovery is delegated to L2 underneath.
4. **Multi-actor with one shared flow-scoped `Context`.** Single-actor flows are the
   degenerate case where every step uses the same actor.
5. **Fail-fast by default** (steps are dependent), with `continue_on_error=True` to
   relax. This differs deliberately from the attack `Runner`'s never-raise-batch
   behavior.

## Core objects

Each has a single, clear purpose and a well-defined interface.

### `Flow`

Owns an ordered `list[Step]`, a default `actor`, and one flow-scoped `Context`.

```python
class Flow:
    def __init__(self, steps, *, actor=None, context=None,
                 continue_on_error=False): ...

    @property
    def steps(self) -> list[Step]: ...
    def step(self, name: str) -> Step: ...            # lookup by name

    async def run(self) -> FlowResult: ...
    def run_sync(self) -> FlowResult: ...
```

- `context` defaults to a fresh `Context`; callers may pass a shared one.
- The `Flow` owns the context used for render/capture — **not** the identities' own
  `ctx`. This is what threads one actor's captured data into another actor's request.

### `Step`

A named unit of work.

```python
class Step:
    def __init__(self, name, *, actor=None,
                 request=None,            # Request | Callable[[Context], Request]
                 action=None,             # Callable[[FlowContext], object] escape hatch
                 capture=None,            # capture specs, as data-layer `capture` takes
                 guard=None,              # Callable[[Context], bool]; True = run
                 recovery=None): ...      # Recovery | None
```

- Exactly one of `request` or `action` is provided. `request` may be a `Request` or a
  `callable(ctx) -> Request` for dynamic construction from captured data.
- `actor` defaults to the flow's default actor. Any object exposing `async send(request)`
  qualifies (`Identity`, `SessionManager`, `Engine`) — duck-typed, consistent with
  `Runner`'s `sender`.
- `guard(ctx) -> bool`: returns `True` to run the step, `False` to skip it.

### `Recovery`

```python
class Recovery:
    def __init__(self, *, when, do, retry=True): ...
    # when: Callable[[StepOutcome], bool]
    # do:   Flow                      (a sub-flow sharing the parent's context)
    # retry: re-run the step once after `do` completes
```

### `StepOutcome`

The read-only view passed to `Recovery.when` after a step is attempted. (`guard`
runs *before* the send and receives only the `Context`, so it does not see a
`StepOutcome`.)

```python
@dataclass
class StepOutcome:
    ctx: Context
    actor: object
    response: object | None = None      # None if not yet sent / send raised
    error: Exception | None = None
```

### `FlowContext` (escape-hatch only)

Passed to a step's `action` callable. Exposes the flow `Context` and a helper to send
through an actor, for the rare non-request step. Kept minimal.

## Execution semantics

For each `Step` in order:

1. **Guard.** If `step.guard` is set and `guard(ctx)` is `False`, record a `skipped`
   `StepResult` and continue.
2. **Build & send.** Resolve `request` (call it with `ctx` if it's a callable), render
   it against the flow `Context` via the existing `data`-layer `render`
   (`build_mapping(context=flow_ctx, data=actor.data)`), `await actor.send(rendered)`,
   then `capture(flow_ctx, response, step.capture)`. (Escape-hatch steps call
   `action(flow_context)` instead.)
3. **Recovery.** Build a `StepOutcome`. If `step.recovery` is set and
   `recovery.when(outcome)` is `True` (an exception **or** a response condition such as
   HTTP 409 / "not activated"):
   - run `recovery.do` as a sub-flow sharing the same `Context`;
   - if `recovery.retry`, re-run this step **once** (guard is re-evaluated). Recovery is
     attempted **once** per step — a second failure is unrecovered.
4. **Outcome classification.** `ok` (sent, no triggering condition), `recovered`
   (recovery ran and the retry succeeded / no longer triggers), `skipped` (guard),
   `failed` (unrecovered error or still-triggering condition after recovery).
5. **Failure handling.**
   - Default (**fail-fast**): stop at the first `failed` step, populate the partial
     `FlowResult`, and raise `StepError` with the partial result attached.
   - `continue_on_error=True`: record the error on the `StepResult` and proceed to the
     next step (batch-style).

Sub-flows invoked by recovery run on the same event loop as the parent.

## Result model

Mirrors the attack layer's `Report`/`Attempt` for familiarity.

```python
@dataclass
class StepResult:
    step: str                       # step name
    actor: object
    status: str                     # "ok" | "skipped" | "recovered" | "failed"
    request: object | None = None
    response: object | None = None
    captured: list[str] = ...        # context keys written by this step
    recovery_ran: bool = False
    error: Exception | None = None
    elapsed_ms: float | None = None

@dataclass
class FlowResult:
    steps: list[StepResult]
    context: dict                   # final flow-context snapshot (Context.to_dict())

    @property
    def ok(self) -> bool: ...        # no failed step
    @property
    def failed_step(self) -> StepResult | None: ...
    def step(self, name: str) -> StepResult: ...
    def summary(self) -> dict: ...   # {"ran", "skipped", "recovered", "failed"}
    def __iter__(self): ...          # over step results
```

## Errors

New in `penpine/flow/exceptions.py`, rooted at the existing `PenpineError`:

- `FlowError(PenpineError)` — base for the flow package.
- `StepError(FlowError)` — carries the failing step `name`/`index` and the partial
  `FlowResult` (as `.result`) so a fail-fast caller still sees progress made.

Under `continue_on_error=True`, step failures do not raise; they land on
`StepResult.error`.

## Seams for the follow-on specs

Shaped now so the next specs build on the engine without reworking it:

- **Spec 2 (testing):** requires running the flow to step *k*, snapshotting the
  context, then forking and injecting at a chosen injection point of step *k*'s request.
  The reified `flow.steps` list + the flow-owned `Context` are what make this tractable.
  A **`Flow.prefix(k)` / checkpoint-snapshot** capability is the intended seam; noted
  here, not built now.
- **Spec 3 (flow-aware modules):** skip-a-step (business-logic) and cross-user data
  transfer (IDOR) rely on multi-actor + shared context (now foundational) and on
  omitting/replacing a step. The **`FlowResult` + step `status` vocabulary** is the seam
  a flow-aware validator will read.

## Testing

No network, consistent with the existing suite (fake senders like
`tests/attack/_fakes.py`). New tests in `tests/flow/`:

- linear happy path (data threaded across steps);
- guard-skip;
- recovery triggers → sub-flow runs → retry succeeds (`recovered`);
- recovery exhausted → fail-fast, `StepError` with partial `FlowResult`;
- `continue_on_error=True` records errors and proceeds;
- multi-actor: actor A captures, actor B templates the value in a shared context;
- escape-hatch `action` step;
- `run_sync` parity with `run`.

## Rollout

Single implementation plan: `penpine/flow/` package (`flow.py`, `step.py`,
`recovery.py`, `results.py`, `exceptions.py`, `__init__.py`), re-exports through
`penpine/__init__.py`, plus `tests/flow/`. No changes to existing layers. Documentation
(README section, a `samples/` flow example in the CLI scaffold) can follow in the same
plan or a docs pass.
