# Project Scaffold Enhancements — Design

**Date:** 2026-07-12
**Status:** Approved
**Builds on:** Flow engine, typed `AttackType`, flow-aware attacks, multi-module
runs, `FlowLoginProvider` (all merged).

## Problem

`penpine new <name>` scaffolds a runnable project, but it lags the framework and
has real usability gaps:

1. **Ctrl+C can't stop a run.** `Runner.run_sync` (and `Engine.send_sync`,
   `SessionManager.send_sync`) run the event loop in a daemon thread and block the
   main thread on `future.result()` — an uninterruptible wait — so
   `KeyboardInterrupt` is not delivered until the batch finishes. (`FlowRunner.run_sync`
   uses `asyncio.run` and *does* handle Ctrl+C — the inconsistency to fix.)
2. **Logging is poor.** `configure_logging` only attaches a console handler; there
   is no file sink and nothing logs per request, so a run is opaque.
3. **No file logging option.**
4. **Config uses strings for attack types.** `config.ATTACKS = ["sqli", "xss"]`
   coerced via `AttackType.from_str` — the string vocabulary the typed migration
   was meant to remove.
5. **No checkpoint/resume.** An interrupted run restarts from scratch.
6. The template does not showcase the new capabilities (auth profiles, flows,
   flow-aware attacks, `FlowLoginProvider`).

**Constraint (user):** penpine is a *library you write code against*. All new
options are **config-in-code**, not CLI flags. The generated `main.py` drops its
`sys.argv` attack-override parsing.

## Overview

Three small **framework enablers** (reusable, tested) plus a **template rewrite**
(typed config, checkpoint, robust `main.py`, feature samples).

---

## Part 1 — Framework enablers

### 1a. Interruptible sync facades (the Ctrl+C fix)

Add a shared helper (new module `penpine/_sync.py`):

```python
def run_on_loop(loop, coro, *, poll=0.25):
    """Submit coro to a background loop and wait interruptibly.

    Polls the concurrent.futures result with a timeout so KeyboardInterrupt is
    delivered to the main thread; on interrupt, cancels the coroutine on the loop
    (propagating asyncio cancellation into the batch) and re-raises.
    """
    future = asyncio.run_coroutine_threadsafe(coro, loop)
    try:
        while True:
            try:
                return future.result(timeout=poll)
            except concurrent.futures.TimeoutError:
                continue
    except KeyboardInterrupt:
        future.cancel()          # run_coroutine_threadsafe future cancels the task
        raise
```

Rewire the three background-thread facades to use it, preserving the persistent
loop and connection reuse:
- `Runner.run_sync` (`penpine/attack/runner.py`)
- `Engine.send_sync` and `Engine.send_many_sync` (`penpine/transport/engine.py`)
- `SessionManager.send_sync` and its refresh `_sync` (`penpine/auth/manager.py`)

`Identity.send_sync` delegates to the manager, so it's covered transitively.
`FlowRunner.run_sync` already uses `asyncio.run` (Ctrl+C-clean) — left as is.

Cancellation is clean: the Runner's per-attempt guards catch `Exception`, not
`CancelledError` (a `BaseException`), so a cancel propagates out of the batch and
the `_sync` call raises `CancelledError`/`KeyboardInterrupt` rather than silently
finishing.

### 1b. `configure_logging` gains a file sink

```python
def configure_logging(level=logging.INFO, *, log_file=None) -> logging.Logger:
```

When `log_file` is set, attach a second handler — a `FileHandler(log_file)` with a
**plain** (non-ANSI) formatter — alongside the existing colored console handler.
`level` accepts an int or a level name string (`"DEBUG"`, `"INFO"`, …) for
config-friendliness. Idempotent (no duplicate handlers on repeat calls).

### 1c. `RequestLogInterceptor`

A reusable transport `Interceptor` (new, in `penpine/transport/interceptor.py` or a
sibling), logging one line per request/response:

```python
class RequestLogInterceptor(Interceptor):
    def __init__(self, *, level=logging.INFO): ...
    async def before_send(self, request): ...        # records start time
    async def after_receive(self, request, response):
        # "GET /path -> 200 (123 ms)" at the configured level
        ...
```

Attached via the existing `Engine(interceptors=[...])` seam. Logged under a
`penpine.transport` logger so `configure_logging` captures it. This makes "notify
on each request" first-class and toggleable, and pairs with `LOG_LEVEL` for depth.

Exported where appropriate (`penpine.transport.__init__`, and re-exported at
top-level if the other interceptor-ish public types are).

---

## Part 2 — Typed, config-driven `config.py.tmpl`

```python
from penpine import AttackType

TARGET_SCHEME = "http"                 # "http" | "https"
TARGET_HOST = "127.0.0.1:8000"         # host or host:port

ATTACKS = [AttackType.SQLI, AttackType.XSS]   # typed; no strings, no from_str
CONCURRENCY = 10
PROXY = None                            # e.g. "http://127.0.0.1:8080"
TLS_VERIFY = False

# Logging (config-in-code; no CLI flags)
LOG_LEVEL = "INFO"                      # "DEBUG" | "INFO" | "WARNING" | ...
LOG_REQUESTS = True                     # one line per request (RequestLogInterceptor)
LOG_FILE = None                         # e.g. "run.log" to also write to a file

# Checkpoint / resume
RESUME = True                           # skip work items already marked done
CHECKPOINT_FILE = "checkpoint.json"
# to start over, set RESUME = False (ignores + overwrites the checkpoint)
```

