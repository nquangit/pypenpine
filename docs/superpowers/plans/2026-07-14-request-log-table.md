# Request-Log Table Output Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Render the request stream as a compact, column-aligned table (one row per request, no logging chrome, folding URL column), with failed sends shown as a single `ERR` row via a new `on_error` interceptor hook, plus a plain audit line to the log file.

**Architecture:** Add an `on_error` hook to the `Interceptor` seam and dispatch it from `Engine.send`. Add a `RequestTableRenderer` to `penpine/render.py` that prints fixed-width aligned rows with a folding URL column. Rewrite `RequestLogInterceptor` to render rows (gated by log level) and emit a file-only audit record tagged `_penpine_request`; `configure_logging` filters that tag off the console handler.

**Tech Stack:** Python 3.11+, `rich>=13`, stdlib `logging`/`asyncio`/`contextvars`, pytest.

## Global Constraints

- Python 3.11+; new modules keep `from __future__ import annotations`.
- `penpine/render.py` stays a LEAF: imports only `rich` (+ stdlib). It must NOT import `penpine.transport`/`penpine.attack`/`penpine.logging`. `interceptor.py` imports FROM `render` (one direction) — no cycle.
- All dynamic text rendered through rich markup (method, URL, error summary) MUST be escaped via `rich.markup.escape`. `RequestTableRenderer` uses `rich.text.Text` for styled cells (Text is literal, not markup-parsed) and `escape(...)` for string cells.
- `RequestLogInterceptor.__init__` public signature stays `(*, level=logging.INFO, logger_name="penpine.transport")`.
- `configure_logging(level, *, log_file=None)` signature unchanged and idempotent (the `_penpine_console`/`_penpine_file` markers).
- The Engine's original exception MUST always re-raise after `on_error` (Runner-never-raises depends on it). Each `on_error` call is individually guarded so a bad hook cannot mask the error.
- Column widths: STATUS 4 (right), METHOD 7 (left), SIZE 8 (right), TIME 8 (right), URL flexible + `overflow="fold"`.
- Ruff lint + format gating. Commit with `git commit --no-gpg-sign`.

## File Structure

- `penpine/transport/interceptor.py` — MODIFY. Add `Interceptor.on_error`; rewrite `RequestLogInterceptor` (Task 1 adds the hook; Task 4 rewrites the logger).
- `penpine/transport/engine.py` — MODIFY. Dispatch `on_error` from `send()`.
- `penpine/render.py` — MODIFY. Add `RequestTableRenderer`; export it.
- `penpine/__init__.py` — MODIFY. Re-export `RequestTableRenderer`.
- `penpine/logging.py` — MODIFY. Filter `_penpine_request` records off the console handler.
- Tests: `tests/transport/test_on_error.py` (NEW), `tests/test_render.py`, `tests/test_logging.py`, `tests/transport/test_request_log.py` (MODIFY).

---

### Task 1: `on_error` interceptor hook + Engine dispatch

**Files:**
- Modify: `penpine/transport/interceptor.py` (base class only), `penpine/transport/engine.py:56-64`
- Test: `tests/transport/test_on_error.py`

**Interfaces:**
- Produces: `Interceptor.on_error(self, request, exc)` (async, default no-op); `Engine.send` fires `on_error` for each interceptor (reversed) on failure, then re-raises.

- [ ] **Step 1: Write the failing test**

