# `penpine run` CLI Subcommand Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `penpine run` subcommand that builds a request from `--curl`/`--request`/`--url`, resolves attacks, and either previews them (`--dry-run`) or executes them via the `Runner`, printing a readable report with `--fail-on-findings` exit-code gating.

**Architecture:** One new command module `penpine/cli/commands/run.py` with pure helpers (`_build_request`, `_resolve_attacks`) plus `run()` (dry-run + execute + format), wired into the existing argparse dispatch in `penpine/cli/main.py`. A `sender=` injection seam makes the whole command testable with a fake sender (no sockets).

**Tech Stack:** stdlib `argparse`; existing penpine core/attack/transport. No new dependencies. Python 3.11+.

**Spec:** `docs/superpowers/specs/2026-07-11-penpine-run-design.md`

## Global Constraints

- Commit WITHOUT GPG signing: `git -c commit.gpgsign=false commit -m "..."` (`-c` BEFORE `commit`).
- Gates are LIVE: before each commit run `ruff check <files> && ruff format <files>` (line-length 100; ruleset E,F,W,I,UP,B,C4,SIM) and `python -m pytest`.
- All user-facing errors are `CliError` (from `penpine.cli.exceptions`) → the existing `main` handler prints to stderr and returns exit code 2.
- Exit codes: `0` normal; `1` only when `--fail-on-findings` and total findings > 0; `2` on `CliError`.
- No new runtime dependencies. Imports inside `run.py` that pull transport/attack modules are LAZY (function-local) so `penpine new` does not load them.
- Do NOT run `git add -A`; stage only the files named per task. Leave the untracked `.superpowers/` scratch dir alone.
- Baseline suite is `354 passed, 1 skipped`; new tests add to it, nothing regresses.

Verified existing APIs (verbatim):
- `Request.from_curl(cmd)`, `Request.from_url(url)`, `Request.from_file(path, *, scheme=, host=, port=)`; `parse_url(url) -> ParsedUrl(scheme, host, port, path, query)`.
- `register_builtins()`; `BUILTIN_MODULES` (a list; each has `.name` — the names are `sqli`, `xss`, `path-traversal`, `open-redirect`); `registry.get(name)` raises `AttackConfigError` (from `penpine.attack.exceptions`) on unknown.
- `analyze(request)` (from `penpine.attack.analyze`) → object with `.for_attack(name) -> list` of points; each point has `.expr`/`.kind`; `module.applies(kind) -> bool`; `module.generate(point, request) -> iterable`.
- `Runner(sender=None, *, max_concurrency=10)`, `Runner.run_sync(request, attack=name) -> Report`, `Runner.close()`; `Report.summary() -> {"sent","failed","found"}`, `Report.findings` (list of `Finding` with `.confidence.name`, `.point.expr`, `.evidence`).
- `Engine(*, tls=, proxy=, max_concurrency=)`, `Engine.close()`; `TLSConfig(verify=bool)`; `ProxyConfig.from_url(url)`.
- `parse_response(bytes)` from `penpine.core.parse.http_parser` (for test fakes).

---

### Task 1: `run.py` helpers — `_build_request` + `_resolve_attacks`

**Files:**
- Create: `penpine/cli/commands/run.py`
- Test: `tests/cli/test_run_helpers.py`

**Interfaces:**
- Produces: `_build_request(curl=None, request_file=None, url=None, target=None) -> Request`; `_resolve_attacks(attacks="all") -> list[str]`. Task 2's `run()` consumes both.

