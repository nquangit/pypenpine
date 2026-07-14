# Request-Log Table Output — Design

**Date:** 2026-07-14
**Status:** Approved (design), pending implementation plan
**Follows:** `2026-07-14-rich-terminal-output-design.md` (this refines the request-log output shipped there)

## Problem

The current `RequestLogInterceptor` output has four problems for live monitoring:

1. **Two lines per request** — a `->` send line and a `<-` receive line. The
   receive line already carries everything; the send line is redundant.
2. **Chrome wastes horizontal space** — every line is prefixed by RichHandler's
   timestamp + level + logger name (`[07/14/26 20:56:11] INFO penpine.transport:`),
   pushing the useful content right and causing wraps.
3. **No column alignment** — payloads vary in length, so `status method target
   size time` never lines up between rows; the stream looks messy.
4. **Long payloads wrap the whole line** — a long URL breaks across lines with no
   structure.

The send line exists for a real reason: the Engine only calls `after_receive`
on success, so a failed send (refused/timeout/TLS) never reaches it — logging in
`before_send` is currently the only way failures stay visible.

## Goal

Render the request stream as a **compact, column-aligned table**: one row per
request, no logging chrome, fixed-width leading columns, and a URL column that
word-wraps (folds) under itself. Failed sends still appear — as a single `ERR`
row — via a new interceptor error hook. When `LOG_FILE` is set, each request also
gets a plain audit line in the file.

## Decisions (locked during brainstorming)

1. **Request rows are rendered directly to the console** (a table via
   `penpine.render`), NOT routed through the RichHandler — that is the only way
   to get true cross-row alignment, per-column URL folding, and no time/level/name
   chrome.
2. **Console table + plain file line.** When a log file is configured, each
   request also emits a compact plain-text audit line to the file (timestamp
   kept there — the file is an audit trail). The console never shows that line.
3. **One row per request via a new `on_error` interceptor hook.** Failed sends
   render a single `ERR` row instead of the old send line.

## Architecture

Three components change: the interceptor seam + Engine (error hook), the renderer
(`penpine.render`), and `configure_logging` (route request audit records to the
file only).

### Component 1 — `on_error` interceptor hook (seam + Engine)

**`penpine/transport/interceptor.py`** — add to the `Interceptor` base:

```python
async def on_error(self, request, exc):
    """Called when a send ultimately fails (after retries). Default no-op.
    Must not raise."""
    return None
```

**`penpine/transport/engine.py`** — dispatch `on_error` from the public `send()`
so it catches every failure mode, including the total-timeout wrap (which is
raised in `send()`, outside `_send`). `send_many` and the Runner both route
through `send()`, so this one site covers all paths.

Current `send()`:
```python
async def send(self, request):
    if self.timeouts.total:
        try:
            return await asyncio.wait_for(self._send(request), self.timeouts.total)
        except TimeoutError as exc:
            raise TotalTimeout(...) from exc
    return await self._send(request)
```

New `send()` (wrap the whole body; fire `on_error` for each interceptor in
reversed order — mirroring `after_receive` — then re-raise):
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
                pass  # a logging/error hook must never mask the original error
        raise
```

Notes:
- `on_error` receives the **original** `request` (the one passed to `send`),
  not the interceptor-transformed/proxy-rewritten `req` from `_send`. For a log
  row this is what we want (original method + target, pre-proxy-rewrite).
- `RetrySignal` never escapes `_send` (it is caught in the retry loop), so it
  cannot reach this handler — `on_error` only sees genuine failures.
- Each `on_error` call is individually guarded so one bad hook cannot mask the
  real exception or block the others. The original exception always re-raises,
  preserving the Runner-never-raises contract (the Runner catches it per attempt).

### Component 2 — the aligned table renderer (`penpine/render.py`)

Add a small stateful renderer that owns the column layout and prints one aligned
row per request, plus a one-time header.

```python
class RequestTableRenderer:
    """Prints request activity as an aligned table: STATUS METHOD SIZE TIME URL.
    Fixed-width leading columns give cross-row alignment; the URL column folds."""

    def __init__(self, *, console: Console = console):
        self._console = console
        self._header_shown = False

    def row(self, *, status, method, size, timing, url, failed=False): ...