Create `tests/transport/test_on_error.py`:
```python
import pytest

from penpine.core.message import Request
from penpine.core.parse.http_parser import parse_response
from penpine.transport.engine import Engine
from penpine.transport.interceptor import Interceptor


class _BoomConn:
    def __init__(self, host, port, **kwargs):
        self.host, self.port = host, port

    async def open(self):
        raise ConnectionRefusedError("refused")

    async def send_bytes(self, data):
        return None

    async def read_response(self, method="GET"):
        return parse_response(b"HTTP/1.1 200 OK\r\nContent-Length: 0\r\n\r\n")

    async def close(self):
        return None


class _OkConn(_BoomConn):
    async def open(self):
        return self


class _Recorder(Interceptor):
    def __init__(self, name, log):
        self.name, self.log = name, log

    async def on_error(self, request, exc):
        self.log.append((self.name, request, exc))


async def test_on_error_fires_in_reversed_order_and_reraises():
    log = []
    a, b = _Recorder("a", log), _Recorder("b", log)
    engine = Engine(connection_factory=_BoomConn, interceptors=[a, b])
    with pytest.raises(ConnectionRefusedError):
        await engine.send(Request.from_url("http://h/path"))
    # reversed order: b before a
    assert [name for name, _, _ in log] == ["b", "a"]
    # each got the request and the exception
    assert all(r.target == "/path" and isinstance(e, ConnectionRefusedError) for _, r, e in log)


async def test_on_error_hook_that_raises_does_not_mask_original():
    class _BadHook(Interceptor):
        async def on_error(self, request, exc):
            raise ValueError("hook blew up")

    engine = Engine(connection_factory=_BoomConn, interceptors=[_BadHook()])
    with pytest.raises(ConnectionRefusedError):  # original error, not ValueError
        await engine.send(Request.from_url("http://h/"))


async def test_success_still_returns_and_calls_after_receive():
    seen = []

    class _Watch(Interceptor):
        async def after_receive(self, request, response):
            seen.append(response.status_code)
            return response

    engine = Engine(connection_factory=_OkConn, interceptors=[_Watch()])
    resp = await engine.send(Request.from_url("http://h/"))
    assert resp.status_code == 200
    assert seen == [200]
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/transport/test_on_error.py -q`
Expected: FAIL (`on_error` not called — attribute exists as no-op but Engine never dispatches it, so the reversed-order assertion fails / `log` is empty).

- [ ] **Step 3: Add `on_error` to the `Interceptor` base**

In `penpine/transport/interceptor.py`, add to class `Interceptor` (after `after_receive`):
```python
    async def on_error(self, request, exc):
        """Called when a send ultimately fails (after retries). Default no-op.
        Must not raise."""
        return None
```

- [ ] **Step 4: Dispatch `on_error` from `Engine.send`**

In `penpine/transport/engine.py`, replace `send` (currently lines 56-64):
```python
    async def send(self, request):
        try:
            if self.timeouts.total:
                try:
                    return await asyncio.wait_for(self._send(request), self.timeouts.total)
                except TimeoutError as exc:
                    raise TotalTimeout(
                        f"send exceeded total timeout of {self.timeouts.total}s"
                    ) from exc
            return await self._send(request)
        except Exception as exc:
            for ic in reversed(self.interceptors):
                try:
                    await ic.on_error(request, exc)
                except Exception:
                    pass  # an error hook must never mask the original failure
            raise
```

- [ ] **Step 5: Run to verify it passes**

Run: `pytest tests/transport/test_on_error.py -q`
Expected: PASS (3 tests).

- [ ] **Step 6: Full suite + lint**

Run: `pytest tests/transport -q && ruff check penpine/transport/ tests/transport/test_on_error.py && ruff format penpine/transport/interceptor.py penpine/transport/engine.py tests/transport/test_on_error.py`
Expected: transport tests pass; ruff clean.

- [ ] **Step 7: Commit**

