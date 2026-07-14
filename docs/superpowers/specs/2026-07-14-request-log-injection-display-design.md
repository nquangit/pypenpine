# Request-Log Injection Display + Palette Refinement — Design

**Date:** 2026-07-14
**Status:** Approved (design), pending implementation plan
**Follows:** `2026-07-14-request-log-table-design.md` (refines the request-log table shipped there)

## Problem

Feedback on the shipped request-log table:

1. **Colors aren't quite right** — the palette needs to make the injection stand
   out and be more deliberate.
2. **Timestamp missing** — the old per-line timestamp is wanted back (but NOT the
   level + logger-name chrome that was correctly removed).
3. **Injection not shown** — a request whose payload lands in a JSON body (or any
   non-URL location) renders with only the URL path, so the operator can't see
   what is being tested. The row should show the **injection location and its
   value** (e.g. `json:$.user = ' OR 1=1`), not just the path.
4. **mypy CI errors** — `penpine/render.py` produces 12 `attr-defined` /
   `call-overload` errors (advisory CI step, but should be clean).

The root difficulty for (3): `RequestLogInterceptor` is a transport-layer (L1)
component that sees only the raw HTTP request bytes. It does not know which part
of the request is the injection — that is attack-layer (L4) knowledge held by the
`Runner` in the `TestCase` (`point.expr` + `payload.value`). The display needs
that context delivered from L4 to L1 without a layering violation.

## Decisions (locked during brainstorming)

1. **Vivid palette (Variant B).** Timestamp dim; STATUS bold + status-class color;
   METHOD bold cyan; SIZE/TOOK dim; injection locator magenta; payload value bold
   yellow; path dim on injection rows. The injection is the row's focal point.
2. **Compact timestamp column** at line start, format `HH:MM:SS` (no date, no
   level, no logger name).
3. **Injection surfaced via a task-isolated contextvar** published by the Runner
   and read by the interceptor. When present, the detail cell shows
   `path  locator = value`; when absent, the URL/target only.
4. **mypy cleanup** by annotating render.py's duck-typed inputs as `typing.Any`.

## Architecture

### Component 1 — injection trace context (`penpine/transport/trace.py`, new)

A tiny, dependency-free module both L1 (interceptor) and L4 (Runner) can import.

```python
from __future__ import annotations
import contextvars
from dataclasses import dataclass


@dataclass(frozen=True)
class InjectionInfo:
    locator: str   # e.g. "json:$.user", "param:q", "header:Host"
    value: str     # the payload value being injected


current_injection: contextvars.ContextVar[InjectionInfo | None] = contextvars.ContextVar(
    "penpine_injection", default=None
)
```

- Lives in the transport layer (L1) so the interceptor can read it without
  importing upward. The Runner (L4) already depends on transport (it uses
  `Engine`), so importing `trace` there is layering-clean.
- No `rich`, no attack imports — a leaf. `InjectionInfo` is a plain descriptor so
  transport never imports attack's `TestCase`/`InjectionPoint`.

### Component 2 — Runner publishes injection context

`penpine/attack/runner.py`, `_attempt` (around the send at runner.py:159-161):

```python
sent_tc = dataclasses.replace(test_case, request=req)
token = current_injection.set(
    InjectionInfo(locator=test_case.point.expr, value=str(test_case.payload.value))
)
try:
    response = await sender.send(req)
except Exception as exc:
    return Attempt(test_case=sent_tc, request=req, error=exc,
                   elapsed_ms=(time.perf_counter() - start) * 1000)
finally:
    current_injection.reset(token)
```

- Set immediately before the send, reset in `finally`. Each `_attempt` runs in
  its own gathered task, so the contextvar is task-isolated (no cross-request
  leakage — same guarantee as `_request_start`). The `finally` reset keeps the
  context clean even within a task.
