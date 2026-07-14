# Request-Log Injection Display + Palette Refinement — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show the injection location + value (e.g. `json:$.user = ' OR 1=1`) in the request-log row instead of just the URL, restore a compact `HH:MM:SS` timestamp column, apply the vivid palette, and clear render.py's mypy errors.

**Architecture:** A task-isolated contextvar (`penpine/transport/trace.py`) carries the current `InjectionInfo` (locator + value). The `Runner` publishes it around each send; the `RequestLogInterceptor` reads it and passes it (plus a timestamp) to `RequestTableRenderer`, which renders a vivid, injection-highlighting row. render.py's duck-typed params are re-annotated `Any` to clear mypy.

**Tech Stack:** Python 3.11+, `rich>=13`, stdlib `contextvars`/`datetime`/`logging`, pytest.

## Global Constraints

- Python 3.11+; new modules keep `from __future__ import annotations`.
- `penpine/render.py` stays a LEAF: imports only `rich` + stdlib (`typing`). It must NOT import `penpine.transport`/`penpine.attack`. The renderer treats `injection` duck-typed (reads `.locator`/`.value` via getattr) so it needs no `InjectionInfo` import.
- `penpine/transport/trace.py` is a LEAF: stdlib only (`contextvars`, `dataclasses`). No `rich`, no attack imports.
- Layering: `interceptor.py` (L1) and `runner.py` (L4) both import from `trace.py` (L1). L4→L1 is allowed (Runner already imports `Engine`). L1 must not import L4.
- Escaping rules in the renderer: cells passed as a plain `str` to `grid.add_row` (timestamp, method, size, timing) ARE markup-parsed → wrap in `escape(...)`. Cells passed as a `rich.text.Text`/`Text.assemble` (status, detail) are LITERAL → do NOT escape (escaping would print literal backslashes).
- The contextvar defaults to `None`; non-attack traffic and custom senders keep rendering URL-only rows (backward compatible).
- Ruff lint + format gating. mypy is advisory. Commit with `git commit --no-gpg-sign`.
- Palette (Variant B): TIME dim · STATUS `bold ` + status-class color (`bold red` for ERR) · METHOD `bold cyan` · SIZE/TOOK dim · injection: path dim, locator magenta, value bold yellow.

## File Structure

- `penpine/transport/trace.py` — NEW. `InjectionInfo` + `current_injection` contextvar.
- `penpine/transport/__init__.py` — MODIFY. Export the two symbols.
- `penpine/render.py` — MODIFY. `RequestTableRenderer`: TIME column, `TOOK` rename, vivid palette, `timestamp`/`injection` params, detail rendering (Task 2). Duck-typed `Any` annotations (Task 5).
- `penpine/attack/runner.py` — MODIFY. Publish `current_injection` in `_attempt` + `_probe_attempt`.
- `penpine/transport/interceptor.py` — MODIFY. Read `current_injection`, supply timestamp, pass injection to `row()` + audit line.
- Tests: `tests/transport/test_trace.py` (NEW), `tests/test_render.py`, `tests/attack/test_runner_injection_trace.py` (NEW), `tests/transport/test_request_log.py` (MODIFY).

---

### Task 1: injection trace contextvar (`trace.py`)

**Files:**
- Create: `penpine/transport/trace.py`
- Modify: `penpine/transport/__init__.py`
- Test: `tests/transport/test_trace.py`

**Interfaces:**
- Produces: `InjectionInfo(locator: str, value: str)` (frozen dataclass); `current_injection: ContextVar[InjectionInfo | None]` (default `None`).

- [ ] **Step 1: Write the failing test**

