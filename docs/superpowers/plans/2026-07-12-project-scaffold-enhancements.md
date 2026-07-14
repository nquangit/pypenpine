# Project Scaffold Enhancements — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `penpine new` projects robust and current — interruptible (Ctrl+C) sync runs, file + per-request logging, a resumable checkpoint, typed config, and samples for flows / flow-attacks / flow-login.

**Architecture:** Add three small reusable framework enablers (an interruptible `run_on_loop` bridge, a file sink for `configure_logging`, and a `RequestLogInterceptor`), then rewrite the scaffold templates to be config-in-code (typed `AttackType`, logging/checkpoint options), add a `checkpoint.py`, and add feature samples. No CLI flags.

**Tech Stack:** Python 3.11+, stdlib `asyncio`/`logging`/`contextvars`, pytest (`asyncio_mode=auto`), fakes (no network).

## Global Constraints

- Python 3.11+; no third-party HTTP client. Exceptions derive from `penpine.exceptions.PenpineError`.
- Config-in-code only — NO CLI flags anywhere in the generated project.
- Every async entry point keeps its `*_sync` facade; the `_sync` facades must be interruptible by `KeyboardInterrupt`.
- Package ships `py.typed` — keep public annotations complete.
- Templates under `penpine/cli/templates/` are excluded from ruff, but must be valid, offline-runnable Python (the `tests/cli` suite executes them).
- Tests use fakes; no sockets. Ruff lint+format gating; mypy must stay clean. Commits use `--no-gpg-sign`.
- Report/finding semantics unchanged; `Flow.run()` unchanged.

## Key current-code facts (use exactly)

- Broken (non-interruptible) sync facades — all do `asyncio.run_coroutine_threadsafe(coro, self._loop).result()` on a daemon-thread loop: `Runner.run_sync` (`penpine/attack/runner.py`), `Engine.send_sync`/`send_many_sync` (`penpine/transport/engine.py`), `SessionManager.send_sync`/`send_many_sync` (`penpine/auth/manager.py`). `Identity.send_sync` delegates to the manager. `FlowRunner.run_sync` uses `asyncio.run` (already fine — do NOT touch).
- `Interceptor` base (`penpine/transport/interceptor.py`): `async before_send(request)`, `async after_receive(request, response)`. `Engine(interceptors=(...))` applies `before_send` in order, `after_receive` reversed. Both run within the same send task.
- `configure_logging(level=logging.INFO)` (`penpine/logging.py`) attaches one colored `StreamHandler`; `_ColorFormatter` adds ANSI. `get_logger(name)` returns `logging.getLogger(name)`.
- `AttackType` is exported from `penpine` (top level) and `penpine.attack.types`; `Flow`/`Step`/`Runner`/`Engine`/`FlowRunner`/`AuthProfile`/`configure_logging`/`get_logger` from `penpine`; `SkipStepModule`/`CrossUserModule` from `penpine.attack.flow`; `FlowLoginProvider`/`JsonLoginProvider`/`BearerAuth` from `penpine.auth`.
- Scaffold: `render_project` renders `*.tmpl` (variable-substituted, suffix dropped) and copies other files verbatim; `{{ project_name }}` etc. are the vars. Templates live in `penpine/cli/templates/project/`.
- Scaffold tests: `tests/cli/test_generated_main.py` monkeypatches `main.build_runner` and calls `main.main(...)`; `tests/cli/test_samples_run.py` runs `python -m samples.<name>` and asserts exit 0 (and, for `FINDING_SAMPLES`, a finding).

---

### Task 1: Interruptible sync facades (`run_on_loop`)

**Files:**
- Create: `penpine/_sync.py`
- Modify: `penpine/attack/runner.py`, `penpine/transport/engine.py`, `penpine/auth/manager.py`
- Test: `tests/test_sync.py`

**Interfaces:**
- Produces: `penpine._sync.wait_interruptible(future, *, poll=0.25)` and `run_on_loop(loop, coro, *, poll=0.25)`. Both facades call `run_on_loop(self._loop, <coro>)`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_sync.py`:

```python
import asyncio
import concurrent.futures
import threading

