# Rich Terminal Output — Design

**Date:** 2026-07-14
**Status:** Approved (design), pending implementation plan

## Problem

The output an operator watches while a scan runs is poor. In the generated
project's `main.py` it is uncolored `print`s:

```python
report = runner.run_sync(request, attack=attack)
print(f"\n== {item} ==  {report.summary()}")
for finding in report.findings:
    print(f"  [{finding.confidence.name}] {finding.point.expr} -> {finding.evidence}")
```

and request logging is a single flat green line per request (everything is
`INFO`, so status codes are indistinguishable). It is hard to monitor progress
and hard to spot findings.

The user wants **more color and much richer information** so a run is easy to
monitor and evaluate. Information density / clutter is explicitly desired.

## Decisions (locked during brainstorming)

1. **Rendering uses the `rich` library**, added as a real runtime dependency.
   This is a deliberate identity change: penpine's core (raw sockets, HTTP
   parse/serialize, attack engine) stays standard-library-only, but `rich` is
   permitted as a **presentation-only** dependency. The README and CLAUDE.md
   "the only runtime dependency is `jsonpath-ng`" / "entirely on the standard
   library" wording is updated to reflect this.
2. **Static, scrolling styled output** — colored lines, tables, and panels
   printed as events happen. No live-updating `Live`/`Progress` dashboard (its
   coordination with logging and the threaded `run_sync` loop is finicky and
   was deferred). The renderer is written so a live layer could wrap it later,
   but that is out of scope here.

## Architecture

Rendering is a **reusable framework capability**, not scaffold-only glue. Any
user writing code against penpine gets the same colored output; the generated
project simply calls it.

### Component 1 — `penpine/render.py` (new, top-level, exported)

Reusable rich renderer. Owns a single shared `Console`.

```python
from rich.console import Console

console = Console()   # module-level shared instance

def render_report(report, *, console: Console = console) -> None: ...
def render_run_summary(results, *, console: Console = console) -> None: ...
```

- `render_report(report)` — renders one `Report`:
  - a per-attack summary line/table (attack type, sent, failed, found),
  - one panel per `Finding` (see Output spec below),
  - an errors block if `report.errors` is non-empty (count + a few reasons).
- `render_run_summary(results)` — `results` is an ordered sequence of
  `(label: str, report: Report)` pairs. Renders a single rich `Table`
  (columns: `target / attack`, `sent`, `failed`, `found`) with one row per
  pair and a bold `TOTAL` row. Rows with `found > 0` are highlighted.

Internal helpers (module-private):
- `_status_style(status: int | str) -> str` — maps status class to a rich
  style name: 2xx `green`, 3xx `cyan`, 4xx `yellow`, 5xx `red`, unknown/`?`
  `red`.
- `_confidence_style(confidence) -> str` — HIGH `bold red`, MEDIUM `yellow`,
  LOW `dim cyan`.
- `_humanize_bytes(n: int) -> str` — e.g. `1234` → `"1.2 kB"`, `512` → `"512 B"`.

Export `console`, `render_report`, `render_run_summary` from
`penpine/render.py`'s `__all__` and re-export all three through the root
`penpine/__init__.py`.

`render_*` never raise on rendering: they read only already-present fields on
`Report`/`Finding`/`Attempt`. (They do not send anything.)

### Component 2 — `penpine/logging.py` (modify)

Replace the hand-rolled `_ColorFormatter` console path with rich's
`RichHandler`, using the **same shared `console`** from `penpine/render.py` so
logs and rendered blocks share one output stream.

- Console handler: `RichHandler(console=render.console, markup=True,
  rich_tracebacks=True, show_path=False)`. `markup=True` lets the interceptor
  color status codes; `rich_tracebacks=True` gives colored tracebacks.
- Remove `_ColorFormatter`, `_LEVEL_COLORS`, `_RESET` (obsolete once RichHandler
  owns level coloring).
- File handler: keep the optional plain `FileHandler`, but attach a formatter
  that **strips rich markup** from the final message so log files stay plain:

  ```python
  from rich.text import Text

  class _PlainFormatter(logging.Formatter):
      def format(self, record):
          s = super().format(record)
          return Text.from_markup(s).plain
  ```

- Preserve current behavior: idempotency (the `_penpine_console` /
  `_penpine_file` markers), `penpine` logger holds the handlers with
  `propagate=False`, children propagate up. `configure_logging(level=...,
  *, log_file=None)` signature is unchanged.