Create `tests/transport/test_trace.py`:
```python
from penpine.transport.trace import InjectionInfo, current_injection


def test_defaults_to_none():
    assert current_injection.get() is None


def test_set_and_reset_round_trips():
    assert current_injection.get() is None
    token = current_injection.set(InjectionInfo(locator="json:$.user", value="' OR 1=1"))
    got = current_injection.get()
    assert got.locator == "json:$.user" and got.value == "' OR 1=1"
    current_injection.reset(token)
    assert current_injection.get() is None


def test_reexported_from_transport():
    from penpine.transport import InjectionInfo as A
    from penpine.transport import current_injection as B

    assert A is InjectionInfo and B is current_injection
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/transport/test_trace.py -q`
Expected: FAIL (`ModuleNotFoundError: penpine.transport.trace`).

- [ ] **Step 3: Create `penpine/transport/trace.py`**

```python
"""Cross-layer trace context: the attack Runner publishes the current injection
(locator + value) here so a transport interceptor can display it. Stdlib only."""

from __future__ import annotations

import contextvars
from dataclasses import dataclass


@dataclass(frozen=True)
class InjectionInfo:
    locator: str  # e.g. "json:$.user", "param:q", "header:Host"
    value: str  # the payload value being injected


current_injection: contextvars.ContextVar[InjectionInfo | None] = contextvars.ContextVar(
    "penpine_injection", default=None
)
```

- [ ] **Step 4: Export from `penpine/transport/__init__.py`**

Add an import line (after the `interceptor` import):
```python
from penpine.transport.trace import InjectionInfo, current_injection
```
and add `"InjectionInfo",` and `"current_injection",` to `__all__`.

- [ ] **Step 5: Run to verify it passes**

Run: `pytest tests/transport/test_trace.py -q`
Expected: PASS (3 tests).

- [ ] **Step 6: Lint + format**

Run: `ruff check penpine/transport/trace.py penpine/transport/__init__.py tests/transport/test_trace.py && ruff format penpine/transport/trace.py penpine/transport/__init__.py tests/transport/test_trace.py`
Expected: clean.

- [ ] **Step 7: Commit**

```bash
git add penpine/transport/trace.py penpine/transport/__init__.py tests/transport/test_trace.py
git commit --no-gpg-sign -m "feat(transport): add InjectionInfo + current_injection trace contextvar

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: renderer — TIME column, vivid palette, injection detail

**Files:**
- Modify: `penpine/render.py` (the `RequestTableRenderer` class only)
- Test: `tests/test_render.py`

**Interfaces:**
- Consumes: `InjectionInfo` (duck-typed, from Task 1) in tests only.
- Produces: `RequestTableRenderer.row(*, status, method, size, timing, url, timestamp="", injection=None, failed=False)`; header `TIME STATUS METHOD SIZE TOOK URL`; vivid palette; injection detail `path  locator = value`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_render.py` (keep the existing `RequestTableRenderer` tests — they still pass because the new params default):
```python
def test_request_table_shows_timestamp_and_header_labels():
    c = Console(record=True, width=80)
    r = RequestTableRenderer(console=c)
    r.row(status=200, method="GET", size="1 B", timing="1 ms", url="/x", timestamp="20:56:11")
    text = c.export_text()
    assert "20:56:11" in text
    assert "TIME" in text and "TOOK" in text  # header renamed/added


def test_request_table_shows_injection_location_and_value():
    from penpine.transport.trace import InjectionInfo

    c = Console(record=True, width=80)
    r = RequestTableRenderer(console=c)
    r.row(
        status=200, method="POST", size="1 B", timing="1 ms", url="/api/login",
        timestamp="20:56:11",
        injection=InjectionInfo(locator="json:$.user", value="' OR 1=1"),
    )
    text = c.export_text()
    assert "json:$.user" in text
    assert "' OR 1=1" in text
    assert "=" in text


def test_request_table_injection_value_escaped():
    from penpine.transport.trace import InjectionInfo

    c = Console(record=True, width=80)
    r = RequestTableRenderer(console=c)
    r.row(
        status=200, method="GET", size="1 B", timing="1 ms", url="/x", timestamp="t",
        injection=InjectionInfo(locator="param:q", value="[bold]pwn[/]"),
    )
    assert "[bold]pwn[/]" in c.export_text()  # literal, markup not interpreted


def test_request_table_no_injection_shows_url_only():
    c = Console(record=True, width=80)
    r = RequestTableRenderer(console=c)
    r.row(status=200, method="GET", size="1 B", timing="1 ms", url="/only-url", timestamp="t")
    text = c.export_text()
    assert "/only-url" in text and "=" not in text.split("/only-url")[1]
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_render.py -q`
Expected: FAIL (the new tests fail — no timestamp/injection support; `TOOK` not in header).