import pytest

from penpine._sync import run_on_loop, wait_interruptible


class _FakeFuture:
    def __init__(self, script):
        self._script = list(script)
        self._i = 0
        self.cancelled = False

    def result(self, timeout=None):
        item = self._script[min(self._i, len(self._script) - 1)]
        self._i += 1
        if isinstance(item, BaseException):
            raise item
        return item

    def cancel(self):
        self.cancelled = True


def test_wait_interruptible_returns_after_timeouts():
    f = _FakeFuture([concurrent.futures.TimeoutError(), concurrent.futures.TimeoutError(), 42])
    assert wait_interruptible(f, poll=0.01) == 42
    assert f.cancelled is False


def test_wait_interruptible_cancels_and_reraises_on_keyboardinterrupt():
    f = _FakeFuture([KeyboardInterrupt()])
    with pytest.raises(KeyboardInterrupt):
        wait_interruptible(f, poll=0.01)
    assert f.cancelled is True


def test_run_on_loop_returns_result_from_background_loop():
    loop = asyncio.new_event_loop()
    t = threading.Thread(target=loop.run_forever, daemon=True)
    t.start()
    try:
        async def work():
            await asyncio.sleep(0)
            return "ok"

        assert run_on_loop(loop, work(), poll=0.01) == "ok"
    finally:
        loop.call_soon_threadsafe(loop.stop)
        t.join(timeout=2)
        loop.close()
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_sync.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'penpine._sync'`.

- [ ] **Step 3: Implement the helper**

Create `penpine/_sync.py`:

```python
"""Interruptible bridge from a sync caller to a background asyncio loop.

`future.result()` on a background-thread loop is an uninterruptible wait, so
KeyboardInterrupt is never delivered until the coroutine finishes. Polling with
a timeout keeps the main thread responsive to signals; on interrupt we cancel
the coroutine on the loop and re-raise.
"""

from __future__ import annotations

import asyncio
import concurrent.futures


def wait_interruptible(future, *, poll: float = 0.25):
    try:
        while True:
            try:
                return future.result(timeout=poll)
            except concurrent.futures.TimeoutError:
                continue
    except (KeyboardInterrupt, SystemExit):
        future.cancel()
        raise


def run_on_loop(loop, coro, *, poll: float = 0.25):
    future = asyncio.run_coroutine_threadsafe(coro, loop)
    return wait_interruptible(future, poll=poll)
```

- [ ] **Step 4: Rewire the three facades**

In `penpine/attack/runner.py`, add `from penpine._sync import run_on_loop` and replace `run_sync`:

```python
    def run_sync(self, request, **kwargs):
        self._ensure_loop()
        return run_on_loop(self._loop, self.run(request, **kwargs))
```

In `penpine/transport/engine.py`, add `from penpine._sync import run_on_loop` and replace both:

```python
    def send_sync(self, request):
        self._ensure_loop()
        return run_on_loop(self._loop, self.send(request))

    def send_many_sync(self, requests, *, return_exceptions=False):
        self._ensure_loop()
        return run_on_loop(
            self._loop, self.send_many(requests, return_exceptions=return_exceptions)
        )
```

In `penpine/auth/manager.py`, add `from penpine._sync import run_on_loop` and replace both:

```python
    def send_sync(self, request, **kwargs):
        self._ensure_loop()
        return run_on_loop(self._loop, self.send(request, **kwargs))

    def send_many_sync(self, requests, **kwargs):
        self._ensure_loop()
        return run_on_loop(self._loop, self.send_many(requests, **kwargs))