- [ ] **Step 1: Write the failing test** — `tests/cli/test_run_helpers.py`:
```python
import pytest

from penpine.cli.commands.run import _build_request, _resolve_attacks
from penpine.cli.exceptions import CliError


def test_build_request_from_curl_sets_meta():
    req = _build_request(curl="curl 'https://t.example/api?id=1'")
    assert req.method == "GET"
    assert req.meta.host == "t.example"
    assert req.meta.port == 443


def test_build_request_from_url_sets_meta():
    req = _build_request(url="https://h/s?q=hi")
    assert req.meta.host == "h"
    assert req.meta.scheme == "https"


def test_build_request_from_file_needs_target(tmp_path):
    f = tmp_path / "r.http"
    f.write_text("GET /p HTTP/1.1\r\nHost: h\r\n\r\n")
    req = _build_request(request_file=str(f), target="https://h:8443")
    assert req.meta.host == "h"
    assert req.meta.port == 8443
    with pytest.raises(CliError):
        _build_request(request_file=str(f))  # no --target


def test_build_request_requires_exactly_one_input():
    with pytest.raises(CliError):
        _build_request()  # zero
    with pytest.raises(CliError):
        _build_request(curl="curl x", url="http://h/")  # two


def test_build_request_bad_curl_is_cli_error():
    with pytest.raises(CliError):
        _build_request(curl="curl -X POST")  # no URL -> BuildError -> CliError


def test_resolve_attacks_all_returns_builtins():
    names = _resolve_attacks("all")
    assert set(names) == {"sqli", "xss", "path-traversal", "open-redirect"}


def test_resolve_attacks_subset_and_unknown():
    assert _resolve_attacks("sqli,xss") == ["sqli", "xss"]
    with pytest.raises(CliError):
        _resolve_attacks("nope")
    with pytest.raises(CliError):
        _resolve_attacks(" , ")  # empty
```

- [ ] **Step 2: Run to confirm fail** — `python -m pytest tests/cli/test_run_helpers.py -v` → `ModuleNotFoundError: No module named 'penpine.cli.commands.run'`.

- [ ] **Step 3: Create `penpine/cli/commands/run.py`:**
```python
"""The `penpine run` command: fire attacks at a request from the CLI."""

from __future__ import annotations

import sys

from penpine.cli.exceptions import CliError

_AUTHORIZED_REMINDER = "penpine run: for authorized targets only."


def _build_request(curl=None, request_file=None, url=None, target=None):
    from penpine.core.message import Request
    from penpine.core.url import parse_url
    from penpine.exceptions import BuildError

    provided = [
        flag
        for flag, val in (("--curl", curl), ("--request", request_file), ("--url", url))
        if val
    ]
    if len(provided) != 1:
        raise CliError("provide exactly one of --curl, --request, --url")

    try:
        if curl:
            req = Request.from_curl(curl)
        elif url:
            req = Request.from_url(url)
        else:
            if not target:
                raise CliError("--request requires --target for connection info")
            u = parse_url(target)
            req = Request.from_file(request_file, scheme=u.scheme, host=u.host, port=u.port)
    except CliError:
        raise
    except FileNotFoundError as exc:
        raise CliError(f"request file not found: {request_file}") from exc
    except BuildError as exc:
        raise CliError(f"could not build request: {exc}") from exc

    if not (req.meta.host and req.meta.port):
        raise CliError("request has no connection target; use --target or a full URL")
    return req


def _resolve_attacks(attacks="all"):
    from penpine.attack import registry
    from penpine.attack.exceptions import AttackConfigError
    from penpine.attack.modules import BUILTIN_MODULES, register_builtins

    register_builtins()
    known = [m.name for m in BUILTIN_MODULES]
    if attacks == "all":
        return list(known)

    names = [n.strip() for n in attacks.split(",") if n.strip()]
    if not names:
        raise CliError("no attacks selected")
    for name in names:
        try:
            registry.get(name)
        except AttackConfigError as exc:
            raise CliError(f"unknown attack {name!r}; registered: {', '.join(known)}") from exc
    return names
```

- [ ] **Step 4: Run to confirm pass** — `python -m pytest tests/cli/test_run_helpers.py -v` → all pass.

- [ ] **Step 5: Lint, format, commit.**
```bash
ruff check penpine/cli/commands/run.py tests/cli/test_run_helpers.py && ruff format penpine/cli/commands/run.py tests/cli/test_run_helpers.py
git add penpine/cli/commands/run.py tests/cli/test_run_helpers.py
git -c commit.gpgsign=false commit -m "feat(cli): add penpine run request-building and attack-resolution helpers"
```

---

### Task 2: `run()` — dry-run, execution, formatting