- [ ] **Step 3: Rewrite `RequestTableRenderer`**

Replace the `_COLS`, `_grid`, `_ensure_header`, and `row` (and add `_detail`) in `penpine/render.py` with:
```python
    _COLS: tuple[tuple[str, int, Literal["left", "right"], str], ...] = (
        ("TIME", 8, "left", "dim"),
        ("STATUS", 6, "right", ""),
        ("METHOD", 7, "left", "bold cyan"),
        ("SIZE", 8, "right", "dim"),
        ("TOOK", 7, "right", "dim"),
    )

    def __init__(self, *, console: Console = console):
        self._console = console
        self._header_shown = False

    def _grid(self) -> Table:
        grid = Table.grid(padding=(0, 1))
        for _, width, justify, style in self._COLS:
            grid.add_column(width=width, justify=justify, style=style or None)
        grid.add_column(overflow="fold")  # URL / injection detail, flexes + folds
        return grid

    def _ensure_header(self) -> None:
        if self._header_shown:
            return
        grid = self._grid()
        grid.add_row(
            *[Text(name, style="dim") for name, _, _, _ in self._COLS],
            Text("URL", style="dim"),
        )
        self._console.print(grid)
        self._header_shown = True

    def _detail(self, url: object, injection: object) -> Text:
        if injection is not None:
            locator = str(getattr(injection, "locator", ""))
            value = str(getattr(injection, "value", ""))
            return Text.assemble(
                (str(url) + "  ", "dim"),
                (locator, "magenta"),
                (" = ", "dim"),
                (_truncate(value, 500), "bold yellow"),
            )
        return Text(_truncate(url, 500))

    def row(
        self,
        *,
        status: object,
        method: object,
        size: object,
        timing: object,
        url: object,
        timestamp: object = "",
        injection: object = None,
        failed: bool = False,
    ) -> None:
        self._ensure_header()
        status_style = "bold red" if failed else "bold " + _status_style(status)
        grid = self._grid()
        grid.add_row(
            escape(str(timestamp)),
            Text(str(status), style=status_style),
            escape(str(method)),
            escape(str(size)),
            escape(str(timing)),
            self._detail(url, injection),
        )
        self._console.print(grid)
```

Note: `_detail` returns a `Text` (literal) — no `escape()` inside it (Text does not parse markup; escaping would print backslashes). timestamp/method/size/timing remain escaped plain-str cells.

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/test_render.py -q`
Expected: PASS (all render tests — the pre-existing `RequestTableRenderer` tests still pass because `timestamp`/`injection` default, and the folding/escaping tests still hold).

- [ ] **Step 5: Lint + format**

Run: `ruff check penpine/render.py tests/test_render.py && ruff format penpine/render.py tests/test_render.py`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add penpine/render.py tests/test_render.py
git commit --no-gpg-sign -m "feat(render): timestamp column, vivid palette, injection detail in request table

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: Runner publishes injection context

**Files:**
- Modify: `penpine/attack/runner.py` (`_attempt`, `_probe_attempt`, imports)
- Test: `tests/attack/test_runner_injection_trace.py`

**Interfaces:**
- Consumes: `InjectionInfo`, `current_injection` (Task 1).
- Produces: during `sender.send(req)` inside `_attempt`, `current_injection` holds `InjectionInfo(test_case.point.expr, str(test_case.payload.value))`; reset to prior after.

- [ ] **Step 1: Write the failing test**

Create `tests/attack/test_runner_injection_trace.py`:
```python
from penpine.attack.runner import Runner
from penpine.attack.types import AttackType
from penpine.attack.modules import register_builtins
from penpine.core.message import Request
from penpine.core.parse.http_parser import parse_response
from penpine.transport.trace import current_injection