```

Column layout (fixed widths chosen for typical values; URL flexes):

| column | width | align | style |
|--------|-------|-------|-------|
| STATUS | 4     | right | status class color; `ERR` red on failure |
| METHOD | 7     | left  | dim/cyan |
| SIZE   | 8     | right | dim (`—` on failure) |
| TIME   | 8     | right | dim (`—` if unavailable) |
| URL    | flex  | left  | default; **folds** (`overflow="fold"`) |

- Implemented per row as a `Table.grid` (or `Table` with `box=None`,
  `show_header=False`, `padding=(0,1)`) with **explicit widths** on STATUS/METHOD/
  SIZE/TIME and a flexible, folding URL column. Identical widths every call ⇒
  rows align; the URL column fills the remaining console width and long payloads
  fold with continuation lines under the URL column.
- A dim header row (`STATUS METHOD SIZE TIME URL`) is printed once, lazily,
  before the first data row (`_header_shown` guard).
- `url` and `method` are escaped via `rich.markup.escape` (payloads carry `[`/`]`).
  A failure row appends the exception summary to the URL cell, e.g.
  `/login  · ConnectError: connection refused` (also escaped, truncated).
- The renderer takes already-formatted primitives (`status`, `size`, `timing`
  strings) — computing them (humanize bytes, status style) stays with the
  interceptor/existing helpers. Keeps the renderer a pure presentation unit.

Export `RequestTableRenderer` from `penpine.render.__all__` and re-export from
root `penpine/__init__.py` (user-facing, consistent with `render_report`).

### Component 3 — `RequestLogInterceptor` uses the renderer + file audit line

**`penpine/transport/interceptor.py`** — rewrite so:

- `__init__` creates a `RequestTableRenderer(console=render.console)` and keeps
  the logger (for the file audit line) and level.
- `before_send`: only records the start time in the `_request_start` contextvar.
  **No output.**
- `after_receive`: if `self._log.isEnabledFor(self._level)` (so `LOG_LEVEL` still
  gates request output), render a success row via the renderer, and emit the file
  audit record (below). Returns the response unchanged.
- `on_error`: same gating; render a failure row (`failed=True`, `ERR`, exception
  summary), and emit a file audit record marked failed. Never raises.
- **File audit line:** a compact plain string logged through the logger with
  `extra={"_penpine_request": True}`:
  `f"{status} {request.method} {request.target} ({timing})"` (RichHandler-free;
  the file's timestamp comes from the file formatter). The `extra` tag routes it
  to the file handler only (Component 4).

Timing: `after_receive` computes elapsed from the contextvar as today. `on_error`
also tries the contextvar and falls back to blank (`—`) on `LookupError` (the
total-timeout path crosses an `asyncio.wait_for` task boundary where the
contextvar may not be visible — blank timing is acceptable on failure).

### Component 4 — route request audit records to the file only

**`penpine/logging.py`** — the console `RichHandler` must NOT print request audit
records (the console already shows the rendered table; the record is for the file).
Attach a filter to the console handler:

```python
handler.addFilter(lambda record: not getattr(record, "_penpine_request", False))
```

- The file handler has no such filter, so it writes the audit line (plain, via
  the existing `_PlainFormatter`; the message has no markup so it passes through).
- If no `LOG_FILE` is configured, there is no file handler, and the audit record
  simply goes nowhere — the console still shows the rendered row. Correct.
- `_PlainFormatter` already strips markup only for `record.markup` records
  (unchanged); audit records are not markup, so their brackets are preserved in
  the file.

## Output specification

Console (colors applied on a TTY):
```
STATUS  METHOD   SIZE      TIME    URL
   200  GET       1.2 kB   12 ms   /search?q=' OR 1=1-- -
   500  GET       340 B    28 ms   /search?q=<very long payload string that
                                   exceeds the column and folds to the next
                                   line under the URL column>
   ERR  POST      —        —       /login  · ConnectError: connection refused
```

File (`LOG_FILE`), one plain line per request via the audit record + file
formatter (`%(levelname)s %(name)s: %(message)s`, with the file handler's own
formatting; timestamp per the formatter config):
```
INFO penpine.transport: 200 GET /search?q=' OR 1=1-- - (12 ms)
INFO penpine.transport: ERR POST /login (failed: ConnectError: connection refused)
```

## Data flow

```
Engine.send(request)
  ├─ success → _send → after_receive(req, resp)
  │             └─ interceptor: renderer.row(success)  → console
  │                           + log(..., extra={_penpine_request})  → file only
  └─ failure → except → on_error(request, exc)
                └─ interceptor: renderer.row(failed)   → console
                              + log(..., extra={_penpine_request})  → file only
```

## Testing

### Engine (`tests/transport/`)
- `on_error` is invoked (reversed interceptor order) when the connection layer
  raises, and the original exception still propagates out of `send()`. Use a fake
  connection factory whose `open`/`send_bytes` raises; assert a recording
  interceptor's `on_error` saw the request + exception, and `send()` re-raised.
- An `on_error` hook that itself raises does NOT mask the original exception.
- Success path still calls `after_receive` and returns the response (regression).

### Renderer (`tests/test_render.py`)
- `RequestTableRenderer.row(...)` twice with different-length URLs: via
  `Console(record=True, width=N)` + `export_text()`, assert the STATUS/METHOD/
  SIZE/TIME columns start at the **same character offsets** on both rows
  (alignment), and the header appears exactly once.
- A URL longer than the URL column **folds** (appears across ≥2 lines) and does
  not push the fixed columns.
- `failed=True` renders `ERR` and the exception summary; markup in the URL is
  escaped (literal `[bold]` survives).
- Re-export: `from penpine import RequestTableRenderer`.

### Interceptor (`tests/transport/test_request_log.py`)
- `after_receive` renders exactly one row (no send-line output from `before_send`)
  and emits one file-tagged record (`caplog` sees a record with
  `_penpine_request` True and a plain message containing status+method+target).
- `on_error` renders a failure row and emits one failed file-tagged record.
- `before_send` produces **no** log record (only sets timing).
- Level gating: with the logger disabled for the level, no row is rendered.
- Rephrase the existing "logged on send even without a response" regression test
  to assert the failure is now recorded via `on_error` (same guarantee: failed
  sends stay visible; different hook).

### Logging (`tests/test_logging*.py`)
- The console handler has a filter that drops `_penpine_request` records; the
  file handler keeps them (write a tagged record, assert it lands in the file but
  a recording console does not show it).

## Non-goals / YAGNI

- No live-updating / redrawing table (still static, scrolling per the prior
  design's decision).
- No configurable columns or widths in this iteration (fixed layout).
- No change to `render_report` / `render_run_summary` (the post-run summary).
- No new config knobs in the generated project — `LOG_REQUESTS` / `LOG_LEVEL` /
  `LOG_FILE` keep their current meaning; only the request *rendering* changes.

## Backward-compatibility notes

- `Interceptor` gains `on_error` with a no-op default, so existing custom
  interceptors keep working unchanged.
- The `RequestLogInterceptor` public constructor signature
  (`level=`, `logger_name=`) is unchanged.
- Request lines are no longer emitted through the console logging handler, so any
  code asserting on the old `-> ` / `<- ` console log format must move to the
  renderer or the file audit line. (Only in-repo tests are affected.)
