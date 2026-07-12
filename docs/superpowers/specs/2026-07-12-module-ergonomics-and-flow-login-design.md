# Module Ergonomics, Flow Login, & README Refresh — Design

**Date:** 2026-07-12
**Status:** Approved
**Builds on:** the merged Flow engine (`penpine/flow/`), the typed `AttackType`
vocabulary, and the flow-aware attacks (`penpine/attack/flow/`).

## Problem & motivation

Three pieces of user feedback:

1. **Run one OR many modules in a single call.** Today `Runner.run` / `FlowRunner.run`
   attack with one module at a time (the request `Runner`'s `attack=AttackType.X`
   already fans out to the signature modules of a category, but you still can't pass
   an explicit *list* of modules/categories). Users want to write one piece of code
   that runs several attacks sequentially instead of repeating the call per module.
2. **Pass a module class without parentheses.** `FlowRunner().run_sync(flow, module=SkipStepModule())`
   is noisy; `module=SkipStepModule` should work. (The request `Runner` already
   accepts a class or an instance; `FlowRunner` does not.)
3. **Flexible auth login.** The README implies login must fit a fixed provider
   (`JsonLoginProvider`), but real logins can need multiple requests, CSRF tokens,
   or custom token extraction. `AuthProvider` is *already* subclassable for this —
   but it's undocumented, and there's no first-class way to define login as a Flow.

Plus a documentation defect: after the `AttackType` migration the README still shows
`attack="sqli"`, `for_attack("sqli")`, and `attack="sqli-boolean"` string forms,
which no longer work.

Overarching principle (unchanged): nothing attacks implicitly; attacking is always
an explicit `Runner`/`FlowRunner` call.

## Current state (relevant facts)

- `Runner.run(request, *, attack=None, module=None, test_cases=None, points=None, validator=None, sender=None)`.
  `_resolve_modules(attack, module)` already instantiates a module **class** and
  resolves an `AttackType` to `registry.by_type(attack, signature_only=True)` — a
  list. `run()` already loops over the resolved modules and aggregates attempts into
  one `Report`. So the request `Runner` is *most of the way there*; it just doesn't
  accept a **list** on `attack=`/`module=`.
- `FlowRunner.run(base_flow, *, module, targets=None)` takes a **single instance**
  and calls `module.mutate(...)` directly (no class instantiation, no list).
- `Report(request, attack_type, baseline, attempts)`; `FlowReport(base_flow, attack_type, baseline, attempts)`.
- `AuthProvider.login(engine) -> Session` is an ABC; `JsonLoginProvider`/`FormLoginProvider`
  are single-request convenience subclasses. `Session(token, cookies, headers, data, issued_at, expires_at)`.
- `Flow(steps, *, actor=None, context=None, continue_on_error=False)` with public
  `.steps`, `.actor`, `.continue_on_error`, `async run()`; fail-fast raises
  `StepError` carrying the partial `FlowResult` on `.result`. `FlowResult.context`
  is the captured-context snapshot (a dict).

---

## Part 1 — Flexible module passing

### `Runner` (request attacks)

`attack=` and `module=` each accept **a single value OR a list**:

- `attack`: an `AttackType` or `list[AttackType]`.
- `module`: an `AttackModule`/`DifferentialModule` **class or instance**, or a list of them.

Normalization: `_resolve_modules` flattens both into one ordered list of module
instances (classes instantiated no-arg; a class with required constructor args
raises `AttackConfigError` naming the module). Duplicates are allowed (caller's
choice). `run()` already loops and aggregates — minimal change.

`Report.attack_type`: keep the single `AttackType` when exactly one category/module
drove the run; set to `None` when the run is heterogeneous (multiple categories or
an explicit multi-module list). Per-`Finding.attack_type` always carries the
specific type.

### `FlowRunner` (flow attacks)

`module=` accepts a **class or instance**, **single or list**:

- A class is instantiated no-arg (so `module=SkipStepModule` works). A class with
  required args (`CrossUserModule(owner=, attacker=)`) passed bare raises
  `AttackConfigError` telling the caller to instantiate it.
- A list runs each module in turn; the baseline flow is run **once** and shared
  across all modules; every module's variants+validations aggregate into **one**
  `FlowReport`.

New/changed signature:

```python
async def run(self, base_flow, *, module, targets=None) -> FlowReport:
    modules = self._resolve_modules(module)      # -> list of instances
    baseline = await self._run_to_result(base_flow)
    attempts = []
    for mod in modules:
        variants = list(mod.mutate(base_flow, baseline, targets))
        attempts += await self._run_variants(mod, variants, baseline)   # bounded concurrency
    attack_type = modules[0].attack_type if len(modules) == 1 else None
    return FlowReport(base_flow=base_flow, attack_type=attack_type, baseline=baseline, attempts=attempts)
```

