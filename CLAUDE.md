# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

penpine is a layered Python pentesting framework built **entirely on raw sockets
and the standard library** — there is no third-party HTTP client (`requests`,
`httpx`, `urllib` are all off-limits). HTTP/1.1 is parsed and serialized by hand
so requests round-trip byte-for-byte and can be deliberately malformed. The core
(raw sockets, HTTP parse/serialize, attack engine) is built on the standard
library; the only non-stdlib runtime dependencies are `jsonpath-ng` (JSON-body
locators) and `rich` (terminal output). Requires Python 3.11+.

It is a **library you write code against**, not a menu-driven CLI. The CLI's only
job is scaffolding new projects (`penpine new`).

## Commands

```bash
pip install -e ".[dev]"        # install with the dev toolchain
pre-commit install             # install hooks (ruff + ruff-format run on commit)

pytest                         # full suite (~400 tests), no network required
pytest tests/attack/test_runner.py                 # one file
pytest tests/attack/test_runner.py::test_name      # one test
pytest -m slow                 # opt-in end-to-end tests that build a real virtualenv
pytest --cov=penpine --cov-report=term-missing     # tests + coverage

ruff check . && ruff format --check .   # lint + format — GATING in CI
mypy penpine                            # type check — ADVISORY (CI continue-on-error)
```

CI (`.gitea/workflows/ci.yml`) runs on Python 3.11 and 3.12. Ruff lint/format are
gating; mypy is advisory. Async tests use `asyncio_mode = "auto"` — no
`@pytest.mark.asyncio` decorators needed.

## Architecture

Built as strictly ordered layers under `penpine/`; each is independently usable
and tested, and `tests/` mirrors this layout package-for-package.

| Layer | Package | Responsibility |
|-------|---------|----------------|
| L0 | `core` | Byte-faithful `Request`/`Response`, HTTP parser/serializer (`core/parse`), headers, body views (`core/body`), the locator DSL, builders/loaders |
| L1 | `transport` | `Engine` — raw-socket async send, TLS, HTTP/SOCKS5 proxy, interceptors, connection pool |
| L2 | `auth` | Sessions, auth schemes, login providers, refresh gate/scheduler, `SessionManager`, `AuthProfile` |
| L3 | `data` | Thread-safe `Context` bus, extractors/capture, `{{ }}` templating, cross-role `Identity` |
| L4a/b | `attack`, `attack/analyze` | Attack contracts + global registry; the injection-point analyzer |
| L4c | `attack/runner.py` | `Runner` — analyze → generate → send → validate → `Report` |
| L4d | `attack/modules` | Concrete SQLi / XSS / path-traversal / open-redirect modules |

Public API is re-exported from `penpine/__init__.py`. When you add something
user-facing, wire it through the relevant layer's `__init__.py` (each layer
curates its own `__all__`) and, if top-level, through the root `__init__.py`.

### Sync/async duality

The core is `asyncio` throughout (transport and the attack runner). Every async
entry point has a synchronous facade suffixed `_sync` (`Engine.send_sync`,
`Runner.run_sync`, `Identity.send_sync`, …) that spins up/manages a loop so
callers never have to `await`. When adding an async method, add its `_sync`
twin.

### Immutability in L0

`Request`/`Response` are immutable; every mutator returns a copy
(`with_method`, `with_target`, `replace_at`, …). `serialize()` returns the exact
bytes that go on the wire.

### The locator DSL (L0)

Any part of a request is addressable by a string expression — `param:id`,
`json:$.user` (JSONPath), `header:Host`, `cookie:session`, `path-seg:2`. Read
with `request.locate(expr)`, replace with `request.replace_at(expr, value)`.
`request.injection_candidates()` enumerates every injectable location.

### The attack pipeline (L4)

1. **Analyze** (`attack/analyze`): `analyze(request)` runs `DEFAULT_RULES`
   (`analyze/rules.py`) over injection candidates and tags each `InjectionPoint`
   with candidate `attack_types` (e.g. `param:next` → open-redirect, sqli, ssrf,
   xss). Add a detection rule in `rules.py`.
2. **Runner** (`attack/runner.py`): selects the points the analyzer tagged for
   the chosen attack, asks the module's `PayloadGenerator` for payloads, inserts
   them, sends concurrently (`max_concurrency`, default 10) against a captured
   baseline, and runs the module's `Validator` to produce `Finding`s in a
   `Report`.
3. **Modules** (`attack/modules`): a module is a `PayloadGenerator` +
   `Validator` wrapped in an `AttackModule`, `register()`-ed into the global
   registry by name. The built-ins are the reference pattern; both generators
   and validators take their defaults (payload lists / signatures) as
   constructor args, so you can extend one without subclassing.

**Registration is explicit, never at import time.** Call `register_builtins()`
before running an attack. `BUILTIN_MODULES` (signature-based: sqli, xss,
traversal, redirect) and `DIFFERENTIAL_MODULES` (blind: `sqli-boolean`,
`sqli-time`) are kept separate — differential modules use an active-prober path
in the Runner (keyed by a module's `select_attack_type`) and are excluded from
the default signature module list.

**The Runner never raises out of a batch.** Every send/build/validator failure is
captured on that `Attempt.error` — one bad test case never aborts the run.
Preserve this property when touching `runner.py`.

### Senders are duck-typed

Anything exposing `async send(request)` is a valid Runner `sender` — `Engine`,
`SessionManager`, and `Identity` all qualify. This is how an attack runs through
an authenticated session: `Runner(sender=identity)`.

### TLS is off by default

The `Engine` does **not** verify TLS certs by default — targets are often
self-signed. Don't "fix" this to verify-by-default.

## CLI / scaffolding (`penpine/cli`)

`penpine new <name>` scaffolds a runnable project from
`cli/templates/project/` (creates a venv and installs deps unless `--no-venv`).
Templates are excluded from ruff (`extend-exclude`) and shipped as package data.
`cli/templates/project/samples/` holds the canonical examples of every extension
seam (custom module, validator, payload, interceptor, rule, auth, data-sharing)
— consult these when demonstrating or extending the framework.

## Conventions

- Typed exception hierarchy rooted at `penpine.exceptions.PenpineError`, with
  focused per-layer subclasses; catch broadly or narrowly.
- Namespaced loggers under `penpine.*`; `configure_logging(level=...)`.
- Ships `py.typed` — keep annotations complete on public surfaces.
- **Authorized testing only.** This framework is for systems you own or have
  written permission to assess.
- **Versioning & releases.** SemVer; releases are git tags `vX.Y.Z`. **Every merge
  to `main` is followed by a version bump: `python scripts/bump_version.py
  <patch|minor|major>`**, which rewrites `pyproject.toml`, commits, tags, and pushes.
  The tag push triggers `.gitea/workflows/release.yml` (build → publish to the Gitea
  PyPI registry → create a release). Do not hand-edit the version or create tags
  manually. Publishing needs a `PACKAGE_TOKEN` repo secret (Gitea PAT with
  `write:package` + `write:repository`) and Actions enabled on the repo.