## Part 3 — Checkpoint / resume (`checkpoint.py.tmpl`, in the generated project)

A small, self-contained, user-editable helper shipped as a template file:

```python
class Checkpoint:
    def __init__(self, path, *, resume=True):
        self._path = Path(path)
        self._done = set()
        if resume and self._path.exists():
            self._done = set(json.loads(self._path.read_text()).get("done", []))
        elif not resume:
            self._path.unlink(missing_ok=True)   # overwrite / start fresh

    def is_done(self, item) -> bool: ...
    def mark_done(self, item) -> None:           # flush to disk immediately
        self._done.add(item)
        self._path.write_text(json.dumps({"done": sorted(self._done)}, indent=2))
```

- **Work item** = a stable string id. In the default `main.py` it's
  `attack_type.value` (one item per entry in `ATTACKS`). The helper is generic, so
  a user can key by request, flow, or `f"{request}:{attack}"`.
- Each completed item is flushed immediately, so an interrupt (now deliverable)
  leaves a valid checkpoint. Interrupt *mid-item* → item not marked → re-runs on
  resume (a `Runner` batch is effectively atomic).
- `RESUME = False` deletes the checkpoint up front and runs everything.

## Part 4 — Generated `main.py.tmpl` + feature samples

### `main.py` (the one robust, runnable, inert-by-default entry point)

Wires everything from config, no `sys.argv`:

```python
import config
from checkpoint import Checkpoint
from penpine import Engine, Runner, configure_logging, get_logger
from penpine.transport import RequestLogInterceptor
...

def main():
    configure_logging(level=config.LOG_LEVEL, log_file=config.LOG_FILE)
    log = get_logger("project")
    interceptors = [RequestLogInterceptor()] if config.LOG_REQUESTS else []
    engine = Engine(tls=..., proxy=..., interceptors=interceptors)
    runner = Runner(sender=engine, max_concurrency=config.CONCURRENCY)
    cp = Checkpoint(config.CHECKPOINT_FILE, resume=config.RESUME)
    request = load_request()
    try:
        for attack in config.ATTACKS:                 # typed AttackType values
            item = attack.value
            if cp.is_done(item):
                log.info("skip %s (checkpointed)", item); continue
            report = runner.run_sync(request, attack=attack)
            print(f"== {item} == {report.summary()}")
            for f in report.findings:
                print(f"  [{f.confidence.name}] {f.point.expr} -> {f.evidence}")
            cp.mark_done(item)
    except KeyboardInterrupt:
        log.warning("interrupted; progress saved to %s (rerun to resume)",
                    config.CHECKPOINT_FILE)
    finally:
        runner.close()
```

### Feature samples (alongside the existing `custom_*` examples)

Runnable, canonical examples of the new capabilities (mirroring how `samples/`
documents every extension seam):
- `auth_profile.py` — `AuthProfile` (`JsonLoginProvider` + `BearerAuth`) →
  authenticated `Runner(sender=identity)`.
- `flow_basic.py` — a multi-step `Flow` (login → act → confirm) with
  capture/templating and `run_sync`.
- `flow_attacks.py` — `FlowRunner` with `SkipStepModule` / `CrossUserModule`
  (typed, class-passing, multi-module list).
- `flow_login.py` — `FlowLoginProvider` for a multi-request login.

The generated `docs/README.md.tmpl` gets short sections pointing at these.

## Testing

- **Framework (unit, no network):**
  - `run_on_loop`: returns a coroutine's result; a `KeyboardInterrupt` raised while
    waiting cancels the coroutine and propagates (simulate via a fake loop/injected
    interrupt). Regression: `Runner.run_sync`/`Engine.send_sync`/`SessionManager.send_sync`
    still return results normally.
  - `configure_logging(log_file=...)`: writes records to the file; string level
    names accepted; idempotent.
  - `RequestLogInterceptor`: `after_receive` emits one record with method/target/
    status; passes the response through unchanged.
- **Scaffold:** existing `tests/cli/` (scaffold, generated-main, samples-run)
  extended so the rendered `config.py`/`checkpoint.py`/`main.py` import and run
  against fakes; the new samples are covered by `test_samples_run`. The opt-in
  `slow` e2e venv test still builds and runs the project.
- Whole suite green; ruff + mypy clean.

## Non-goals

- No CLI flags (config-in-code only).
- No fine-grained (mid-batch) resume — checkpoint granularity is the work item.
- `FlowRunner.run_sync` is already Ctrl+C-clean; not rewired.
- No change to attack semantics or the Flow engine.

## Rollout

One implementation plan, ordered: (1) framework enablers (interruptible sync,
file logging, `RequestLogInterceptor`) with tests; (2) template files (typed
`config.py`, `checkpoint.py`, rewritten `main.py`); (3) feature samples + generated
README; (4) scaffold-test updates + full regression.
