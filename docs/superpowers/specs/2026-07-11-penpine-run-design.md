# Penpine — `penpine run` CLI Subcommand (Design Spec)

**Date:** 2026-07-11
**Status:** Approved for implementation planning
**Scope:** A `penpine run` subcommand that fires attacks at a request from the command line, without writing a `main.py`. Sub-project D of Tier 3 (value-first order).

---

## 1. Context

penpine has a `Runner` (analyze → generate → send → validate → `Report`) and, as of sub-project C, `Request.from_curl`. The CLI so far only scaffolds projects (`penpine new`). `penpine run` closes the loop: paste a request, name an attack, get findings — the natural completion of the CLI that L4c's forward hooks anticipated.

Depends on (all existing):
- `Request.from_curl` / `from_url` / `from_file(path, scheme=, host=, port=)`; `parse_url` (`penpine/core/url.py`).
- `Runner(sender=None, *, max_concurrency=10)`, `Runner.run_sync(request, attack=…)`, `Runner.close()`; `Report.summary()`/`.findings`; `Finding.confidence.name`/`.point.expr`/`.evidence`.
- `register_builtins()`, `BUILTIN_MODULES` (modules named `sqli`, `xss`, `path-traversal`, `open-redirect`); `registry.get(name)` (raises `AttackConfigError` on unknown); `analyze(request).for_attack(name)`; `module.applies(kind)`, `module.generate(point, request)`.
- `Engine(*, tls=, proxy=, max_concurrency=)`, `TLSConfig(verify=…)`, `ProxyConfig.from_url(url)`.
- CLI: `penpine/cli/main.py` argparse dispatch; `CliError` (`penpine/cli/exceptions.py`) → exit 2.

