# Rich Terminal Output Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give penpine colorful, information-dense terminal output — status-colored request logs, per-finding panels, and run-summary tables — via a reusable `rich`-based renderer.

**Architecture:** New leaf module `penpine/render.py` owns a shared `rich` `Console` plus `render_report` / `render_run_summary` and small style helpers. `configure_logging` switches its console handler to rich's `RichHandler` (file handler stays plain via a markup-stripping formatter). `RequestLogInterceptor` emits status-colored lines with size + timing. `rich` becomes a presentation-only runtime dependency; the scaffold `main.py` calls the renderer instead of raw prints.

**Tech Stack:** Python 3.11+, `rich>=13`, stdlib `logging`, pytest.

## Global Constraints

- Python 3.11+; keep `from __future__ import annotations` in new modules.
- `rich` is the ONLY new dependency and is presentation-only — the core (sockets, parse, attack engine) stays stdlib + `jsonpath-ng`. Do not import `rich` from any core/transport/attack-engine logic except `penpine/render.py`, `penpine/logging.py`, and `penpine/transport/interceptor.py`.
- `penpine/render.py` is a LEAF: it imports only `rich` (+ stdlib). It must NOT import from `penpine.transport`, `penpine.attack`, or `penpine.logging` (avoids import cycles).
- All dynamic/user-controlled text rendered through rich markup (targets, payloads, evidence, labels, error strings) MUST be passed through `rich.markup.escape()` — payloads contain `[`/`]`.
- `configure_logging(level=..., *, log_file=None)` signature is unchanged and must stay idempotent (the `_penpine_console` / `_penpine_file` handler markers).
- Ruff lint + format are gating in CI. Templates under `cli/templates/` are ruff-excluded.
- Commit with `git commit --no-gpg-sign` (this user's repo has no signing key).
- Confidence styles: HIGH `bold red`, MEDIUM `yellow`, LOW `dim cyan`. Status styles: 2xx `green`, 3xx `cyan`, 4xx `yellow`, 5xx/unknown `red`.

---

## File Structure

- `penpine/render.py` — NEW. Shared `console`, `render_report`, `render_run_summary`, helpers `_status_style`/`_confidence_style`/`_humanize_bytes`/`_truncate`/`_finding_panel`.
- `penpine/__init__.py` — MODIFY. Re-export `console`, `render_report`, `render_run_summary`.
- `penpine/logging.py` — MODIFY. RichHandler console + markup-stripping file formatter; remove `_ColorFormatter`/`_LEVEL_COLORS`/`_RESET`.
- `penpine/transport/interceptor.py` — MODIFY. Richer status-colored request lines.
- `pyproject.toml` — MODIFY. Add `rich>=13`.
- `README.md`, `CLAUDE.md` — MODIFY. Update "only dependency" wording.
- `penpine/cli/templates/project/main.py.tmpl` — MODIFY. Call the renderer.
- Tests: `tests/test_render.py` (NEW), `tests/transport/test_request_log.py`, `tests/test_logging.py`, `tests/test_logging_file.py`, `tests/test_public_api.py` (MODIFY).

---

### Task 1: render helpers + shared console + rich dependency

**Files:**
- Modify: `pyproject.toml:10`
- Create: `penpine/render.py`
- Test: `tests/test_render.py`

**Interfaces:**
- Produces: module `penpine.render` with `console: rich.console.Console`, `_status_style(status) -> str`, `_confidence_style(confidence) -> str`, `_humanize_bytes(n: int) -> str`, `_truncate(s, limit=200) -> str`.

- [ ] **Step 1: Add rich to dependencies**

Edit `pyproject.toml` line 10:
```toml
dependencies = ["jsonpath-ng>=1.6", "rich>=13"]
```

- [ ] **Step 2: Install so rich is declared in the env**

Run: `pip install -e ".[dev]" -q`
Expected: completes; `python -c "import rich"` succeeds (rich 13.x already resolvable).

- [ ] **Step 3: Write the failing test**

Create `tests/test_render.py`:
```python
from penpine.render import (
    _confidence_style,
    _humanize_bytes,
    _status_style,
    _truncate,
    console,
)


def test_status_style_by_class():
    assert _status_style(200) == "green"
    assert _status_style(301) == "cyan"
    assert _status_style(404) == "yellow"
    assert _status_style(500) == "red"
    assert _status_style("?") == "red"


def test_confidence_style_by_name():
    class _C:
        def __init__(self, name):
            self.name = name

    assert _confidence_style(_C("HIGH")) == "bold red"
    assert _confidence_style(_C("MEDIUM")) == "yellow"
    assert _confidence_style(_C("LOW")) == "dim cyan"


def test_humanize_bytes():
    assert _humanize_bytes(512) == "512 B"
    assert _humanize_bytes(1536) == "1.5 kB"


def test_truncate_adds_ellipsis():
    assert _truncate("abc", 10) == "abc"
    assert _truncate("abcdef", 4).endswith("…")
    assert len(_truncate("abcdef", 4)) == 4


def test_console_is_a_rich_console():
    from rich.console import Console

    assert isinstance(console, Console)
```

- [ ] **Step 4: Run test to verify it fails**

Run: `pytest tests/test_render.py -q`
Expected: FAIL (`ModuleNotFoundError: penpine.render`).

- [ ] **Step 5: Create `penpine/render.py`**

```python
"""Rich terminal rendering for reports and findings (presentation-only)."""

from __future__ import annotations

from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

__all__ = ["console", "render_report", "render_run_summary"]

console = Console()

_MAX_FIELD = 200
_CONFIDENCE_STYLES = {"HIGH": "bold red", "MEDIUM": "yellow", "LOW": "dim cyan"}


def _status_style(status: object) -> str:
    try:
        code = int(status)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return "red"
    if 200 <= code < 300:
        return "green"
    if 300 <= code < 400:
        return "cyan"
    if 400 <= code < 500:
        return "yellow"
    return "red"


def _confidence_style(confidence: object) -> str:
    name = getattr(confidence, "name", str(confidence))
    return _CONFIDENCE_STYLES.get(name, "white")


def _humanize_bytes(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    kb = n / 1024
    if kb < 1024:
        return f"{kb:.1f} kB"
    return f"{kb / 1024:.1f} MB"


def _truncate(s: object, limit: int = _MAX_FIELD) -> str:
    s = str(s)
    return s if len(s) <= limit else s[: limit - 1] + "…"
```

- [ ] **Step 6: Run test to verify it passes**

Run: `pytest tests/test_render.py -q`
Expected: PASS (5 tests).

- [ ] **Step 7: Lint + format**

Run: `ruff check penpine/render.py tests/test_render.py && ruff format penpine/render.py tests/test_render.py`
Expected: clean.

- [ ] **Step 8: Commit**

```bash
git add pyproject.toml penpine/render.py tests/test_render.py
git commit --no-gpg-sign -m "feat(render): add rich console + style helpers; add rich dependency

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: render_report (finding panels + summary + errors)

**Files:**
- Modify: `penpine/render.py`
- Test: `tests/test_render.py`

**Interfaces:**
- Consumes: `_status_style`, `_confidence_style`, `_truncate`, `console` from Task 1; `Report`/`Attempt`/`Finding`/`Payload` from `penpine.attack`.
- Report shape (already exists): `report.summary() -> {"sent","failed","found"}`, `report.attempts` (each `Attempt` has `.finding`, `.response`, `.elapsed_ms`, `.error`), `report.errors` (list of `Attempt` with `.error`), `report.attack_type` (`AttackType` with `.value`, or `None`).
- Finding shape: `finding.point.expr` (str), `finding.payload.value` (str), `finding.confidence` (`.name`), `finding.evidence` (str), `finding.attack_type` (`.value`).
- Produces: `render_report(report, *, console=console) -> None` and `_finding_panel(finding, attempt) -> rich.panel.Panel`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_render.py`:
```python
from rich.console import Console

from penpine.attack.models import Confidence, Finding, InjectionPoint, Payload
from penpine.attack.results import Attempt, Report
from penpine.attack.types import AttackType
from penpine.render import render_report


def _point(expr="param:id"):
    return InjectionPoint(expr=expr, kind="param", name="id")


def _finding(evidence="SQL syntax error near", payload="' OR 1=1-- -"):
    return Finding(
        attack_type=AttackType.SQLI,
        point=_point(),
        payload=Payload(value=payload),
        confidence=Confidence.HIGH,
        evidence=evidence,
    )


class _Resp:
    def __init__(self, status_code=500):
        self.status_code = status_code


def _rec():  # a recording console
    return Console(record=True, width=100)


def test_render_report_with_finding_shows_fields():
    c = _rec()
    att = Attempt(test_case=object(), response=_Resp(500), finding=_finding(), elapsed_ms=28.0)
    report = Report(request=object(), attack_type=AttackType.SQLI, baseline=None, attempts=[att])
    render_report(report, console=c)
    out = c.export_text()
    assert "param:id" in out
    assert "1=1" in out
    assert "SQL syntax error" in out
    assert "HIGH" in out
    assert "sqli" in out


def test_render_report_no_findings_shows_summary():
    c = _rec()
    att = Attempt(test_case=object(), response=_Resp(200))
    report = Report(request=object(), attack_type=AttackType.XSS, baseline=None, attempts=[att])
    render_report(report, console=c)
    out = c.export_text()
    assert "sent=" in out
    assert "found=0" in out


def test_render_report_shows_errors():
    c = _rec()
    att = Attempt(test_case=object(), error=RuntimeError("connection refused"))
    report = Report(request=object(), attack_type=AttackType.SQLI, baseline=None, attempts=[att])
    render_report(report, console=c)
    out = c.export_text()
    assert "errors:" in out
    assert "connection refused" in out


def test_render_report_escapes_markup_in_payload():
    c = _rec()
    att = Attempt(test_case=object(), response=_Resp(500),
                  finding=_finding(payload="[bold]pwn[/]"), elapsed_ms=1.0)
    report = Report(request=object(), attack_type=AttackType.SQLI, baseline=None, attempts=[att])
    render_report(report, console=c)
    out = c.export_text()
    assert "[bold]pwn[/]" in out  # literal, not interpreted as markup
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_render.py -q`
Expected: FAIL (`ImportError: cannot import name 'render_report'`).

- [ ] **Step 3: Implement `render_report` + `_finding_panel`**

Add to `penpine/render.py` (after `_truncate`):
```python
def _finding_panel(finding: object, attempt: object) -> Panel:
    conf_name = getattr(finding.confidence, "name", str(finding.confidence))
    style = _confidence_style(finding.confidence)
    attack = getattr(finding.attack_type, "value", finding.attack_type)
    title = f"[{style}]FINDING · {conf_name} · {escape(str(attack))}[/]"

    grid = Table.grid(padding=(0, 2))
    grid.add_column(style="dim", justify="right")
    grid.add_column()
    grid.add_row("point", escape(str(finding.point.expr)))
    payload_val = getattr(finding.payload, "value", finding.payload)
    grid.add_row("payload", escape(_truncate(payload_val)))

    response = getattr(attempt, "response", None) or getattr(finding, "response", None)
    if response is not None:
        status = getattr(response, "status_code", "?")
        elapsed = getattr(attempt, "elapsed_ms", None)
        timing = f"  ({elapsed:.0f} ms)" if elapsed is not None else ""
        grid.add_row("status", f"[{_status_style(status)}]{escape(str(status))}[/]{timing}")

    grid.add_row("evidence", escape(_truncate(finding.evidence)))
    return Panel(grid, title=title, title_align="left", border_style=style, expand=False)


def render_report(report: object, *, console: Console = console) -> None:
    summary = report.summary()
    attack = getattr(report.attack_type, "value", report.attack_type)
    found = summary["found"]
    found_txt = f"[bold red]{found}[/]" if found else "0"
    console.print(
        f"\n[bold]{escape(str(attack))}[/]  "
        f"sent={summary['sent']}  failed={summary['failed']}  found={found_txt}"
    )
    for attempt in report.attempts:
        finding = getattr(attempt, "finding", None)
        if finding is not None:
            console.print(_finding_panel(finding, attempt))
    errors = report.errors
    if errors:
        console.print(f"[dim]errors: {len(errors)}[/]")
        for att in errors[:3]:
            console.print(f"[dim]  - {escape(str(att.error))}[/]")
```

Add `render_report` is already in `__all__`; `_finding_panel` stays private.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_render.py -q`
Expected: PASS (9 tests).

- [ ] **Step 5: Lint + format**

Run: `ruff check penpine/render.py tests/test_render.py && ruff format penpine/render.py tests/test_render.py`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add penpine/render.py tests/test_render.py
git commit --no-gpg-sign -m "feat(render): add render_report with finding panels, summary, errors

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: render_run_summary + root re-exports

**Files:**
- Modify: `penpine/render.py`, `penpine/__init__.py`
- Test: `tests/test_render.py`, `tests/test_public_api.py`

**Interfaces:**
- Consumes: `Report.summary()`, `console` from prior tasks.
- Produces: `render_run_summary(results, *, console=console) -> None` where `results` is an iterable of `(label: str, report)` pairs; re-exports `console`, `render_report`, `render_run_summary` from `penpine`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_render.py`:
```python
from penpine.render import render_run_summary


def test_render_run_summary_totals_and_labels():
    c = _rec()
    r1 = Report(
        request=object(), attack_type=AttackType.SQLI, baseline=None,
        attempts=[Attempt(test_case=object(), response=_Resp(500), finding=_finding(),
                          elapsed_ms=1.0),
                  Attempt(test_case=object(), error=RuntimeError("x"))],
    )
    r2 = Report(
        request=object(), attack_type=AttackType.XSS, baseline=None,
        attempts=[Attempt(test_case=object(), response=_Resp(200))],
    )
    render_run_summary([("login.php / sqli", r1), ("login.php / xss", r2)], console=c)
    out = c.export_text()
    assert "login.php / sqli" in out
    assert "login.php / xss" in out
    assert "TOTAL" in out
    # totals: sent 2+1=3, failed 1, found 1
    assert "3" in out and "TOTAL" in out


def test_run_summary_empty_does_not_crash():
    c = _rec()
    render_run_summary([], console=c)
    assert "TOTAL" in c.export_text()


def test_render_symbols_reexported_from_root():
    import penpine

    assert hasattr(penpine, "render_report")
    assert hasattr(penpine, "render_run_summary")
    assert hasattr(penpine, "console")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_render.py -q`
Expected: FAIL (`ImportError: cannot import name 'render_run_summary'`).

- [ ] **Step 3: Implement `render_run_summary`**

Add to `penpine/render.py`:
```python
def render_run_summary(results: object, *, console: Console = console) -> None:
    table = Table(title="run summary", title_justify="left", expand=False)
    table.add_column("target / attack")
    table.add_column("sent", justify="right")
    table.add_column("failed", justify="right")
    table.add_column("found", justify="right")

    tot_sent = tot_failed = tot_found = 0
    for label, report in results:
        s = report.summary()
        tot_sent += s["sent"]
        tot_failed += s["failed"]
        tot_found += s["found"]
        found_cell = Text(str(s["found"]), style="bold red") if s["found"] else Text("0")
        table.add_row(
            escape(str(label)), str(s["sent"]), str(s["failed"]), found_cell,
            style="bold" if s["found"] else None,
        )

    table.add_section()
    total_found = Text(str(tot_found), style="bold red") if tot_found else Text("0")
    table.add_row(
        Text("TOTAL", style="bold"), Text(str(tot_sent), style="bold"),
        Text(str(tot_failed), style="bold"), total_found,
    )
    console.print(table)
```

- [ ] **Step 4: Re-export from root**

Edit `penpine/__init__.py`: add after the `from penpine.logging import ...` line:
```python
from penpine.render import console, render_report, render_run_summary
```
and add to `__all__` (after `"get_logger",`):
```python
    "console",
    "render_report",
    "render_run_summary",
```

- [ ] **Step 5: Extend the public-API test**

Edit `tests/test_public_api.py`, add inside `test_top_level_exports`:
```python
    assert hasattr(penpine, "render_report")
    assert hasattr(penpine, "render_run_summary")
    assert hasattr(penpine, "console")
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest tests/test_render.py tests/test_public_api.py -q`
Expected: PASS.

- [ ] **Step 7: Lint + format**

Run: `ruff check penpine/render.py penpine/__init__.py tests/ && ruff format penpine/render.py penpine/__init__.py tests/test_render.py tests/test_public_api.py`
Expected: clean.

- [ ] **Step 8: Commit**

```bash
git add penpine/render.py penpine/__init__.py tests/test_render.py tests/test_public_api.py
git commit --no-gpg-sign -m "feat(render): add render_run_summary; re-export renderer from root

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 4: RichHandler logging + plain-text file formatter

**Files:**
- Modify: `penpine/logging.py`
- Test: `tests/test_logging.py`, `tests/test_logging_file.py`

**Interfaces:**
- Consumes: `penpine.render.console` (the shared Console).
- Produces: `configure_logging` whose console handler is a `rich.logging.RichHandler` and whose optional file handler writes markup-free text; `_ColorFormatter`/`_LEVEL_COLORS`/`_RESET` removed.

- [ ] **Step 1: Write the failing tests**

Edit `tests/test_logging.py` — replace `test_configure_logging_sets_level_and_handler` and add a RichHandler assertion:
```python
def test_configure_logging_sets_level_and_handler():
    from rich.logging import RichHandler

    log = configure_logging(level=logging.DEBUG)
    assert log.level == logging.DEBUG
    assert any(isinstance(h, RichHandler) for h in log.handlers)
    n = len(log.handlers)
    configure_logging(level=logging.INFO)
    assert len(log.handlers) == n
```

Edit `tests/test_logging_file.py` — add:
```python
def test_file_handler_strips_markup(tmp_path):
    path = tmp_path / "run.log"
    configure_logging(level="INFO", log_file=str(path))
    get_logger("penpine.demo").info("[green]200[/] hello-markup")
    for h in logging.getLogger(_ROOT).handlers:
        h.flush()
    text = path.read_text()
    assert "hello-markup" in text
    assert "[green]" not in text  # markup stripped in file output
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_logging.py tests/test_logging_file.py -q`
Expected: FAIL (`test_configure_logging_sets_level_and_handler` — no RichHandler; `test_file_handler_strips_markup` — `[green]` present).

- [ ] **Step 3: Rewrite `penpine/logging.py`**

Replace the whole file with:
```python
"""Shared logging for penpine. No side effects at import time."""

from __future__ import annotations

import logging

from rich.logging import RichHandler
from rich.text import Text

from penpine.render import console as _console

_ROOT_NAME = "penpine"


class _PlainFormatter(logging.Formatter):
    """Formatter that strips rich markup so log files stay plain text."""

    def format(self, record: logging.LogRecord) -> str:
        s = super().format(record)
        try:
            return Text.from_markup(s).plain
        except Exception:
            return s


def get_logger(name: str) -> logging.Logger:
    """Return a namespaced logger. Does not attach handlers."""
    return logging.getLogger(name)


def configure_logging(
    level: int | str = logging.INFO, *, log_file: str | None = None
) -> logging.Logger:
    """Attach a rich console handler (and optionally a plain file handler) to the
    penpine root logger. `level` may be an int or a level-name string.
    Idempotent: repeat calls do not duplicate handlers."""
    log = logging.getLogger(_ROOT_NAME)
    log.setLevel(level)
    log.propagate = False

    if not any(getattr(h, "_penpine_console", False) for h in log.handlers):
        handler = RichHandler(
            console=_console, markup=True, rich_tracebacks=True, show_path=False
        )
        handler._penpine_console = True  # type: ignore[attr-defined]
        handler.setFormatter(logging.Formatter("%(name)s: %(message)s"))
        log.addHandler(handler)

    if log_file is not None:
        target = str(log_file)
        if not any(getattr(h, "_penpine_file", None) == target for h in log.handlers):
            file_handler = logging.FileHandler(target)
            file_handler._penpine_file = target  # type: ignore[attr-defined]
            file_handler.setFormatter(_PlainFormatter("%(levelname)s %(name)s: %(message)s"))
            log.addHandler(file_handler)

    return log
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_logging.py tests/test_logging_file.py -q`
Expected: PASS.

- [ ] **Step 5: Lint + format**

Run: `ruff check penpine/logging.py tests/test_logging.py tests/test_logging_file.py && ruff format penpine/logging.py tests/test_logging.py tests/test_logging_file.py`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add penpine/logging.py tests/test_logging.py tests/test_logging_file.py
git commit --no-gpg-sign -m "feat(logging): use rich RichHandler for console; strip markup in log files

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 5: richer status-colored request logging

**Files:**
- Modify: `penpine/transport/interceptor.py`
- Test: `tests/transport/test_request_log.py`

**Interfaces:**
- Consumes: `penpine.render._status_style`, `penpine.render._humanize_bytes`, `rich.markup.escape`.
- Produces: `RequestLogInterceptor` whose receive line contains a colored status + size + timing; send line unchanged in spirit (still logs in `before_send`).

- [ ] **Step 1: Update the tests**

Edit `tests/transport/test_request_log.py`, replace `test_request_and_response_logged_and_passthrough` and add an escaping test:
```python
async def test_request_and_response_logged_and_passthrough(caplog):
    ic = RequestLogInterceptor()
    req = Request.from_url("http://t/path?x=1")
    resp = parse_response(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nok")
    with caplog.at_level(logging.INFO, logger="penpine.transport"):
        await ic.before_send(req)
        out = await ic.after_receive(req, resp)
    assert out is resp  # passthrough, unchanged
    text = "\n".join(r.getMessage() for r in caplog.records)
    assert "GET" in text and "/path?x=1" in text  # request line
    assert "200" in text  # response status
    assert "B" in text  # humanized size unit present
    assert len(caplog.records) == 2  # one on send, one on receive


async def test_target_with_brackets_is_escaped(caplog):
    ic = RequestLogInterceptor()
    req = Request.from_url("http://t/path?q=%5Bbold%5D")  # decodes to [bold]
    with caplog.at_level(logging.INFO, logger="penpine.transport"):
        await ic.before_send(req)
    text = "\n".join(r.getMessage() for r in caplog.records)
    # escaped for rich markup: the raw message carries a backslash-escaped bracket
    assert "\\[" in text or "[bold]" not in text
```

Keep `test_request_logged_on_send_even_without_a_response` and `test_request_log_interceptor_reexported` unchanged.

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/transport/test_request_log.py -q`
Expected: FAIL (`assert "B" in text` — current line has no size; escaping test fails).

- [ ] **Step 3: Update `RequestLogInterceptor`**

Edit `penpine/transport/interceptor.py`. Add imports at top (after existing imports):
```python
from rich.markup import escape

from penpine.render import _humanize_bytes, _status_style
```
Replace `before_send` and `after_receive`:
```python
    async def before_send(self, request):
        _request_start.set(time.perf_counter())
        self._log.log(self._level, "[dim]->[/] %s %s", request.method, escape(request.target))
        return request

    async def after_receive(self, request, response):
        try:
            elapsed_ms = (time.perf_counter() - _request_start.get()) * 1000
            timing = f"{elapsed_ms:.0f} ms"
        except LookupError:
            timing = ""
        status = getattr(response, "status_code", "?")
        size = _humanize_bytes(len(getattr(response, "body", b"") or b""))
        self._log.log(
            self._level,
            "[dim]<-[/] [%s]%s[/] %s %s   %s   %s",
            _status_style(status),
            status,
            request.method,
            escape(request.target),
            size,
            timing,
        )
        return response
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/transport/test_request_log.py -q`
Expected: PASS (4 tests).

- [ ] **Step 5: Lint + format**

Run: `ruff check penpine/transport/interceptor.py tests/transport/test_request_log.py && ruff format penpine/transport/interceptor.py tests/transport/test_request_log.py`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add penpine/transport/interceptor.py tests/transport/test_request_log.py
git commit --no-gpg-sign -m "feat(transport): status-colored request logs with size and timing

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 6: docs — update the stdlib-only wording

**Files:**
- Modify: `README.md`, `CLAUDE.md`

**Interfaces:** none (documentation).

- [ ] **Step 1: Locate the claims**

Run: `grep -n "only.*dependency\|jsonpath-ng\|standard library\|raw sockets" README.md CLAUDE.md`
Expected: the "only runtime dependency is `jsonpath-ng`" / "entirely on raw sockets and the standard library" sentences.

- [ ] **Step 2: Update `CLAUDE.md`**

In the "What this is" paragraph, change the dependency sentence to reflect that the CORE is stdlib + `jsonpath-ng`, and `rich` is a presentation-only dependency. Example replacement for the relevant sentence:
> The core (raw sockets, HTTP parse/serialize, attack engine) is built on the standard library; the only non-stdlib runtime dependencies are `jsonpath-ng` (JSON-body locators) and `rich` (terminal output). Requires Python 3.11+.

- [ ] **Step 3: Update `README.md`**

Apply the equivalent change to the matching sentence(s) in `README.md` (keep the raw-sockets ethos; clarify `rich` is for terminal presentation only). Match the file's existing tone/format.

- [ ] **Step 4: Verify no stale claim remains**

Run: `grep -n "only runtime dependency is .jsonpath-ng.\|only dependency" README.md CLAUDE.md`
Expected: no sentence still claims jsonpath-ng is the *only* dependency.

- [ ] **Step 5: Commit**

```bash
git add README.md CLAUDE.md
git commit --no-gpg-sign -m "docs: note rich as a presentation-only runtime dependency

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 7: scaffold main.py uses the renderer

**Files:**
- Modify: `penpine/cli/templates/project/main.py.tmpl`
- Verify (no edit expected): `tests/cli/test_generated_main.py`, `tests/cli/test_samples_run.py`

**Interfaces:**
- Consumes: `penpine.render.console`, `render_report`, `render_run_summary`.
- Note: `test_generated_main.py` only asserts the `RUN_OK` sentinel and `test_samples_run.py` only asserts the samples' own stdout — neither greps `main.py`'s summary line, so the template change should NOT break them. Verify by running; do not edit unless they fail.

- [ ] **Step 1: Edit the template imports**

In `penpine/cli/templates/project/main.py.tmpl`, add to the `from penpine ...` import block:
```python
from penpine.render import console, render_report, render_run_summary
```
(Place it with the other `from penpine...` imports near the top.)

- [ ] **Step 2: Replace the output loop**

Replace the `main()` body's try-block loop (lines around 52-62) so it accumulates results and renders:
```python
    try:
        results = []
        for attack in config.ATTACKS:
            item = attack.value
            if checkpoint.is_done(item):
                log.info("skip %s (already done)", item)
                continue
            report = runner.run_sync(request, attack=attack)
            render_report(report, console=console)
            results.append((item, report))
            checkpoint.mark_done(item)
        render_run_summary(results, console=console)
    except KeyboardInterrupt:
        log.warning("interrupted; progress saved to %s (rerun to resume)", config.CHECKPOINT_FILE)
    finally:
        runner.close()
```
(Removes the two `print(...)` lines; keeps the checkpoint/skip/Ctrl+C/finally logic intact.)

- [ ] **Step 3: Run the scaffold tests**

Run: `pytest tests/cli/test_generated_main.py tests/cli/test_samples_run.py -q`
Expected: PASS. If `test_samples_run.py` fails on a `'found': 0` assertion, that means a sample prints the old summary dict — in that case update only the failing assertion to match the sample's actual output (do NOT change unrelated samples).

- [ ] **Step 4: Full suite + lint**

Run: `pytest -q && ruff check . && ruff format --check .`
Expected: all pass; ruff clean (templates are ruff-excluded).

- [ ] **Step 5: Commit**

```bash
git add penpine/cli/templates/project/main.py.tmpl
git commit --no-gpg-sign -m "feat(scaffold): render reports + run summary with rich in generated main

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Self-Review Notes

- **Spec coverage:** Component 1 → Tasks 1-3; Component 2 (logging) → Task 4; Component 3 (interceptor) → Task 5; Component 4 (pyproject+docs) → Task 1 (dep) + Task 6 (docs); Component 5 (scaffold) → Task 7. Output spec (request lines, finding panel, summaries, errors block) → Tasks 2, 3, 5. Testing spec → each task's tests.
- **Spec reconciliation:** the design doc predicted `test_generated_main.py` and `test_samples_run.py` "must change." On inspection they assert only the `RUN_OK` sentinel and the samples' own stdout respectively — not `main.py`'s summary line — so Task 7 verifies rather than rewrites them, editing only if a run reveals an actual failing assertion.
- **Type consistency:** `finding.payload` is a `Payload` (use `.value`); `finding.point.expr`, `finding.evidence` are strings; `report.errors` is a list of `Attempt` (use `.error`); `report.attempts[i].elapsed_ms`/`.response` used for finding timing/status. `render_run_summary` takes `(label, report)` pairs — matches the scaffold's `(item, report)`.
- **Import safety:** `penpine/render.py` imports only `rich`; `penpine/logging.py` and `penpine/transport/interceptor.py` import FROM `render` (one direction) — no cycle.