**Files:**
- Modify: `penpine/cli/commands/run.py` (add `run`, `_dry_run`, `_execute`, `_format_report`)
- Test: `tests/cli/test_run_command.py`

**Interfaces:**
- Consumes: `_build_request`, `_resolve_attacks` (Task 1).
- Produces: `run(*, curl=None, request_file=None, url=None, target=None, attacks="all", dry_run=False, fail_on_findings=False, proxy=None, insecure=False, concurrency=10, sender=None) -> int`. Task 3's `main` dispatch calls it.

- [ ] **Step 1: Write the failing test** — `tests/cli/test_run_command.py`:
```python
from penpine.cli.commands.run import run
from penpine.core.parse.http_parser import parse_response


class FakeSender:
    """Records sent requests; returns a SQL-error body when a quote was injected."""

    def __init__(self):
        self.calls = []

    async def send(self, request):
        self.calls.append(request)
        raw = request.serialize()
        if b"%27" in raw or b"'" in raw:
            body = b"You have an error in your SQL syntax near '''"
        else:
            body = b"<html>ok</html>"
        return parse_response(b"HTTP/1.1 200 X\r\nContent-Length: %d\r\n\r\n" % len(body) + body)


class CleanSender:
    def __init__(self):
        self.calls = []

    async def send(self, request):
        self.calls.append(request)
        body = b"<html>ok</html>"
        return parse_response(b"HTTP/1.1 200 X\r\nContent-Length: %d\r\n\r\n" % len(body) + body)


def test_dry_run_lists_points_and_sends_nothing(capsys):
    fake = FakeSender()
    rc = run(curl="curl 'http://h/s?q=hi'", attacks="sqli", dry_run=True, sender=fake)
    out = capsys.readouterr().out
    assert rc == 0
    assert "would attack (sqli):" in out
    assert "param:q" in out
    assert "payloads" in out
    assert fake.calls == []  # nothing sent


def test_execute_reports_finding_and_exit_codes(capsys):
    rc = run(curl="curl 'http://h/s?q=hi'", attacks="sqli", sender=FakeSender())
    out = capsys.readouterr().out
    assert rc == 0
    assert "== sqli ==" in out
    assert "[HIGH]" in out
    assert "param:q" in out


def test_fail_on_findings_sets_exit_1():
    rc = run(curl="curl 'http://h/s?q=hi'", attacks="sqli", fail_on_findings=True,
             sender=FakeSender())
    assert rc == 1


def test_clean_run_exit_0_even_with_fail_flag(capsys):
    rc = run(curl="curl 'http://h/s?q=hi'", attacks="sqli", fail_on_findings=True,
             sender=CleanSender())
    out = capsys.readouterr().out
    assert rc == 0
    assert "found 0" in out
```

- [ ] **Step 2: Run to confirm fail** — `python -m pytest tests/cli/test_run_command.py -v` → `ImportError: cannot import name 'run'`.