```

- [ ] **Step 5: Run the tests**

Run: `pytest tests/test_sync.py tests/attack/test_runner_sync.py tests/transport/test_engine_sync.py tests/auth/test_manager_sync.py -v`
Expected: PASS (new sync tests + existing sync-facade tests unchanged — the normal path returns identically).

- [ ] **Step 6: Lint + type check**

Run: `ruff check penpine/_sync.py penpine/attack/runner.py penpine/transport/engine.py penpine/auth/manager.py tests/test_sync.py && ruff format --check penpine/_sync.py tests/test_sync.py && mypy penpine`
Expected: clean.

- [ ] **Step 7: Commit**

```bash
git add penpine/_sync.py penpine/attack/runner.py penpine/transport/engine.py penpine/auth/manager.py tests/test_sync.py
git commit --no-gpg-sign -m "fix: make sync facades interruptible (Ctrl+C stops a run)"
```

---

### Task 2: `configure_logging` file sink + string levels

**Files:**
- Modify: `penpine/logging.py`
- Test: `tests/test_logging_file.py`

**Interfaces:**
- Produces: `configure_logging(level=logging.INFO, *, log_file=None)`. `level` accepts an int or a level-name string. `log_file` (path) adds a plain (non-ANSI) `FileHandler`. Idempotent (no duplicate console/file handlers across calls).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_logging_file.py`:

```python
import logging

import pytest

from penpine.logging import configure_logging, get_logger

_ROOT = "penpine"


@pytest.fixture(autouse=True)
def _clean_penpine_logger():
    log = logging.getLogger(_ROOT)
    saved = log.handlers[:]
    log.handlers.clear()
    yield
    log.handlers.clear()
    log.handlers.extend(saved)


def test_configure_logging_accepts_level_name():
    log = configure_logging(level="WARNING")
    assert log.level == logging.WARNING


def test_configure_logging_writes_to_file(tmp_path):
    path = tmp_path / "run.log"
    configure_logging(level="DEBUG", log_file=str(path))
    get_logger("penpine.demo").debug("hello-file")
    for h in logging.getLogger(_ROOT).handlers:
        h.flush()
    assert "hello-file" in path.read_text()


def test_configure_logging_is_idempotent(tmp_path):
    path = tmp_path / "run.log"
    configure_logging(log_file=str(path))
    n = len(logging.getLogger(_ROOT).handlers)
    configure_logging(log_file=str(path))
    assert len(logging.getLogger(_ROOT).handlers) == n
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_logging_file.py -v`
Expected: FAIL — `configure_logging()` has no `log_file` keyword (TypeError).

- [ ] **Step 3: Implement**

In `penpine/logging.py`, replace `configure_logging` with:

```python
def configure_logging(level: int | str = logging.INFO, *, log_file: str | None = None) -> logging.Logger:
    """Attach a colored console handler (and optionally a plain file handler) to
    the penpine root logger. `level` may be an int or a level-name string.
    Idempotent: repeat calls do not duplicate handlers."""
    log = logging.getLogger(_ROOT_NAME)
    log.setLevel(level)
    log.propagate = False

    if not any(getattr(h, "_penpine_console", False) for h in log.handlers):
        console = logging.StreamHandler()
        console._penpine_console = True
        console.setFormatter(_ColorFormatter("%(levelname)s %(name)s: %(message)s"))
        log.addHandler(console)

    if log_file is not None:
        target = str(log_file)
        if not any(getattr(h, "_penpine_file", None) == target for h in log.handlers):
            file_handler = logging.FileHandler(target)
            file_handler._penpine_file = target
            file_handler.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
            log.addHandler(file_handler)

    return log
```

- [ ] **Step 4: Run the tests**

Run: `pytest tests/test_logging_file.py tests/test_logging.py -v`
Expected: PASS (new file tests + existing logging tests still green — the console-handler behavior is unchanged).

- [ ] **Step 5: Lint + type check**