```bash
git add penpine/transport/interceptor.py penpine/transport/engine.py tests/transport/test_on_error.py
git commit --no-gpg-sign -m "feat(transport): add on_error interceptor hook, dispatched from Engine.send

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: `RequestTableRenderer` (aligned rows + folding URL)

**Files:**
- Modify: `penpine/render.py`, `penpine/__init__.py`
- Test: `tests/test_render.py`

**Interfaces:**
- Consumes: `_status_style`, `_truncate`, `escape`, `Console`, `Table`, `Text`, `console` (all present in `render.py`).
- Produces: `RequestTableRenderer(*, console=console)` with `.row(*, status, method, size, timing, url, failed=False) -> None`; prints a one-time dim header then aligned rows. Re-exported from `penpine`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_render.py`:
```python
from penpine.render import RequestTableRenderer


def _table_console():
    return Console(record=True, width=60)


def test_request_table_aligns_columns_and_shows_header_once():
    c = _table_console()
    r = RequestTableRenderer(console=c)
    r.row(status=200, method="GET", size="1.2 kB", timing="12 ms", url="/aaa")
    r.row(status=404, method="POST", size="3 B", timing="1 ms", url="/bbb")
    lines = [ln for ln in c.export_text().splitlines() if ln.strip()]
    # header printed exactly once
    assert sum(1 for ln in lines if "STATUS" in ln and "URL" in ln) == 1
    data = [ln for ln in lines if "/aaa" in ln or "/bbb" in ln]
    assert len(data) == 2
    # URL column starts at the same offset on both data rows (alignment)
    assert data[0].index("/aaa") == data[1].index("/bbb")


def test_request_table_folds_long_url():
    c = _table_console()
    r = RequestTableRenderer(console=c)
    r.row(status=200, method="GET", size="1 B", timing="1 ms", url="/x?" + "A" * 200)
    text = c.export_text()
    # a 200-char URL cannot fit one 60-col line -> folds across multiple lines
    assert text.count("A") >= 200
    assert len([ln for ln in text.splitlines() if "A" in ln]) >= 2


def test_request_table_failed_row_and_escaping():
    c = _table_console()
    r = RequestTableRenderer(console=c)
    r.row(status="ERR", method="POST", size="—", timing="—",
          url="/login  · ConnectionRefusedError: [refused]", failed=True)
    text = c.export_text()
    assert "ERR" in text
    assert "ConnectionRefusedError" in text
    assert "[refused]" in text  # markup escaped -> literal brackets survive


def test_request_table_renderer_reexported():
    import penpine

    assert hasattr(penpine, "RequestTableRenderer")
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_render.py -q`
Expected: FAIL (`ImportError: cannot import name 'RequestTableRenderer'`).

- [ ] **Step 3: Implement `RequestTableRenderer` in `penpine/render.py`**

Add after `render_run_summary` (and add `"RequestTableRenderer"` to `__all__`):
```python
class RequestTableRenderer:
    """Print request activity as an aligned table: STATUS METHOD SIZE TIME URL.
    Fixed-width leading columns give cross-row alignment; the URL column folds.
    A dim header row is printed once, before the first data row."""

    _COLS = (("STATUS", 4, "right"), ("METHOD", 7, "left"),
             ("SIZE", 8, "right"), ("TIME", 8, "right"))

    def __init__(self, *, console: Console = console):
        self._console = console
        self._header_shown = False

    def _grid(self) -> Table:
        grid = Table.grid(padding=(0, 1))
        for _, width, justify in self._COLS:
            grid.add_column(width=width, justify=justify)
        grid.add_column(overflow="fold")  # URL, flexes to remaining width
        return grid

    def _ensure_header(self) -> None:
        if self._header_shown:
            return
        grid = self._grid()
        grid.add_row(*[Text(name, style="dim") for name, _, _ in self._COLS],
                     Text("URL", style="dim"))
        self._console.print(grid)
        self._header_shown = True

    def row(self, *, status, method, size, timing, url, failed: bool = False) -> None:
        self._ensure_header()
        style = "red" if failed else _status_style(status)
        grid = self._grid()
        grid.add_row(
            Text(str(status), style=style),
            escape(str(method)),
            str(size),
            str(timing),
            escape(_truncate(url, 500)),
        )
        self._console.print(grid)
```

- [ ] **Step 4: Re-export from root**

Edit `penpine/__init__.py`: change the render import to
```python
from penpine.render import RequestTableRenderer, console, render_report, render_run_summary
```
and add `"RequestTableRenderer",` to `__all__` (next to the other render exports).

- [ ] **Step 5: Run to verify it passes**

Run: `pytest tests/test_render.py -q`
Expected: PASS (all render tests, including the 4 new ones).

- [ ] **Step 6: Lint + format**