- [ ] **Step 3: Append to `penpine/cli/commands/run.py`:**
```python
def _format_report(name, report):
    summary = report.summary()
    lines = [
        f"== {name} ==  sent {summary['sent']}  "
        f"failed {summary['failed']}  found {summary['found']}"
    ]
    for finding in report.findings:
        lines.append(f"  [{finding.confidence.name}] {finding.point.expr} -> {finding.evidence}")
    return "\n".join(lines)


def _dry_run(request, names):
    from penpine.attack import registry
    from penpine.attack.analyze import analyze

    analysis = analyze(request)
    for name in names:
        module = registry.get(name)
        points = [p for p in analysis.for_attack(name) if module.applies(p.kind)]
        print(f"would attack ({name}):")
        if not points:
            print("  (no applicable injection points)")
            continue
        for point in points:
            count = len(list(module.generate(point, request)))
            print(f"  {point.expr}   {count} payloads")
    print("(dry-run: nothing sent)")
    return 0


def _execute(request, names, *, fail_on_findings, proxy, insecure, concurrency, sender):
    from penpine.attack.runner import Runner

    print(_AUTHORIZED_REMINDER, file=sys.stderr)

    own_engine = None
    if sender is None:
        from penpine.transport.engine import Engine
        from penpine.transport.proxy import ProxyConfig
        from penpine.transport.tls import TLSConfig

        own_engine = Engine(
            tls=TLSConfig(verify=not insecure),
            proxy=ProxyConfig.from_url(proxy) if proxy else None,
            max_concurrency=concurrency,
        )
        sender = own_engine

    runner = Runner(sender=sender, max_concurrency=concurrency)
    total_found = 0
    try:
        for name in names:
            report = runner.run_sync(request, attack=name)
            total_found += len(report.findings)
            print(_format_report(name, report))
    finally:
        runner.close()
        if own_engine is not None:
            own_engine.close()

    return 1 if (fail_on_findings and total_found > 0) else 0


def run(
    *,
    curl=None,
    request_file=None,
    url=None,
    target=None,
    attacks="all",
    dry_run=False,
    fail_on_findings=False,
    proxy=None,
    insecure=False,
    concurrency=10,
    sender=None,
):
    request = _build_request(curl=curl, request_file=request_file, url=url, target=target)
    names = _resolve_attacks(attacks)
    if dry_run:
        return _dry_run(request, names)
    return _execute(
        request,
        names,
        fail_on_findings=fail_on_findings,
        proxy=proxy,
        insecure=insecure,
        concurrency=concurrency,
        sender=sender,
    )
```