- `_probe_attempt` (blind/differential path, runner.py:191+) similarly sets
  `InjectionInfo(locator=point.expr, value="<differential>")` around
  `module.probe(...)` so the prober's internal sends still show the locator
  (exact per-probe payloads are the module's concern; the locator is enough).
- The `except` path returns before `finally`? No — `finally` always runs, so the
  reset happens on both success and the caught-exception return. Correct.

Import in runner.py: `from penpine.transport.trace import InjectionInfo, current_injection`.

### Component 3 — the renderer shows the injection + timestamp (`penpine/render.py`)

Update `RequestTableRenderer`:

- **New leading TIME column** (`HH:MM:SS`, dim). Header labels become
  `TIME STATUS METHOD SIZE TOOK URL` (the elapsed column header renamed to `TOOK`
  to disambiguate from the clock).
- **Column spec** (fixed widths; URL/detail flexes + folds):

  | col | width | align | style |
  |-----|-------|-------|-------|
  | TIME | 8 | left | dim |
  | STATUS | 6 | right | bold + status-class color; `ERR` bold red |
  | METHOD | 7 | left | bold cyan |
  | SIZE | 8 | right | dim |
  | TOOK | 7 | right | dim |
  | URL/detail | flex | left | fold |

- **`row(...)` gains parameters** `timestamp: object = ""` and
  `injection: object = None` (an `InjectionInfo`-like with `.locator`/`.value`, or
  None). Both default so existing `row()` callers/tests keep working; the
  interceptor always passes a real timestamp. Kept duck-typed/`Any`-friendly so
  `render.py` imports nothing from transport (leaf property preserved). When
  `timestamp` is falsy the TIME cell renders blank (still occupies its column).
- **Detail cell** built with `rich.text.Text.assemble`:
  - injection present →
    `Text.assemble((path + "  ", "dim"), (escape(locator), "magenta"),
    (" = ", "dim"), (escape(truncate(value)), "bold yellow"))`.
  - injection absent → `Text(escape(url))` (normal weight).
- STATUS remains a styled `Text`; METHOD/SIZE/TOOK still escaped strings.
- Timestamp is passed IN (not computed in the renderer) so the renderer stays a
  pure presentation unit and is deterministic to test; the interceptor supplies
  `datetime.now().strftime("%H:%M:%S")`.

### Component 4 — interceptor reads context + supplies timestamp

`penpine/transport/interceptor.py`, `RequestLogInterceptor`:

- In `after_receive` and `on_error`, read `injection = current_injection.get()`.
- Compute `ts = datetime.now().strftime("%H:%M:%S")`.
- Call `self._table.row(timestamp=ts, status=..., method=..., size=..., timing=...,
  url=request.target, injection=injection, failed=...)`.
- **File audit line** includes the injection when present:
  `f"{status} {method} {target}{inj} ({timing})"` where
  `inj = f"  {injection.locator}={injection.value}"` if injection else `""`.
- `_row_rendered` double-render guard (from the prior branch) stays.
- Import `from penpine.transport.trace import current_injection`.

### Component 5 — mypy cleanup (`penpine/render.py`)

Annotate the duck-typed render inputs as `typing.Any` (they accept any
report/finding/result-like object): `render_report(report: Any)`,
`_finding_panel(finding: Any, attempt: Any)`, `render_run_summary(results: Any)`,
`_status_style(status: Any)`. Remove the now-unnecessary
`# type: ignore[arg-type]` on `int(status)` (with `status: Any`, `int(status)`
type-checks). `RequestTableRenderer.row`'s new `injection`/`timestamp` params are
`Any`/`object` (attribute access on `injection` guarded by the None check).

Add `from typing import Any` alongside the existing `Literal` import.

## Output specification

Console (vivid palette; injection is the focal point):
```
TIME     STATUS  METHOD   SIZE     TOOK   URL
20:56:11    200  GET       1.2 kB  12 ms  /home
20:56:11    500  POST       340 B  28 ms  /api/login  json:$.user = ' OR 1=1-- -
20:56:12    200  GET         88 B   9 ms  /search  param:q = <script>alert(1)…
20:56:12    ERR  POST           —      —  /api/item  json:$.id = ../../etc/passwd
```
- TIME dim · STATUS bold-colored · METHOD bold-cyan · SIZE/TOOK dim · path dim ·
  locator magenta · value bold-yellow. Long values fold under the URL column.

File (`LOG_FILE`):
```
INFO penpine.transport: 200 POST /api/login  json:$.user=' OR 1=1-- - (28 ms)
INFO penpine.transport: 200 GET /home (12 ms)
```

## Data flow

```
Runner._attempt(test_case)
  ├─ current_injection.set(InjectionInfo(point.expr, payload.value))   [task-local]
  ├─ await sender.send(req)
  │     └─ Engine → RequestLogInterceptor.after_receive / on_error
  │            └─ injection = current_injection.get()  → renderer.row(..., injection)
  └─ finally: current_injection.reset(token)
```

## Testing

### `tests/transport/test_trace.py` (new)
- `current_injection.get()` defaults to `None`.
- `set`/`reset` round-trips (token restores prior value); nested set/reset works.

### Runner (`tests/attack/`)
- A fake sender that records `current_injection.get()` during `send` sees the
  `InjectionInfo(locator=point.expr, value=payload.value)` for the attempt.
- After `run`, `current_injection.get()` is back to `None` (reset happened), even
  when the send raises.

### Renderer (`tests/test_render.py`)
- `row(..., injection=InjectionInfo("json:$.user", "' OR 1=1"))` output contains
  the locator and the value; a URL-markup/`[...]` in the value is escaped.
- `row(..., injection=None)` shows the URL only (no ` = `).
- The TIME column value appears; header row shows `TIME` and `TOOK` and prints once.
- Long injection value folds under the detail column.

### Interceptor (`tests/transport/test_request_log.py`)
- With `current_injection` set, `after_receive` renders the injection AND the
  audit record message contains `locator=value`.
- With it unset, the row/audit show the URL only.
- The timestamp column is present in the rendered row.

### mypy
- `mypy penpine/render.py` → the 12 previously-reported errors are gone (0 errors
  in `render.py`). (Advisory step; verify locally.)

## Non-goals / YAGNI

- No coloring the payload value by attack type (uniform bold-yellow for now).
- No live/redraw dashboard (still static scrolling rows).
- No configurable palette/columns.
- Blind-prober per-probe exact payloads are not surfaced (locator only for the
  differential path).
- No change to `render_report` / `render_run_summary` layout (only their param
  type annotations change for mypy).

## Backward-compatibility notes

- `RequestTableRenderer.row` gains `timestamp=""` and `injection=None` params —
  both optional, so existing callers/tests are unaffected. This is a public
  re-exported API — the added params are the only surface change.
- `InjectionInfo`/`current_injection` are new public transport symbols; the
  contextvar defaults to `None`, so non-attack traffic and existing custom
  senders are unaffected (URL-only rows, exactly as before this change).