Run: `ruff check penpine/render.py penpine/__init__.py tests/test_render.py && ruff format penpine/render.py penpine/__init__.py tests/test_render.py`
Expected: clean.

- [ ] **Step 7: Commit**

```bash
git add penpine/render.py penpine/__init__.py tests/test_render.py
git commit --no-gpg-sign -m "feat(render): add RequestTableRenderer (aligned rows, folding URL column)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: filter request-audit records off the console handler

**Files:**
- Modify: `penpine/logging.py:43-47`
- Test: `tests/test_logging.py`

**Interfaces:**
- Produces: the console `RichHandler` drops any record with a truthy `_penpine_request` attribute; the file handler keeps them.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_logging.py`:
```python
def test_console_handler_filters_request_records():
    from rich.logging import RichHandler

    log = configure_logging(level=logging.INFO)
    console_h = next(h for h in log.handlers if isinstance(h, RichHandler))
    normal = logging.LogRecord("penpine.x", logging.INFO, "f", 1, "hi", None, None)
    request = logging.LogRecord("penpine.x", logging.INFO, "f", 1, "hi", None, None)
    request._penpine_request = True
    assert console_h.filter(normal) is True   # normal records pass
    assert console_h.filter(request) is False  # request-audit records dropped
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_logging.py::test_console_handler_filters_request_records -q`
Expected: FAIL (`assert False is False` fails because no filter yet → returns True).

- [ ] **Step 3: Add the filter in `configure_logging`**

In `penpine/logging.py`, inside the console-handler `if` block (after `handler.setFormatter(...)`, before `log.addHandler(handler)`):
```python
        handler.addFilter(lambda record: not getattr(record, "_penpine_request", False))
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/test_logging.py -q`
Expected: PASS.

- [ ] **Step 5: Verify file still captures request records**

Append to `tests/test_logging_file.py`:
```python
def test_file_handler_keeps_request_records(tmp_path):
    path = tmp_path / "run.log"
    configure_logging(level="INFO", log_file=str(path))
    get_logger("penpine.transport").info("200 GET /x (12 ms)",
                                         extra={"_penpine_request": True})
    for h in logging.getLogger(_ROOT).handlers:
        h.flush()
    assert "200 GET /x" in path.read_text()  # file keeps the audit line
```

Run: `pytest tests/test_logging_file.py -q`
Expected: PASS.

- [ ] **Step 6: Lint + format**

Run: `ruff check penpine/logging.py tests/test_logging.py tests/test_logging_file.py && ruff format penpine/logging.py tests/test_logging.py tests/test_logging_file.py`
Expected: clean.

- [ ] **Step 7: Commit**

```bash
git add penpine/logging.py tests/test_logging.py tests/test_logging_file.py
git commit --no-gpg-sign -m "feat(logging): route request-audit records to the file handler only

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 4: rewrite `RequestLogInterceptor` (render rows + on_error + file audit)

**Files:**
- Modify: `penpine/transport/interceptor.py` (the `RequestLogInterceptor` class + imports)
- Test: `tests/transport/test_request_log.py`

**Interfaces:**
- Consumes: `RequestTableRenderer`, `_humanize_bytes` from `penpine.render`; `Interceptor.on_error` (Task 1); the `_penpine_request` filter (Task 3); `_request_start` contextvar.
- Produces: one rendered row per request (success via `after_receive`, failure via `on_error`), a file-tagged audit record per request, and NO output from `before_send`.

- [ ] **Step 1: Rewrite the tests**

Replace the body of `tests/transport/test_request_log.py` (keep the autouse `_capturable_penpine_logger` fixture and the re-export test) with:
```python
import logging

import pytest

from penpine.core.message import Request
from penpine.core.parse.http_parser import parse_response
from penpine.transport.interceptor import RequestLogInterceptor
from rich.console import Console


@pytest.fixture(autouse=True)
def _capturable_penpine_logger():
    log = logging.getLogger("penpine")
    saved_propagate = log.propagate
    saved_handlers = log.handlers[:]
    log.propagate = True
    log.handlers.clear()
    log.setLevel(logging.INFO)
    yield
    log.propagate = saved_propagate
    log.handlers[:] = saved_handlers