- [ ] **Step 4: Run to confirm pass** — `python -m pytest tests/cli/test_run_command.py -v` → all 4 pass. (If `test_dry_run` shows no `param:q`, the analyzer isn't tagging the query param for sqli — verify `analyze` is imported from `penpine.attack.analyze`; do not change the assertion.)

- [ ] **Step 5: Lint, format, commit.**
```bash
ruff check penpine/cli/commands/run.py tests/cli/test_run_command.py && ruff format penpine/cli/commands/run.py tests/cli/test_run_command.py
git add penpine/cli/commands/run.py tests/cli/test_run_command.py
git -c commit.gpgsign=false commit -m "feat(cli): implement penpine run dry-run, execution, and report formatting"
```

---

### Task 3: Wire `run` into `main.py`

**Files:**
- Modify: `penpine/cli/main.py` (add the `run` subparser + dispatch)
- Test: `tests/cli/test_run_main.py`

**Interfaces:**
- Consumes: `penpine.cli.commands.run.run` (Task 2).

- [ ] **Step 1: Write the failing test** — `tests/cli/test_run_main.py`:
```python
import subprocess
import sys

from penpine.cli.main import main


def test_main_run_dry_run_returns_zero(capsys):
    rc = main(["run", "--url", "http://h/s?q=1", "--attack", "sqli", "--dry-run"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "would attack (sqli):" in out


def test_main_run_no_input_is_cli_error():
    rc = main(["run", "--attack", "sqli"])  # no --curl/--request/--url
    assert rc == 2


def test_python_m_penpine_run_dry_run_smoke():
    result = subprocess.run(
        [sys.executable, "-m", "penpine", "run", "--url", "http://h/s?q=1", "--dry-run"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "would attack" in result.stdout
```

- [ ] **Step 2: Run to confirm fail** — `python -m pytest tests/cli/test_run_main.py -v` → fails: argparse errors on the unknown `run` subcommand (SystemExit / nonzero), so `test_main_run_dry_run_returns_zero` fails.

- [ ] **Step 3a: Add the import at the top of `penpine/cli/main.py`** (next to the existing `from penpine.cli.commands import new as new_cmd`):
```python
from penpine.cli.commands import run as run_cmd
```

- [ ] **Step 3b: Add the `run` subparser inside `build_parser`** (after the `new` subparser block, before `return parser`):
```python
    run_p = sub.add_parser("run", help="run attacks against a request")
    run_p.add_argument("--curl", default=None, help="a 'Copy as cURL' command to attack")
    run_p.add_argument("--request", default=None, help="path to a raw .http request file")
    run_p.add_argument("--url", default=None, help="a URL to attack (bare GET)")
    run_p.add_argument("--target", default=None, help="base URL (scheme://host:port) for --request")
    run_p.add_argument("--attack", default="all", help="comma list of attacks, or 'all' (default)")
    run_p.add_argument(
        "--dry-run", action="store_true", help="list points/payloads; send nothing"
    )
    run_p.add_argument(
        "--fail-on-findings", action="store_true", help="exit 1 if any finding is found"
    )
    run_p.add_argument("--proxy", default=None, help="upstream proxy URL, e.g. http://127.0.0.1:8080")
    run_p.add_argument("--insecure", action="store_true", help="disable TLS certificate verification")
    run_p.add_argument("--concurrency", type=int, default=10, help="max concurrent requests")
```

- [ ] **Step 3c: Add the dispatch branch in `main`** — change the `if args.command == "new":` block to also handle `run`. Insert this `elif` immediately after the `new` branch's body (before the `except CliError` line):
```python
        elif args.command == "run":
            return run_cmd.run(
                curl=args.curl,
                request_file=args.request,
                url=args.url,
                target=args.target,
                attacks=args.attack,
                dry_run=args.dry_run,
                fail_on_findings=args.fail_on_findings,
                proxy=args.proxy,
                insecure=args.insecure,
                concurrency=args.concurrency,
            )
```
(The existing `new` branch keeps its `print(...)` block and the function still falls through to `return 0` for `new`. The `run` branch returns `run_cmd.run(...)`'s exit code directly; a `CliError` raised inside it is caught by the existing `except CliError` handler → `return 2`.)

- [ ] **Step 4: Run to confirm pass** — `python -m pytest tests/cli/test_run_main.py -v` → all 3 pass.

- [ ] **Step 5: Full suite + gates, then commit.**
```bash
python -m pytest -q            # expect: 354 baseline + new run tests all pass, 1 skipped
ruff check . && ruff format --check .
git add penpine/cli/main.py tests/cli/test_run_main.py
git -c commit.gpgsign=false commit -m "feat(cli): wire penpine run subcommand into the CLI dispatch"
```

---

### Final verification (after all tasks)

- [ ] `ruff check . && ruff format --check . && python -m pytest -q` → gates clean; suite green (354 baseline + new run tests, 1 skipped).
- [ ] Dry-run smoke against a real analyzer: `python -m penpine run --curl "curl 'http://h/s?id=1&q=hi'" --dry-run` prints `would attack` blocks for all four built-ins with payload counts, sending nothing.

---

## Self-Review

**Spec coverage:**
- §3 command surface / flags → Task 3 argparse. ✓
- §4 module layout (`run.py` + `main.py` wiring) → Tasks 1–3. ✓
- §5.1 `_build_request` (three inputs, `--target` for `--request`, exactly-one, meta guard, bad-curl→CliError) → Task 1 + tests. ✓
- §5.2 `_resolve_attacks` (`all`, subset, unknown→CliError, empty→CliError) → Task 1 + tests. ✓
- §5.3 dry-run (points + payload counts, sends nothing) → Task 2 `_dry_run` + `test_dry_run_lists_points_and_sends_nothing`. ✓
- §5.4 execution (Engine from proxy/insecure/concurrency, stderr reminder, per-attack run, finally-close) → Task 2 `_execute`. ✓
- §5.5 formatting → Task 2 `_format_report` + tests. ✓
- §6 main wiring + dispatch returning the exit code → Task 3. ✓
- §7 errors (CliError, BuildError→CliError) → Task 1 + tests. ✓
- §8 testing (helpers, dry-run no-send, execution+exit codes, main dispatch, subprocess smoke) → Tasks 1–3 tests. ✓

**Placeholder scan:** No TBD/TODO; every step has complete code. ✓

**Type/name consistency:** `_build_request(curl, request_file, url, target)` and `_resolve_attacks(attacks)` are defined in Task 1 and called by `run()` in Task 2 with matching keywords; `run(...)`'s full keyword set matches the `main` dispatch mapping in Task 3 (`request_file=args.request`, `attacks=args.attack`, `fail_on_findings=args.fail_on_findings`, `dry_run=args.dry_run`). `Runner`/`Engine`/`report.summary()`/`finding.confidence.name` match the verified signatures in Global Constraints. ✓