### Component 3 — `penpine/transport/interceptor.py` (modify)

`RequestLogInterceptor` emits richer, status-colored lines including response
size and timing. Dynamic content is escaped so payloads cannot corrupt markup.

```python
from rich.markup import escape
from penpine.render import _status_style, _humanize_bytes  # or local equivalents

async def before_send(self, request):
    _request_start.set(time.perf_counter())
    self._log.log(self._level, "[dim]->[/] %s %s",
                  request.method, escape(request.target))
    return request

async def after_receive(self, request, response):
    try:
        elapsed_ms = (time.perf_counter() - _request_start.get()) * 1000
        timing = f"{elapsed_ms:.0f} ms"
    except LookupError:
        timing = ""
    status = getattr(response, "status_code", "?")
    size = _humanize_bytes(len(getattr(response, "body", b"") or b""))
    style = _status_style(status)
    self._log.log(
        self._level,
        "[dim]<-[/] [%s]%s[/] %s %s   %s   %s",
        style, status, request.method, escape(request.target), size, timing,
    )
    return response
```

Notes:
- `escape(request.target)` is required: targets carry injected payloads which
  can contain `[` / `]` that rich would otherwise parse as markup.
- Send failures (refused/timeout/TLS) never reach `after_receive`, so only the
  `->` line appears for them; the failure reason surfaces in the report's
  errors block (`render_report`). This matches the existing
  "log on send, not only on receive" contract — do not remove the
  `before_send` log.
- To avoid a circular import (`transport` importing `render` which imports
  nothing from transport), importing the two helpers from `penpine.render` is
  fine — `render` depends only on `rich` and the attack result types, not on
  transport. If a cycle appears in practice, duplicate the two tiny helpers
  locally; prefer the shared import.

### Component 4 — `pyproject.toml` + docs (modify)

- `dependencies = ["jsonpath-ng>=1.6", "rich>=13"]`.
- README.md and CLAUDE.md: update the "only runtime dependency is
  `jsonpath-ng`" and "built entirely on raw sockets and the standard library"
  statements to say the **core** is stdlib + `jsonpath-ng`, with `rich` used
  for terminal presentation.

### Component 5 — scaffold `cli/templates/project/main.py.tmpl` (modify)

Replace the raw prints with the renderer. Sketch:

```python
from penpine.render import console, render_report, render_run_summary

results = []
for item in targets:
    for attack in config.ATTACKS:
        report = build_runner().run_sync(request, attack=attack)
        label = f"{item} / {attack.value}"
        render_report(report, console=console)
        results.append((label, report))
render_run_summary(results, console=console)
```

(Exact loop shape follows the current template's target/attack iteration; the
change is: drop the two `print(...)` lines, call `render_report` inside the
loop, accumulate `(label, report)`, call `render_run_summary` after.)

## Output specification

### Request lines
```
-> GET /search?q=' OR 1=1-- -
<- 200 GET /search?q=' OR 1=1-- -   1.2 kB   12 ms
<- 500 GET /search?q=' OR 1=1-- -   0.3 kB   28 ms
```
`->`/`<-` dim; status colored by class (2xx green, 3xx cyan, 4xx yellow, 5xx
red, unknown red).

### Finding panel (one per finding)
```
╭─ FINDING · HIGH · sqli ──────────────────────────╮
│ point    param:id                                │
│ payload  ' OR 1=1-- -                             │
│ status   500  (28 ms)                            │
│ evidence you have an error in your SQL syntax…   │
╰──────────────────────────────────────────────────╯
```
- Title: `FINDING · <CONFIDENCE> · <attack_type>`, styled by confidence.
- Rows: `point` (`finding.point.expr`), `payload` (truncated), `status` +
  timing from `finding.response`/attempt if available (omit the line if no
  response), `evidence` (truncated).
- Long `payload`/`evidence` truncated to a sensible width (e.g. 200 chars) with
  an ellipsis. Both are escaped for markup.

### Per-attack summary (in `render_report`)
A short line or one-row table: `<attack>  sent=N  failed=N  found=N`, with
`found` bold-red when `> 0`.

### Run summary (in `render_run_summary`)
```
 target / attack        sent  failed  found
 login.php / sqli         17       1      2
 login.php / xss          12       0      0
 TOTAL                    29       1      2
```
`found > 0` rows highlighted; `TOTAL` row bold.