class _CapturingSender:
    def __init__(self):
        self.seen = []

    async def send(self, request):
        self.seen.append(current_injection.get())
        return parse_response(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nok")


async def test_runner_publishes_injection_during_send():
    register_builtins()
    sender = _CapturingSender()
    req = Request.from_url("http://h/search?q=1")
    report = await Runner(sender=sender, max_concurrency=1).run(req, attack=AttackType.SQLI)
    # every send saw an InjectionInfo with a locator + value (not None)
    non_baseline = [s for s in sender.seen if s is not None]
    assert non_baseline, "sender never saw injection context"
    assert all(s.locator and s.value for s in non_baseline)
    assert any("q" in s.locator for s in non_baseline)  # param:q was targeted
    # context is reset after the run
    assert current_injection.get() is None
    assert report.summary()["sent"] >= 1
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/attack/test_runner_injection_trace.py -q`
Expected: FAIL (`sender.seen` is all `None` — Runner doesn't publish yet).

- [ ] **Step 3: Import trace in runner.py**

Add to the imports:
```python
from penpine.transport.trace import InjectionInfo, current_injection
```

- [ ] **Step 4: Publish in `_attempt`**

In `penpine/attack/runner.py`, `_attempt`, wrap the send. Replace:
```python
        sent_tc = dataclasses.replace(test_case, request=req)
        try:
            response = await sender.send(req)
        except Exception as exc:
            return Attempt(
                test_case=sent_tc,
                request=req,
                error=exc,
                elapsed_ms=(time.perf_counter() - start) * 1000,
            )
```
with:
```python
        sent_tc = dataclasses.replace(test_case, request=req)
        token = current_injection.set(
            InjectionInfo(locator=test_case.point.expr, value=str(test_case.payload.value))
        )
        try:
            response = await sender.send(req)
        except Exception as exc:
            return Attempt(
                test_case=sent_tc,
                request=req,
                error=exc,
                elapsed_ms=(time.perf_counter() - start) * 1000,
            )
        finally:
            current_injection.reset(token)
```

- [ ] **Step 5: Publish in `_probe_attempt`**

Replace the `try/except` in `_probe_attempt` with a `token`-guarded version:
```python
        token = current_injection.set(
            InjectionInfo(locator=point.expr, value="<differential>")
        )
        try:
            finding = await module.probe(point, request, sender, baseline=baseline)
        except Exception as exc:
            return Attempt(test_case=placeholder, error=exc)
        finally:
            current_injection.reset(token)
```
(The `return` inside `except` still runs `finally` before returning — reset happens on both paths.)

- [ ] **Step 6: Run to verify it passes**

Run: `pytest tests/attack/test_runner_injection_trace.py -q`
Expected: PASS.

- [ ] **Step 7: Full attack suite + lint**

Run: `pytest tests/attack -q && ruff check penpine/attack/runner.py tests/attack/test_runner_injection_trace.py && ruff format penpine/attack/runner.py tests/attack/test_runner_injection_trace.py`
Expected: attack tests pass; ruff clean.

- [ ] **Step 8: Commit**

```bash
git add penpine/attack/runner.py tests/attack/test_runner_injection_trace.py
git commit --no-gpg-sign -m "feat(attack): Runner publishes injection locator+value via current_injection

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 4: interceptor reads injection + supplies timestamp

**Files:**
- Modify: `penpine/transport/interceptor.py`
- Test: `tests/transport/test_request_log.py`

**Interfaces:**
- Consumes: `current_injection` (Task 1), `RequestTableRenderer.row` new params (Task 2).
- Produces: `after_receive`/`on_error` pass `timestamp` (HH:MM:SS) + `injection` to `row()`; the audit line includes `locator=value` when present.

- [ ] **Step 1: Add the failing tests**

Append to `tests/transport/test_request_log.py`:
```python
async def test_row_and_audit_include_injection(caplog):
    from penpine.transport.trace import InjectionInfo, current_injection

    ic = RequestLogInterceptor()
    rec = _recording(ic)
    req = Request.from_url("http://t/api/login")
    resp = parse_response(b"HTTP/1.1 200 OK\r\nContent-Length: 0\r\n\r\n")
    tok = current_injection.set(InjectionInfo(locator="json:$.user", value="' OR 1=1"))
    try:
        with caplog.at_level(logging.INFO, logger="penpine.transport"):
            await ic.before_send(req)
            await ic.after_receive(req, resp)
    finally:
        current_injection.reset(tok)
    text = rec.export_text()
    assert "json:$.user" in text and "' OR 1=1" in text  # rendered row
    audit = next(r for r in caplog.records if getattr(r, "_penpine_request", False))
    assert "json:$.user" in audit.getMessage()  # audit line carries it too


async def test_row_has_timestamp(caplog):
    ic = RequestLogInterceptor()
    rec = _recording(ic)
    req = Request.from_url("http://t/x")
    resp = parse_response(b"HTTP/1.1 200 OK\r\nContent-Length: 0\r\n\r\n")
    with caplog.at_level(logging.INFO, logger="penpine.transport"):
        await ic.before_send(req)
        await ic.after_receive(req, resp)
    # HH:MM:SS pattern present
    import re

    assert re.search(r"\d\d:\d\d:\d\d", rec.export_text())
```
(The existing `test_after_receive_renders_one_row_and_audits` still holds: no injection set → URL only.)

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/transport/test_request_log.py -q`
Expected: FAIL (injection not read; no timestamp passed).

- [ ] **Step 3: Update the interceptor**

Edit `penpine/transport/interceptor.py`:
- Add imports:
```python
from datetime import datetime

from penpine.transport.trace import current_injection
```
- In `after_receive`, inside the `isEnabledFor` block, read injection + timestamp and pass them, and add injection to the audit line. Replace the `self._table.row(...)` + `self._log.log(...)` block with:
```python
            ts = datetime.now().strftime("%H:%M:%S")
            injection = current_injection.get()
            self._table.row(
                status=status,
                method=request.method,
                size=size,
                timing=timing,
                url=request.target,
                timestamp=ts,
                injection=injection,
            )
            inj = f"  {injection.locator}={injection.value}" if injection else ""
            self._log.log(
                self._level,
                "%s %s %s%s (%s)",
                status,
                request.method,
                request.target,
                inj,
                timing,
                extra={"_penpine_request": True},
            )
```
- In `on_error`, similarly add timestamp + injection to the failure row and audit. Replace its `self._table.row(...)` + `self._log.log(...)` with:
```python
            ts = datetime.now().strftime("%H:%M:%S")
            injection = current_injection.get()
            self._table.row(
                status="ERR",
                method=request.method,
                size="—",
                timing=timing,
                url=f"{request.target}  · {summary}",
                timestamp=ts,
                injection=injection,
                failed=True,
            )
            inj = f"  {injection.locator}={injection.value}" if injection else ""
            self._log.log(
                self._level,
                "ERR %s %s%s (failed: %s)",
                request.method,
                request.target,
                inj,
                summary,
                extra={"_penpine_request": True},
            )
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/transport/test_request_log.py -q`
Expected: PASS.

- [ ] **Step 5: Full suite + lint**

Run: `pytest -q && ruff check . && ruff format --check .`
Expected: all pass; ruff clean.

- [ ] **Step 6: Commit**

```bash
git add penpine/transport/interceptor.py tests/transport/test_request_log.py
git commit --no-gpg-sign -m "feat(transport): show injection locator+value and timestamp in request log

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 5: render.py mypy cleanup

**Files:**
- Modify: `penpine/render.py` (annotations only)

**Interfaces:** none (typing only; no behavior change).

- [ ] **Step 1: Confirm the current errors**

Run: `mypy penpine/render.py 2>&1 | grep -c error:`
Expected: reports the `attr-defined` / `call-overload` errors (the 12 from CI, possibly fewer after Tasks 2/5-adjacent edits — record the count).

- [ ] **Step 2: Annotate duck-typed inputs as `Any`**

In `penpine/render.py`:
- Add `Any` to the typing import: `from typing import Any, Literal`.
- Change signatures (params that access attributes on report/finding-like objects):
  - `def _status_style(status: Any) -> str:` and remove the `# type: ignore[arg-type]` on `int(status)`.
  - `def _finding_panel(finding: Any, attempt: Any) -> Panel:`
  - `def render_report(report: Any, *, console: Console = console) -> None:`
  - `def render_run_summary(results: Any, *, console: Console = console) -> None:`
- Leave `_confidence_style(confidence: object)`, `_humanize_bytes(n: int)`, `_truncate(s: object, ...)` as-is (no attr-defined errors there). `RequestTableRenderer.row`/`_detail` params stay `object` (attribute access on `injection` is getattr-guarded, no mypy error).

- [ ] **Step 3: Verify mypy is clean for render.py**

Run: `mypy penpine/render.py 2>&1 | grep "error:" | grep "render.py" || echo "no render.py errors"`
Expected: `no render.py errors` (0 errors in render.py; unrelated notes about other files are fine).

- [ ] **Step 4: Lint + format + full suite**

Run: `ruff check penpine/render.py && ruff format --check penpine/render.py && pytest tests/test_render.py -q`
Expected: clean; render tests pass (annotations don't change behavior).

- [ ] **Step 5: Commit**

```bash
git add penpine/render.py
git commit --no-gpg-sign -m "fix(render): annotate duck-typed render inputs as Any to clear mypy errors

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Self-Review Notes

- **Spec coverage:** Component 1 (trace) → Task 1; Component 2 (Runner publishes) → Task 3; Component 3 (renderer TIME/palette/injection) → Task 2; Component 4 (interceptor reads + timestamp + audit) → Task 4; Component 5 (mypy) → Task 5. Output spec (timestamp col, vivid palette, `path locator = value`, audit line) → Tasks 2 + 4. Testing spec → each task.
- **Ordering:** trace (1) before its consumers (2 renderer, 3 runner, 4 interceptor). Renderer (2) before interceptor (4), which calls the new `row()` signature. mypy (5) last, isolated.
- **Escaping consistency:** detail uses `Text`/`Text.assemble` (literal) → NOT escaped; timestamp/method/size/timing are plain-str grid cells → escaped. The injection-value escaping test asserts a literal `[bold]pwn[/]` survives via the Text path (markup not interpreted).
- **Back-compat:** `row()`'s `timestamp=""`/`injection=None` defaults keep the existing `RequestTableRenderer` tests green; `current_injection` defaults to `None` so non-attack sends render URL-only exactly as before.
- **Type consistency:** `InjectionInfo(locator, value)` constructed in the Runner (Task 3), read via getattr in the renderer (Task 2) and via `current_injection.get()` in the interceptor (Task 4); `row(..., timestamp, injection)` signature (Task 2) matches the interceptor's call (Task 4).
- **Leaf/cycle safety:** `trace.py` (stdlib only) and `render.py` (rich only) both stay leaves; `interceptor`/`runner` import from `trace` one-directionally.