**Decisions (this round):**
- **Inputs:** `--curl`, `--request FILE` (+`--target`), `--url` — exactly one required.
- **Output:** human-readable table to stdout; **no JSON** (that is the deferred Report-export sub-project).
- **Exit codes:** `0` normal; `1` only with `--fail-on-findings` and findings > 0; `2` on `CliError`.
- **Safety:** `--dry-run` previews points + payload counts and sends nothing; otherwise runs immediately (no interactive prompt); an "authorized targets only" reminder goes to stderr.
- **Attack selection:** `--attack` is a comma list or `all`, **default `all`** (every built-in module applied to the request).
- **Auth** is baked into the request (e.g. a pasted curl's `Authorization`/`Cookie`); no separate auth flags in v1.

## 2. Goals & Non-Goals

**Goals**
- `penpine run` builds a sendable `Request` from one of three inputs, resolves attacks, and either previews (`--dry-run`) or executes them, printing a readable report.
- Correct exit codes for scripting/CI (`--fail-on-findings`).
- Fully unit-testable via an injected fake sender — no sockets.

**Non-Goals (documented follow-ups)**
- JSON/SARIF/HTML output (the deferred Report-export sub-project).
- Auth/login flows from the CLI (bake auth into the request for now).
- `--dry-run` confirmation prompts / `--yes` (chosen against — prompts break scripting).
- HAR input, multi-request batch runs, multi-step chaining.

## 3. Command Surface

```
penpine run (--curl CMD | --request FILE | --url URL) [--target BASE_URL]
            [--attack LIST] [--dry-run] [--fail-on-findings]
            [--proxy URL] [--insecure] [--concurrency N]
```

Argparse (added to the existing `build_parser` in `penpine/cli/main.py`):
- `--curl` (str), `--request` (str, path), `--url` (str) — not marked mutually-exclusive at the argparse level (so the error message is ours); the command validates "exactly one".
- `--target` (str) — base URL supplying scheme/host/port for `--request`.
- `--attack` (str, default `"all"`).
- `--dry-run` (store_true), `--fail-on-findings` (store_true), `--insecure` (store_true).
- `--proxy` (str, default None), `--concurrency` (int, default 10).

## 4. Module Layout

```
penpine/cli/commands/run.py   # new — the run command (build request, resolve attacks, dry-run/execute, format)
penpine/cli/main.py           # modified — add the `run` subparser + dispatch returning run's exit code
```
`run.py` stays a single focused file (request-building, attack-resolution, dry-run, execution, formatting are all small). No new dependencies.

## 5. `run.py` API

```python
def run(
    *, curl=None, request_file=None, url=None, target=None,
    attacks="all", dry_run=False, fail_on_findings=False,
    proxy=None, insecure=False, concurrency=10, sender=None,
) -> int:
    ...
```
Returns the process exit code (`0`/`1`). Raises `CliError` for user errors (caught by `main` → exit 2). `sender` is an injection seam for tests (default `None` → a real `Engine` is built for a live run).

### 5.1 Request building — `_build_request(curl, request_file, url, target) -> Request`
- Exactly one of `curl`/`request_file`/`url` must be set, else `CliError("provide exactly one of --curl, --request, --url")`.
- `curl` → `Request.from_curl(curl)`.
- `url` → `Request.from_url(url)`.
- `request_file` → requires `target`; parse `target` with `parse_url` and call `Request.from_file(request_file, scheme=u.scheme, host=u.host, port=u.port)`. Missing `target` → `CliError("--request requires --target for connection info")`. A missing file surfaces as `CliError` (wrap `FileNotFoundError`).
- After building, require `req.meta.host and req.meta.port`, else `CliError("request has no connection target; use --target or a full URL")`.

### 5.2 Attack resolution — `_resolve_attacks(attacks) -> list[str]`
- `register_builtins()` first.
- `attacks == "all"` → `[m.name for m in BUILTIN_MODULES]`.
- else split on `,`, strip, drop empties; for each name `registry.get(name)` and on `AttackConfigError` raise `CliError(f"unknown attack {name!r}; registered: {…}")`.
- Empty resulting list → `CliError("no attacks selected")`.

### 5.3 Dry-run — `_dry_run(request, names) -> int`
- For each name: `module = registry.get(name)`; `points = [p for p in analyze(request).for_attack(name) if module.applies(p.kind)]`.
- Print `would attack ({name}):` then per point `  {p.expr}   {count} payloads` where `count = len(list(module.generate(p, request)))`; if no points, print `  (no applicable injection points)`.
- Send nothing. Return `0`.

### 5.4 Execution
- Build the sender if not injected: `engine = Engine(tls=TLSConfig(verify=not insecure), proxy=ProxyConfig.from_url(proxy) if proxy else None, max_concurrency=concurrency)`.
- `runner = Runner(sender=sender or engine, max_concurrency=concurrency)`.
- Print the authorized-use reminder to **stderr**.
- For each name: `report = runner.run_sync(request, attack=name)`; print the formatted block; accumulate `total_found += len(report.findings)`.
- `finally`: `runner.close()`; and close the engine if we created it.
- Return `1` if `fail_on_findings and total_found > 0` else `0`.

### 5.5 Formatting — `_format_report(name, report) -> str`
```
== {name} ==  sent {sent}  failed {failed}  found {found}
  [{confidence.name}] {point.expr} -> {evidence}
  ...
```
Using `report.summary()` (`{"sent","failed","found"}`) and iterating `report.findings`. No findings → just the header line.

## 6. `main.py` wiring

- Add the `run` subparser in `build_parser`.
- In `main`, dispatch: `if args.command == "run": return run_cmd.run(curl=args.curl, request_file=args.request, url=args.url, target=args.target, attacks=args.attack, dry_run=args.dry_run, fail_on_findings=args.fail_on_findings, proxy=args.proxy, insecure=args.insecure, concurrency=args.concurrency)`.
- The existing `except CliError: … return 2` already wraps it; the `new` branch keeps returning `0`.
- `run.py` imports are local/lazy where needed to avoid pulling transport/attack modules into `penpine new`'s path.

## 7. Errors

All user-facing failures are `CliError` (exit 2, stderr): wrong number of inputs, `--request` without `--target`, missing file, unknown attack, unsendable request (no meta). `BuildError` from request construction (e.g. a bad curl) is caught and re-raised as `CliError` so the CLI contract stays "CliError → exit 2". Per-attempt send/validator errors are already captured by the `Runner` (they appear in the `failed` count) and never crash the command.

## 8. Testing Strategy (TDD)

All unit-level, no sockets (a fake sender is injected via `sender=`).

- **`_build_request`:** `--curl` sets method/target/meta; `--url` sets meta; `--request`+`--target` sets meta from the target; `--request` without `--target` → `CliError`; two inputs → `CliError`; zero inputs → `CliError`; a bad curl → `CliError`.
- **`_resolve_attacks`:** `"all"` → the four built-in names; `"sqli,xss"` → `["sqli","xss"]`; `"nope"` → `CliError`; empty → `CliError`.
- **dry-run:** with a fake sender that records calls, `run(..., dry_run=True)` prints `would attack` + a payload count and the fake sender is **never called**; returns `0`.
- **execution:** a fake sender returning a SQL-error body for the injected request → `run(curl=…, attacks="sqli", sender=fake)` prints a `found 1` block and a `[HIGH]` line; returns `0`; with `fail_on_findings=True` returns `1`; a clean sender → `found 0`, returns `0` even with `fail_on_findings`.
- **main dispatch / smoke:** `python -m penpine run --url 'http://h/?q=1' --dry-run` exits `0` and prints `would attack`; `penpine run` with no input → exit `2`.
- **exit-code mapping:** `main(["run", …bad…])` returns `2` on `CliError`.

## 9. Dependencies

Runtime: none beyond existing (stdlib `argparse`; penpine transport/attack/core). No new dependencies. Python 3.11+.

## 10. Forward Hooks

- The deferred Report-export sub-project adds `--format json|sarif|html` + `--output FILE` on top of `run` without changing the run/resolve/execute core.
- Auth flags (`--bearer`, `--login-curl`, an `AuthProfile` from the CLI) can layer on later.
- HAR/batch input and `--fail-on-findings` severity thresholds are natural extensions.