### Errors block (in `render_report`, only when `report.errors`)
A short dim block: `errors: N` then up to ~3 representative reasons
(`str(attempt.error)`), so unreachable/failed sends are visible.

## Data available (for reference)

- `Report(request, attack_type, baseline, attempts)`; `.findings`, `.errors`,
  `.summary() -> {sent, failed, found}`.
- `Finding(attack_type, point, payload, confidence, evidence, request,
  response, meta)`; `Confidence` IntEnum (LOW=1, MEDIUM=2, HIGH=3, has `.name`).
- `Attempt` carries `test_case`, `request`, `response`, `finding`, `error`,
  `elapsed_ms`.
- `point.expr` is the locator string (e.g. `param:id`).
- `attack_type` is an `AttackType` enum (has `.value`).

The renderer reads these fields defensively (`getattr` where a field may be
absent, e.g. `response` on a failed attempt).

## Testing

### `tests/test_render.py` (new, top-level — mirrors `penpine/render.py`)
Use `Console(record=True)` and `console.export_text()` to assert on rendered
text:
- `render_report` on a report **with** a finding: output contains the point
  expr, the payload, the evidence, and `HIGH`.
- `render_report` on a report with **no** findings: renders the summary line
  (`sent=`, `found=0`) and does not crash.
- `render_report` on a report with **errors**: output shows `errors:` and a
  reason string.
- `render_run_summary` with multiple `(label, report)` pairs: totals row sums
  `sent`/`failed`/`found` correctly and each label appears.
- **Escaping**: a finding whose payload/evidence contains `[bold]` renders the
  literal text (markup not interpreted) — assert the literal bracket text is
  present in `export_text()`.
- `_status_style`, `_confidence_style`, `_humanize_bytes` unit tests for the
  class boundaries (200/301/404/500/`?`; HIGH/MEDIUM/LOW; 512 B / 1.2 kB).
- Re-export: `from penpine import render_report, render_run_summary, console`.

### `tests/transport/test_request_log.py` (update)
- Keep the existing "logged on send even without a response" regression test
  (message still contains `GET` and `/path`).
- Update the request+response test: the receive line now also contains the
  size and timing; assert status, method, target still present, and 2 records.
- Add an **escaping** test: a target containing `[` is logged without raising
  and the literal bracket survives (via `Text.from_markup(msg).plain` or by
  checking the escaped form).
- The autouse fixture that swaps the `penpine` logger's handlers for caplog is
  unaffected (it clears handlers; markup lives in the message string, which
  caplog captures raw).

### `tests/test_logging.py` and `tests/test_logging_file.py` (update)
- `tests/test_logging.py`: after `configure_logging()`, the `penpine` logger's
  console handler is a `rich.logging.RichHandler`; `configure_logging` remains
  idempotent (calling twice does not duplicate handlers). Remove/replace any
  assertions on the deleted `_ColorFormatter`.
- `tests/test_logging_file.py`: with `log_file=...`, the file contains **plain**
  text — a log message that included markup like `[green]200[/]` is written
  without the `[green]` tags.
- `tests/test_public_api.py` references `configure_logging`; confirm it still
  imports/exports cleanly after the logging changes.

### `tests/cli/test_generated_main.py` and `tests/cli/test_samples_run.py` (update)
These grep stdout and **must** change because stdout format changes:
- `test_generated_main_runs_attack_path`: keep `RUN_OK` sentinel (still printed
  by the injected check), but the report is now rendered via `render_run_summary`
  — the assertion on the old `== item ==` / summary dict is removed; assert the
  run completes (`RUN_OK`) and, optionally, that a summary table header token
  (e.g. `found`) appears.
- `test_samples_run.py`: the `FINDING_SAMPLES` check currently asserts
  `"'found': 0" not in result.stdout`. Update to assert against the new rendered
  output (e.g. the finding-bearing samples show a non-zero `found` in the
  rendered summary, or a `FINDING` panel token appears). Ensure the samples'
  own output (if they print) still round-trips — adjust sample scripts only if
  they printed the old summary dict.

## Non-goals / YAGNI

- No live/`Progress`/`Live` dashboard (deferred; renderer stays wrappable).
- No config knobs for colors/themes; `rich` auto-detects TTY and honors
  `NO_COLOR`/`FORCE_COLOR` out of the box.
- No request/response body syntax-highlighting in finding panels (evidence
  string is enough for v1).
- No change to the attack engine, runner, or data model — presentation only.