`_resolve_modules(module)` mirrors the request `Runner`'s helper: accept single/list,
instantiate classes, raise a clear error on a class with required args (catch the
`TypeError` from no-arg instantiation and re-raise as `AttackConfigError`).

Bounded concurrency (`asyncio.Semaphore`) is preserved per the existing
never-raise-batch contract; a variant-run or validator error still lands on
`FlowAttempt.error`.

---

## Part 2 — `FlowLoginProvider`

A new `AuthProvider` subclass (in `penpine/auth/provider.py`) that runs a **login
Flow** and builds a `Session` from its captured context.

```python
class FlowLoginProvider(AuthProvider):
    def __init__(self, flow, *, token_key=None, expires_key=None,
                 cookie_keys=None, data_keys=None):
        ...

    async def login(self, engine) -> Session:
        # run the login flow with the raw engine as its actor (no auth yet)
        run_flow = Flow(steps=self._flow.steps, actor=engine,
                        continue_on_error=self._flow.continue_on_error)
        try:
            result = await run_flow.run()
        except StepError as exc:
            raise LoginError(f"login flow failed at step {exc.name!r}") from exc
        ctx = result.context
        token = ctx.get(self._token_key) if self._token_key else None
        expires_at = (time.time() + float(ctx[self._expires_key])) if self._expires_key and self._expires_key in ctx else None
        cookies = [(k, ctx[k]) for k in (self._cookie_keys or []) if k in ctx]
        data = {k: ctx[k] for k in (self._data_keys or []) if k in ctx}
        return Session(token=token, cookies=cookies, data=data, expires_at=expires_at)
```

Behavior notes:

- The provider **overrides the flow's actor with the `engine`** it's handed, so the
  login flow's steps send through the (unauthenticated) engine. It reconstructs the
  flow from the public `.steps`/`.continue_on_error` (immutability preserved). This
  is why login-flow steps should rely on the flow's default actor rather than naming
  their own.
- Token/expiry/cookies/data are read from the flow's **captured context** — the user
  captures them in the login flow via `Extract` (JSONPath, regex, cookie, header),
  exactly like any other flow. `expires_key` follows the `JsonLoginProvider`
  convention: the captured value is seconds-from-now, added to `time.time()`.
- A fail-fast `StepError` becomes a `LoginError` (consistent with the other providers'
  `_check_2xx`). All keys are optional — a login might yield only cookies, or only a
  token.
- `refresh`/`validate` inherit the base `AuthProvider` behavior (re-login on refresh;
  expiry-based validate), which is correct for a Flow login.

Exported from `penpine.auth` (added to `__init__.py`'s `__all__`).

---

## Part 3 — README refresh

- **Fix the stale strings** (correctness bug): `attack="sqli"` → `attack=AttackType.SQLI`;
  `analysis.for_attack("sqli")` → `analysis.for_attack(AttackType.SQLI)`;
  `Runner.run(attack="sqli-boolean")` → `Runner().run_sync(req, module=BooleanSqliModule)`;
  add `from penpine import AttackType` / `from penpine.attack.types import AttackType`
  to the relevant snippets.
- **Show multi-module**: `Runner().run_sync(req, module=[SqliModule, XssModule])` and
  `FlowRunner().run_sync(flow, module=[SkipStepModule, CrossUserModule(owner=a, attacker=b)])`.
- **Show class-not-instance**: `module=SkipStepModule`.
- **Add a `FlowLoginProvider` example** and a short "roll your own `AuthProvider`"
  subclassing note (multi-request/custom login).

## Testing (no network, fakes as usual)

- **Part 1**: `Runner` with `module=[A, B]` and `attack=[AttackType.SQLI, AttackType.XSS]`
  aggregates attempts from all; `Report.attack_type` is `None` for a multi list, the
  single type for one. `FlowRunner` with `module=SkipStepModule` (class) instantiates
  it; `module=[SkipStepModule, CrossUserModule(...)]` runs both against one shared
  baseline into one `FlowReport`; a bare class needing args raises `AttackConfigError`.
- **Part 2**: a fake-actor login flow that captures a token → `FlowLoginProvider`
  produces a `Session` with that token/expiry; a multi-step login (CSRF then submit)
  works; a failing login flow raises `LoginError`.
- All existing tests stay green; mypy stays clean.

## Non-goals

- No implicit attacking; `Flow.run()` stays behaviorally unchanged.
- No change to how a single module/category already resolves (only add list/class
  acceptance on the two runners).
- `FlowLoginProvider` cookie/data mapping is intentionally simple (named context
  keys); richer cookie-jar semantics are out of scope.

## Rollout

One implementation plan, three parts landing in order: (1) `FlowRunner` list/class
support + `Runner` list support; (2) `FlowLoginProvider`; (3) README refresh + full
regression. Small enough for a single plan.