def _recording(ic):
    """Point the interceptor's renderer at a recording console."""
    ic._table._console = Console(record=True, width=80)
    return ic._table._console


async def test_before_send_produces_no_output(caplog):
    ic = RequestLogInterceptor()
    rec = _recording(ic)
    req = Request.from_url("http://t/path?x=1")
    with caplog.at_level(logging.INFO, logger="penpine.transport"):
        await ic.before_send(req)
    assert caplog.records == []            # no log record on send
    assert rec.export_text().strip() == "" # nothing rendered on send


async def test_after_receive_renders_one_row_and_audits(caplog):
    ic = RequestLogInterceptor()
    rec = _recording(ic)
    req = Request.from_url("http://t/path?x=1")
    resp = parse_response(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nok")
    with caplog.at_level(logging.INFO, logger="penpine.transport"):
        await ic.before_send(req)
        out = await ic.after_receive(req, resp)
    assert out is resp
    text = rec.export_text()
    assert "200" in text and "GET" in text and "/path?x=1" in text  # rendered row
    # exactly one audit record, tagged for file-only routing
    reqrecs = [r for r in caplog.records if getattr(r, "_penpine_request", False)]
    assert len(reqrecs) == 1
    assert "200" in reqrecs[0].getMessage() and "/path?x=1" in reqrecs[0].getMessage()


async def test_on_error_renders_failure_row_and_audits(caplog):
    ic = RequestLogInterceptor()
    rec = _recording(ic)
    req = Request.from_url("http://t/down")
    with caplog.at_level(logging.INFO, logger="penpine.transport"):
        await ic.before_send(req)
        await ic.on_error(req, ConnectionRefusedError("refused"))
    text = rec.export_text()
    assert "ERR" in text and "/down" in text and "ConnectionRefusedError" in text
    reqrecs = [r for r in caplog.records if getattr(r, "_penpine_request", False)]
    assert len(reqrecs) == 1
    assert "ERR" in reqrecs[0].getMessage()


async def test_failure_is_visible_without_a_response(caplog):
    # Regression (rephrased): a send that fails never reaches after_receive, so
    # the failure must be recorded via on_error — failed requests stay visible.
    ic = RequestLogInterceptor()
    _recording(ic)
    req = Request.from_url("http://t/path")
    with caplog.at_level(logging.INFO, logger="penpine.transport"):
        await ic.before_send(req)
        await ic.on_error(req, TimeoutError("boom"))
    assert any(getattr(r, "_penpine_request", False) for r in caplog.records)


async def test_level_gating_suppresses_output(caplog):
    ic = RequestLogInterceptor()
    rec = _recording(ic)
    logging.getLogger("penpine").setLevel(logging.WARNING)  # above INFO
    req = Request.from_url("http://t/path")
    resp = parse_response(b"HTTP/1.1 200 OK\r\nContent-Length: 0\r\n\r\n")
    await ic.before_send(req)
    await ic.after_receive(req, resp)
    assert rec.export_text().strip() == ""      # nothing rendered
    assert caplog.records == []                 # nothing logged


async def test_request_log_interceptor_reexported():
    from penpine.transport import RequestLogInterceptor as Exported

    assert Exported is RequestLogInterceptor
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/transport/test_request_log.py -q`
Expected: FAIL (current interceptor logs on `before_send`, has no `_table`, no `on_error` rendering, no `_penpine_request` tag).

- [ ] **Step 3: Rewrite `RequestLogInterceptor`**

In `penpine/transport/interceptor.py`, update imports (top of file):
```python
from penpine.render import RequestTableRenderer, _humanize_bytes
```
(remove the now-unused `escape` and `_status_style` imports if present; keep `contextvars`, `logging`, `time`, `get_logger`, and `_request_start`.)

Replace the entire `RequestLogInterceptor` class with:
```python
class RequestLogInterceptor(Interceptor):
    """Render each request as an aligned table row (STATUS METHOD SIZE TIME URL)
    and, when a log file is configured, write a plain audit line to it.

    A successful request renders in `after_receive`; a failed send renders an
    `ERR` row in `on_error` (a failed send never reaches `after_receive`). No
    output is produced in `before_send`. Rendering and the audit record are both
    gated by the logger's effective level, so LOG_LEVEL still applies."""

    def __init__(self, *, level: int = logging.INFO, logger_name: str = "penpine.transport"):
        self._level = level
        self._log = get_logger(logger_name)
        self._table = RequestTableRenderer()

    async def before_send(self, request):
        _request_start.set(time.perf_counter())
        return request

    def _timing(self) -> str:
        try:
            return f"{(time.perf_counter() - _request_start.get()) * 1000:.0f} ms"
        except LookupError:
            return "—"

    async def after_receive(self, request, response):
        if self._log.isEnabledFor(self._level):
            timing = self._timing()
            status = getattr(response, "status_code", "?")
            size = _humanize_bytes(len(getattr(response, "body", b"") or b""))
            self._table.row(
                status=status, method=request.method, size=size,
                timing=timing, url=request.target,
            )
            self._log.log(
                self._level, "%s %s %s (%s)",
                status, request.method, request.target, timing,
                extra={"_penpine_request": True},
            )
        return response

    async def on_error(self, request, exc):
        if self._log.isEnabledFor(self._level):
            timing = self._timing()
            summary = f"{type(exc).__name__}: {exc}"
            self._table.row(
                status="ERR", method=request.method, size="—", timing=timing,
                url=f"{request.target}  · {summary}", failed=True,
            )
            self._log.log(
                self._level, "ERR %s %s (failed: %s)",
                request.method, request.target, summary,
                extra={"_penpine_request": True},
            )
        return None
```
Also update the class docstring reference in the module if the old one mentioned `-> ` / `<- ` lines (the new docstring above replaces it).

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/transport/test_request_log.py -q`
Expected: PASS (6 tests).

- [ ] **Step 5: Full suite + lint**

Run: `pytest -q && ruff check . && ruff format --check .`
Expected: all pass; ruff clean. (Watch for any other test asserting the old `-> `/`<- ` interceptor format — none expected outside `test_request_log.py`, but fix if found.)

- [ ] **Step 6: Commit**

```bash
git add penpine/transport/interceptor.py tests/transport/test_request_log.py
git commit --no-gpg-sign -m "feat(transport): render request logs as an aligned table; failures via on_error

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Self-Review Notes

- **Spec coverage:** Component 1 (on_error hook + Engine) → Task 1; Component 2 (RequestTableRenderer) → Task 2; Component 4 (console filter) → Task 3; Component 3 (interceptor rewrite: render + file audit + on_error + gating + no send output) → Task 4. Output spec (aligned columns, folding URL, ERR row, file audit line) → Tasks 2 + 4. Testing spec → each task's tests.
- **Type/name consistency:** `RequestTableRenderer.row(*, status, method, size, timing, url, failed=False)` — the interceptor (Task 4) calls it with exactly these kwargs. `_penpine_request` tag written in Task 4, filtered in Task 3, re-tested in both. `on_error(request, exc)` defined in Task 1, implemented in Task 4, dispatched by the Engine in Task 1.
- **Ordering rationale:** Task 3 (console filter) lands before Task 4 (which emits tagged records) so the console never double-shows (rendered row + audit line) at any commit. Task 2 (renderer) precedes Task 4 (consumer). Task 1 (hook) precedes Task 4 (implementer of the hook).
- **Escaping:** renderer escapes `method` and `url` (Task 2), tested via literal-bracket survival; `Text` cells (status) are literal-by-construction. Audit records are plain (no markup) and not `record.markup`, so the file formatter preserves them verbatim.
- **Leaf/import safety:** `render.py` gains no penpine imports; `interceptor.py` imports FROM `render` — one direction, no cycle (verified pattern from the prior branch).