Run: `ruff check penpine/logging.py tests/test_logging_file.py && ruff format --check penpine/logging.py tests/test_logging_file.py && mypy penpine`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add penpine/logging.py tests/test_logging_file.py
git commit --no-gpg-sign -m "feat(logging): add file sink and string level names to configure_logging"
```

---

### Task 3: `RequestLogInterceptor`

**Files:**
- Modify: `penpine/transport/interceptor.py`, `penpine/transport/__init__.py`
- Test: `tests/transport/test_request_log.py`

**Interfaces:**
- Consumes: `Interceptor`, `get_logger`.
- Produces: `RequestLogInterceptor(*, level=logging.INFO, logger_name="penpine.transport")` — logs one line per request/response (`"<method> <target> -> <status> (<ms> ms)"`) and returns the response unchanged. Per-request timing via a `contextvars.ContextVar` (per-task, concurrency-safe). Exported from `penpine.transport`.

- [ ] **Step 1: Write the failing test**

Create `tests/transport/test_request_log.py`:

```python
import logging

from penpine.core.message import Request
from penpine.core.parse.http_parser import parse_response
from penpine.transport.interceptor import RequestLogInterceptor


async def test_request_log_interceptor_logs_line_and_passes_through(caplog):
    ic = RequestLogInterceptor()
    req = Request.from_url("http://t/path?x=1")
    resp = parse_response(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nok")
    with caplog.at_level(logging.INFO, logger="penpine.transport"):
        await ic.before_send(req)
        out = await ic.after_receive(req, resp)
    assert out is resp  # passthrough, unchanged
    msgs = [r.getMessage() for r in caplog.records]
    assert any("GET" in m and "-> 200" in m for m in msgs)


async def test_request_log_interceptor_reexported():
    from penpine.transport import RequestLogInterceptor as Exported

    assert Exported is RequestLogInterceptor
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/transport/test_request_log.py -v`
Expected: FAIL — `ImportError: cannot import name 'RequestLogInterceptor'`.

- [ ] **Step 3: Implement**

In `penpine/transport/interceptor.py`, add the imports at the top (after `from __future__ import annotations`):

```python
import contextvars
import logging
import time

from penpine.logging import get_logger

_request_start = contextvars.ContextVar("penpine_request_start")
```

Append at the end of the file:

```python
class RequestLogInterceptor(Interceptor):
    """Log one line per request/response, e.g. `GET /path -> 200 (12 ms)`."""

    def __init__(self, *, level: int = logging.INFO, logger_name: str = "penpine.transport"):
        self._level = level
        self._log = get_logger(logger_name)

    async def before_send(self, request):
        _request_start.set(time.perf_counter())
        return request

    async def after_receive(self, request, response):
        try:
            elapsed_ms = (time.perf_counter() - _request_start.get()) * 1000
            timing = f" ({elapsed_ms:.0f} ms)"
        except LookupError:
            timing = ""
        status = getattr(response, "status_code", "?")
        self._log.log(self._level, "%s %s -> %s%s", request.method, request.target, status, timing)
        return response
```

In `penpine/transport/__init__.py`, add `RequestLogInterceptor` to the `from penpine.transport.interceptor import ...` line and to `__all__`.

- [ ] **Step 4: Run the test**

Run: `pytest tests/transport/test_request_log.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Lint + type check**

Run: `ruff check penpine/transport && ruff format --check penpine/transport && mypy penpine`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add penpine/transport/interceptor.py penpine/transport/__init__.py tests/transport/test_request_log.py
git commit --no-gpg-sign -m "feat(transport): add RequestLogInterceptor for per-request logging"
```

---

### Task 4: Template core — typed config, checkpoint, rewritten main

**Files:**
- Modify: `penpine/cli/templates/project/config.py.tmpl`, `penpine/cli/templates/project/main.py.tmpl`
- Create: `penpine/cli/templates/project/checkpoint.py`
- Modify: `tests/cli/test_generated_main.py`

**Interfaces:**
- Produces: a config-driven, typed generated project. `main.build_runner()` kept as a test seam; `main.main()` takes no args and iterates `config.ATTACKS` (typed `AttackType`) with a `Checkpoint`.

- [ ] **Step 1: Update the generated-main test first (expresses the new shape)**

In `tests/cli/test_generated_main.py`, replace the `_RUN_CHECK` string and its usage so it drives the new config-driven `main.main()` (no argv), sets typed attacks, and disables resume:

```python
_RUN_CHECK = """
import config, main
from penpine import AttackType
from penpine.attack.runner import Runner
from penpine.core.parse.http_parser import parse_response


class _FakeSender:
    async def send(self, request):
        return parse_response(b"HTTP/1.1 200 OK\\r\\nContent-Length: 2\\r\\n\\r\\nok")


# run the attack path with a fake sender (no sockets)
main.build_runner = lambda: Runner(sender=_FakeSender(), max_concurrency=2)
config.TARGET_HOST = "example.test"
config.ATTACKS = [AttackType.SQLI]
config.RESUME = False          # ignore any checkpoint from a prior run
main.main()
print("RUN_OK")
"""
```

(Leave `test_load_request_sets_meta` unchanged — `load_request()` keeps its signature.)

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/cli/test_generated_main.py::test_generated_main_runs_attack_path -v`
Expected: FAIL — the current `main.main` requires `argv`/uses `AttackType.from_str` and there is no `config.RESUME`/checkpoint, so importing/running the new-shape check against the OLD template fails (AttributeError/TypeError).

- [ ] **Step 3: Write the typed `config.py.tmpl`**

Replace `penpine/cli/templates/project/config.py.tmpl` with:

```python
"""{{ project_name }} — configuration (pure Python; no CLI flags, no config files)."""

from penpine import AttackType

# Target the sample request is sent to. CHANGE THESE to a system you are
# AUTHORIZED to test. Defaults to a local listener so a blind run is inert.
TARGET_SCHEME = "http"          # "http" or "https"  (https makes the Engine use TLS)
TARGET_HOST = "127.0.0.1:8000"  # host or host:port

# Attacks to run by default — typed AttackType values (not strings).
ATTACKS = [AttackType.SQLI, AttackType.XSS]

# Max concurrent in-flight requests.
CONCURRENCY = 10

# Optional upstream proxy, e.g. "http://127.0.0.1:8080" for Burp/ZAP. None disables.
PROXY = None

# Verify TLS certificates (only applies when TARGET_SCHEME == "https").
TLS_VERIFY = False

# --- Logging (config-in-code) ---
LOG_LEVEL = "INFO"      # "DEBUG" | "INFO" | "WARNING" | "ERROR"
LOG_REQUESTS = True     # log one line per request via RequestLogInterceptor
LOG_FILE = None         # e.g. "run.log" to ALSO write logs to a file

# --- Checkpoint / resume ---
RESUME = True                    # skip work items already recorded as done
CHECKPOINT_FILE = "checkpoint.json"
# To start over from scratch, set RESUME = False (ignores + overwrites the checkpoint).
```

- [ ] **Step 4: Write `checkpoint.py`**

Create `penpine/cli/templates/project/checkpoint.py` (plain file, copied verbatim — no template vars):

```python
"""Resumable checkpoint: record completed work items to a JSON file.

Used by main.py to skip work already done on a rerun. Generic — key items
however you like (attack name, request id, flow name, ...).
"""

from __future__ import annotations

import json
from pathlib import Path


class Checkpoint:
    def __init__(self, path, *, resume=True):
        self._path = Path(path)
        self._done = set()
        if not resume:
            self._path.unlink(missing_ok=True)  # start fresh / overwrite
        elif self._path.exists():
            try:
                self._done = set(json.loads(self._path.read_text()).get("done", []))
            except (ValueError, OSError):
                self._done = set()

    def is_done(self, item) -> bool:
        return str(item) in self._done

    def mark_done(self, item) -> None:
        self._done.add(str(item))
        # Flush immediately so an interrupt leaves a valid checkpoint.
        self._path.write_text(json.dumps({"done": sorted(self._done)}, indent=2))
```

- [ ] **Step 5: Rewrite `main.py.tmpl`**

Replace `penpine/cli/templates/project/main.py.tmpl` with:

```python
"""{{ project_name }} — penpine engagement entry point.

Config-driven (edit config.py); no CLI arguments. Runs config.ATTACKS against
requests/sample.http with per-request logging, a resumable checkpoint, and clean
Ctrl+C handling.

    python main.py            # runs config.ATTACKS; resumes from checkpoint.json
    # set RESUME = False in config.py to start over
"""

import config
from checkpoint import Checkpoint

from penpine import Engine, Runner, configure_logging, get_logger
from penpine.attack.modules import register_builtins
from penpine.core.message import Request
from penpine.transport import RequestLogInterceptor
from penpine.transport.proxy import ProxyConfig
from penpine.transport.tls import TLSConfig

from samples.custom_module import register as register_custom

# Child of the "penpine" logger so configure_logging's handlers + level apply.
log = get_logger("penpine.project")


def load_request():
    with open("requests/sample.http", "rb") as fh:
        raw = fh.read()
    raw = raw.replace(b"__TARGET_HOST__", config.TARGET_HOST.encode())
    host, _, port_s = config.TARGET_HOST.partition(":")
    port = int(port_s) if port_s else (443 if config.TARGET_SCHEME == "https" else 80)
    return Request.from_raw(raw, scheme=config.TARGET_SCHEME, host=host, port=port)


def build_runner():
    engine_kw = {"tls": TLSConfig(verify=config.TLS_VERIFY)}
    if config.PROXY:
        engine_kw["proxy"] = ProxyConfig.from_url(config.PROXY)
    if config.LOG_REQUESTS:
        engine_kw["interceptors"] = [RequestLogInterceptor()]
    return Runner(sender=Engine(**engine_kw), max_concurrency=config.CONCURRENCY)


def main():
    configure_logging(level=config.LOG_LEVEL, log_file=config.LOG_FILE)
    register_builtins()
    register_custom()
    request = load_request()
    runner = build_runner()
    checkpoint = Checkpoint(config.CHECKPOINT_FILE, resume=config.RESUME)
    try:
        for attack in config.ATTACKS:
            item = attack.value
            if checkpoint.is_done(item):
                log.info("skip %s (already done)", item)
                continue
            report = runner.run_sync(request, attack=attack)
            print(f"\n== {item} ==  {report.summary()}")
            for finding in report.findings:
                print(f"  [{finding.confidence.name}] {finding.point.expr} -> {finding.evidence}")
            checkpoint.mark_done(item)
    except KeyboardInterrupt:
        log.warning("interrupted; progress saved to %s (rerun to resume)", config.CHECKPOINT_FILE)
    finally:
        runner.close()


if __name__ == "__main__":
    main()
```

- [ ] **Step 6: Run the generated-main tests**

Run: `pytest tests/cli/test_generated_main.py -v`
Expected: PASS (both `test_load_request_sets_meta` and `test_generated_main_runs_attack_path`).

- [ ] **Step 7: Commit**

```bash
git add penpine/cli/templates/project/config.py.tmpl penpine/cli/templates/project/main.py.tmpl penpine/cli/templates/project/checkpoint.py tests/cli/test_generated_main.py
git commit --no-gpg-sign -m "feat(cli): typed config + checkpoint + robust config-driven main.py"
```

---

### Task 5: Feature samples (flow, flow-attacks, flow-login)

**Files:**
- Create: `penpine/cli/templates/project/samples/flow_basic.py`, `samples/flow_attacks.py`, `samples/flow_login.py`
- Modify: `penpine/cli/templates/project/docs/README.md.tmpl`, `tests/cli/test_samples_run.py`

**Interfaces:**
- Produces: three offline-runnable samples showcasing `Flow`, `FlowRunner` + `SkipStepModule`, and `FlowLoginProvider`. All exit 0 under `python -m samples.<name>`.

- [ ] **Step 1: Add the samples to the runner test first**

In `tests/cli/test_samples_run.py`, add the three names to `SAMPLES`:

```python
SAMPLES = [
    "custom_payload",
    "custom_validator",
    "custom_module",
    "custom_rule",
    "custom_auth",
    "custom_interceptor",
    "data_sharing",
    "byo_test_cases",
    "flow_basic",
    "flow_attacks",
    "flow_login",
]
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/cli/test_samples_run.py -v`
Expected: FAIL — `python -m samples.flow_basic` (etc.) fails with `No module named samples.flow_basic`.

- [ ] **Step 3: Write `flow_basic.py`**

Create `penpine/cli/templates/project/samples/flow_basic.py`:

```python
"""A multi-step Flow with capture + templating (offline, no sockets).

login -> capture token -> next step uses {{token}}.
    python -m samples.flow_basic
"""
from penpine import Flow, Step
from penpine.core.message import Request
from penpine.core.parse.http_parser import parse_response
from penpine.data.extract import Extract


class _FakeActor:
    def __init__(self):
        self.sent = []

    async def send(self, request):
        self.sent.append(request)
        if request.target.endswith("/login"):
            body = b'{"token": "abc123"}'
            return parse_response(
                b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: %d\r\n\r\n%s"
                % (len(body), body)
            )
        return parse_response(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nok")


def demo():
    flow = Flow(
        actor=_FakeActor(),
        steps=[
            Step("login", request=Request.from_url("http://target.example/login"),
                 capture=[Extract("token", json="$.token")]),
            Step("act", request=Request.from_url("http://target.example/do?tok={{token}}")),
        ],
    )
    result = flow.run_sync()
    print("flow:", result.summary(), "token=", result.context.get("token"))
    return result


if __name__ == "__main__":
    demo()
```

- [ ] **Step 4: Write `flow_attacks.py`**

Create `penpine/cli/templates/project/samples/flow_attacks.py`:

```python
"""Flow-structural attacks via FlowRunner (offline, no sockets).

SkipStepModule drops each step and checks whether the goal step still succeeds
(broken access control). Pass a module CLASS (no parens), or a list of modules.
    python -m samples.flow_attacks
"""
from penpine import Flow, FlowRunner, Step
from penpine.attack.flow import SkipStepModule
from penpine.core.message import Request
from penpine.core.parse.http_parser import parse_response


class _FakeActor:
    def __init__(self, name="user"):
        self.name = name
        self.sent = []

    async def send(self, request):
        self.sent.append(request)
        return parse_response(b"HTTP/1.1 200 OK\r\nContent-Length: 4\r\n\r\ndone")


def demo():
    flow = Flow(
        actor=_FakeActor(),
        steps=[
            Step("login", request=Request.from_url("http://target.example/login")),
            Step("action", request=Request.from_url("http://target.example/action")),
            Step("confirm", request=Request.from_url("http://target.example/confirm")),
        ],
    )
    report = FlowRunner().run_sync(flow, module=SkipStepModule)  # class, no parens
    print("skip-step:", report.summary())
    for finding in report.findings:
        print(f"  {finding.attack_type} {finding.target} -> {finding.evidence}")
    return report


if __name__ == "__main__":
    demo()
```

- [ ] **Step 5: Write `flow_login.py`**

Create `penpine/cli/templates/project/samples/flow_login.py`:

```python
"""Multi-request login via FlowLoginProvider (offline, no sockets).

The login is a Flow (fetch a CSRF token, then submit); FlowLoginProvider runs it
and maps captured context to a Session. Bundle it into an AuthProfile as usual.
    python -m samples.flow_login
"""
import asyncio

from penpine.auth import BearerAuth, FlowLoginProvider
from penpine.auth.profile import AuthProfile
from penpine.core.message import Request
from penpine.core.parse.http_parser import parse_response
from penpine.data.extract import Extract
from penpine.flow import Flow, Step


class _FakeEngine:
    async def send(self, request):
        if "csrf=" in request.target:  # the submit step
            body = b'{"access_token": "tok-9"}'
        else:  # the initial page fetch
            body = b'{"csrf": "C1"}'
        return parse_response(
            b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: %d\r\n\r\n%s"
            % (len(body), body)
        )


def demo():
    login = Flow(steps=[
        Step("page", request=Request.from_url("http://target.example/login"),
             capture=[Extract("csrf", json="$.csrf")]),
        Step("submit", request=Request.from_url("http://target.example/login?csrf={{csrf}}"),
             capture=[Extract("tok", json="$.access_token")]),
    ])
    provider = FlowLoginProvider(login, token_key="tok")
    profile = AuthProfile(name="demo", provider=provider, scheme=BearerAuth())
    session = asyncio.run(provider.login(_FakeEngine()))
    print("logged in via flow; token =", session.token, "| profile:", profile.name)
    return session


if __name__ == "__main__":
    demo()
```

- [ ] **Step 6: Add a README section**

Append this section to `penpine/cli/templates/project/docs/README.md.tmpl`:

````markdown
## Running

Everything is configured in `config.py` (no CLI flags):

- `ATTACKS` — typed `AttackType` values to run (e.g. `AttackType.SQLI`).
- `LOG_LEVEL` / `LOG_REQUESTS` / `LOG_FILE` — console level, per-request lines, and an optional log file.
- `RESUME` / `CHECKPOINT_FILE` — resume from the last checkpoint; set `RESUME = False` to start over.

`python main.py` runs the attacks, logs each request, checkpoints after each, and
stops cleanly on Ctrl+C (rerun to resume).

### Feature samples

```
python -m samples.flow_basic     # a multi-step Flow with capture + templating
python -m samples.flow_attacks   # flow-structural attacks (skip-a-step) via FlowRunner
python -m samples.flow_login     # multi-request login via FlowLoginProvider
```

(plus the existing `custom_*` and `data_sharing` extension examples.)
````

- [ ] **Step 7: Run the samples tests**

Run: `pytest tests/cli/test_samples_run.py -v`
Expected: PASS (all samples, including the three new ones, run offline and exit 0).

- [ ] **Step 8: Commit**

```bash
git add penpine/cli/templates/project/samples/flow_basic.py penpine/cli/templates/project/samples/flow_attacks.py penpine/cli/templates/project/samples/flow_login.py penpine/cli/templates/project/docs/README.md.tmpl tests/cli/test_samples_run.py
git commit --no-gpg-sign -m "feat(cli): add flow / flow-attacks / flow-login samples to the scaffold"
```

---

### Task 6: Full regression

**Files:** none (verification only).

- [ ] **Step 1: Whole suite**

Run: `pytest -q`
Expected: all pass (existing + new). Fix any regression before proceeding.

- [ ] **Step 2: Opt-in slow e2e scaffold test**

Run: `pytest -m slow tests/cli/test_e2e_venv.py -q`
Expected: PASS — it builds a real venv and runs the generated project end to end (this exercises the rewritten `main.py`, checkpoint, and logging for real). If the environment blocks network/venv, note it and rely on the offline suite.

- [ ] **Step 3: Gates**

Run: `ruff check . && ruff format --check . && mypy penpine`
Expected: ruff clean; mypy `Success`.

- [ ] **Step 4: Commit (if any regression fixes were needed)**

```bash
git add -A
git commit --no-gpg-sign -m "test: full regression for scaffold enhancements" || echo "nothing to commit"
```

---

## Notes for the implementer

- **The Ctrl+C fix works even if `future.cancel()` cannot stop an already-running task** — the polling re-delivers `KeyboardInterrupt` to the main thread, which re-raises and lets the script exit (the loop thread is a daemon). Cancellation is best-effort cleanup. Do not change the daemon-loop design.
- **`RequestLogInterceptor` timing uses a `ContextVar`** so concurrent requests each get their own start time (interceptor instances are shared). `before_send` and `after_receive` run in the same send task, so the var correlates.
- **Templates are ruff-excluded** but must be valid, offline-runnable Python — the `tests/cli` suite executes them with fakes.
- **Keep `main.build_runner()` as a seam** — the generated-main test monkeypatches it to inject a fake sender.
- **`main.main()` takes no arguments** (config-driven). The old `argv` attack-override and `AttackType.from_str` are gone.
