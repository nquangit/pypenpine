# Penpine — CLI Project Scaffolder (`penpine new`) (Design Spec)

**Date:** 2026-06-15
**Status:** Approved for implementation planning
**Scope:** A command-line scaffolder that **creates a new penpine-based project** — folder, `requirements.txt`, virtualenv, and runnable base code with docs and a sample of every extension point. It does **not** run the attack flow.

---

## 1. Context

penpine (L0–L4d) is a complete, tested library but ships no executable. A new user
has no on-ramp: they must hand-assemble a project, figure out the editable
dependency on the (unpublished) local penpine source, and discover each extension
point from the README. This tool removes that friction by generating a working
starter project.

The scaffolder is delivered as a **`penpine` console-script subcommand**:
`penpine new <name>`. It is the library's first CLI surface. There is deliberately
**no `run` subcommand** — running attacks is the job of the generated project's
`main.py`, invoked by the user.

Depends on:
- The penpine package being importable (to locate its source root for the editable dependency).
- Python 3.11+ stdlib only: `argparse`, `importlib.resources`, `subprocess`, `venv`, `pathlib`, `re`, `shutil`.

**Design decisions (this round):**
- Delivery: a `penpine` console script with a `new` subcommand (new `penpine/cli/` package).
- Virtualenv: create `.venv` + `pip install` **by default**, with `--no-venv` to skip.
- penpine dependency: auto-detect the local penpine source root and write `-e <abs path>` into `requirements.txt`; fall back to a plain `penpine` spec (with a warning) when no source root exists.
- Output: a **runnable end-to-end demo** (`main.py`) plus a `samples/` library with one self-contained, offline-runnable example per documented extension point.
- Scaffolder internals (Approach A): the scaffold is stored as real `.tmpl` template files under `penpine/cli/templates/`, rendered by variable substitution and verified by a test that renders + imports + smoke-runs the generated project.

## 2. Goals & Non-Goals

**Goals**
- A `penpine new <name>` command that creates a complete, runnable starter project.
- Auto-detected editable dependency on the local penpine source.
- Default venv creation + dependency install, opt-out via `--no-venv`, tolerant of pip/network failure.
- A generated project whose `main.py` runs analyze→attack→report against a configurable target, and whose `samples/` each run offline and demonstrate one extension point.
- Templates that are real files (reviewable, lintable) and a test that proves the generated project is valid, working Python.
- Thorough error handling and a clean success/next-steps message.

**Non-Goals (documented follow-ups)**
- A `penpine run` subcommand / running the attack flow from the CLI.
- An interactive wizard (flags only; scriptable).
- PyInstaller frozen binaries or PyPI publication.
- Samples for every conceivable extension — only the documented public seams.

## 3. Module Layout

```
penpine/cli/
  __init__.py
  __main__.py          # enables `python -m penpine`
  main.py              # argparse top-level `penpine` cmd; dispatch subcommands; main() entry point
  commands/
    __init__.py
    new.py             # the `new` command: validate -> detect path -> render -> venv -> report
  scaffold.py          # template renderer: walk templates/, substitute vars, strip .tmpl, write tree
  venv.py              # create .venv + pip install, with tolerant error handling
  paths.py             # detect the local penpine source root + build the dependency spec
  templates/           # the scaffold, shipped as package data (see section 6)
```

`pyproject.toml` gains:
```toml
[project.scripts]
penpine = "penpine.cli.main:main"
```
and packaging config so `penpine/cli/templates/**` ships in the wheel/sdist (section 7).

## 4. Template Rendering (`scaffold.py`)

```python
def render_project(dst: Path, variables: dict[str, str], *, force: bool = False) -> list[Path]:
    """Render templates/ into dst. Returns the list of files written.
    Only *.tmpl files are variable-substituted (suffix stripped on write);
    all other files are copied verbatim. Subdirectory structure is preserved.
    Raises ScaffoldError if dst is non-empty and not force."""
```

- **Template source:** `importlib.resources.files("penpine.cli") / "templates"`, walked recursively.
- **`.tmpl` rule:** a file named `foo.py.tmpl` is rendered and written as `foo.py`. A file without `.tmpl` is copied byte-for-byte — the escape hatch for sample files that must contain literal `{{ }}` (e.g. a templated `.http` request used by a sample).
- **Substitution:** a small local helper using the **same placeholder regex as penpine's L3 templating** — `re.compile(r"\{\{\s*([^}\s]+)\s*\}\}")` — replacing each `{{ name }}` with `variables[name]`. An unknown placeholder raises `ScaffoldError` (fail fast on a template bug). (L3's `render()` is `Request`-bound and its substitution helper is private, so the convention is shared, not the function.)

**Variables:**

| Name | Value |
|---|---|
| `project_name` | the raw `<name>` argument |
| `project_slug` | an importable form of the name (see section 5) |
| `penpine_path` | absolute path to the local penpine source root, or empty when unavailable |
| `penpine_spec` | the requirements.txt line: `-e <penpine_path>` or `penpine` (section 5) |
| `date` | today's date, `YYYY-MM-DD` |
| `python_version` | `f"{sys.version_info.major}.{sys.version_info.minor}"` |

## 5. penpine path detection (`paths.py`)

```python
def find_penpine_root() -> Path | None:
    """Return the directory containing penpine's pyproject.toml, or None.
    Walk up from Path(penpine.__file__).parent looking for a pyproject.toml
    whose [project].name == "penpine". None when penpine is installed
    non-editably (e.g. site-packages with no source tree)."""

def penpine_spec(root: Path | None) -> str:
    """`-e <root>` when root is not None, else `penpine` (plain name)."""
```

- When `find_penpine_root()` returns `None`, `new` prints a warning that the editable path could not be detected and that `requirements.txt` uses a plain `penpine` spec (which requires penpine on an index), then proceeds.

**Name → slug:** lowercase; replace any run of non-`[a-z0-9]` characters with `_`; strip leading/trailing `_`; if the result is empty or starts with a digit, prefix `p_`. Used for any in-project Python identifier needs. The target directory uses the raw `<name>`.

## 6. Generated Project Layout

```
<name>/
  main.py                  # RUNNABLE end-to-end: load request -> analyze -> run attack -> print Report
  config.py                # Python config: target base URL, concurrency, proxy, tls verify, attacks
  requests/
    sample.http            # a sample raw HTTP request to attack
  samples/
    __init__.py
    custom_payload.py      # a PayloadGenerator subclass + offline demo
    custom_validator.py    # a Validator subclass + offline demo
    custom_module.py       # generator + validator -> AttackModule + register() + offline demo
    custom_rule.py         # a ClassificationRule for the analyzer + offline demo
    custom_auth.py         # AuthProvider + AuthScheme + AuthProfile (construction demo)
    custom_interceptor.py  # a transport Interceptor + demo
    data_sharing.py        # two Identities sharing captured data (IDOR pattern) + offline demo
    byo_test_cases.py      # bring-your-own TestCase list -> Runner(test_cases=...) + offline demo
  docs/
    README.md              # what it is, how to run, how to extend, per-sample index
  requirements.txt         # {{ penpine_spec }}  +  jsonpath-ng>=1.6
  .gitignore               # .venv/, __pycache__/, *.pyc, findings/
  .venv/                   # created unless --no-venv
```

**`main.py` (the one runnable end-to-end artifact):**
- Imports `config`, builds/loads a `Request` (from `requests/sample.http`, with the host taken from `config.TARGET`).
- Calls `register_builtins()` and registers the project's `samples.custom_module`.
- Constructs a `Runner` honoring `config` (concurrency, proxy, tls verify).
- Runs the attack(s) named in `config.ATTACKS` (overridable by a CLI arg to `main.py`) and prints `report.summary()` and each finding.
- **Safe by default:** `config.TARGET` defaults to a placeholder such as `http://127.0.0.1:8000` so a blind `python main.py` never hits an unintended host; the README instructs the user to set the real target. The user is responsible for authorization.

**`samples/*.py` (each self-contained and offline):**
- Each module defines its extension class(es) and a `demo()` plus `if __name__ == "__main__": demo()`.
- Demos use **synthetic responses** (`penpine.core.parse.http_parser.parse_response`) and **fake senders** (an object exposing `async def send(self, request)`), matching penpine's no-network test style.
- The validator, module, data-sharing, and byo-test-cases demos assert/print a produced `Finding` so they visibly work without a live target.

## 7. Packaging & Entry Point

- `pyproject.toml`:
  - `[project.scripts] penpine = "penpine.cli.main:main"`.
  - `[tool.setuptools] include-package-data = true`.
- `MANIFEST.in`: `recursive-include penpine/cli/templates *` (ships all template files, including those without a normal source suffix).
- Template files are stored with a `.tmpl` suffix where rendered, or their plain name where copied verbatim; both are picked up by the recursive include.
- Runtime access via `importlib.resources.files("penpine.cli") / "templates"` (works from an installed wheel and from a source checkout).

## 8. `penpine new` Command Flow (`commands/new.py`)

Signature: `penpine new <name> [--no-venv] [--force] [--python <exe>] [--dir <path>]`

1. **Parse & validate.** `name` (positional, required). Derive `slug` (section 5) and target dir = `Path(args.dir or ".") / name`.
2. **Pre-flight.** If the target dir exists and is non-empty and not `--force` → `ScaffoldError` (clean message, no writes). Record whether we created the dir (for rollback).
3. **Detect penpine.** `root = find_penpine_root()`; `spec = penpine_spec(root)`. Warn if `root is None`.
4. **Build variables** (section 4) and `render_project(target, variables, force=args.force)`.
5. **Virtualenv** (unless `--no-venv`): `create_venv(target, python=args.python or sys.executable)` then `pip_install(target)`. On `VenvError` (pip/network/venv failure): **warn with the manual commands and continue** — the files are valid; the scaffold is not aborted.
6. **Report success** + next steps: `cd <name>`, activate `.venv`, set `config.TARGET`, `python main.py`.

**Rollback rule:** if step 4/5 raises and **we created the target dir**, remove it; if `--force` was used into a pre-existing dir, never delete. Implemented by wrapping steps 4–5 in try/except that calls `shutil.rmtree(target)` only when `created_dir` is true.

**venv module (`venv.py`):**
```python
def create_venv(project_dir: Path, *, python: str, runner=subprocess.run) -> Path: ...
def pip_install(project_dir: Path, *, runner=subprocess.run) -> None: ...
```
- `runner` is injectable so unit tests drive a fake (no real venv).
- `pip_install` invokes the venv's own interpreter (`.venv/bin/python -m pip install -r requirements.txt`, `Scripts\python.exe` on Windows).
- Both raise `VenvError` on non-zero exit, surfacing stdout/stderr.

## 9. Errors

A new `penpine.cli.exceptions` module:
- `CliError(PenpineError)` — base for CLI failures.
- `ScaffoldError(CliError)` — invalid name, non-empty target without `--force`, unknown template placeholder, write failure.
- `VenvError(CliError)` — venv creation or pip install failed (caught in `new` and downgraded to a warning).

`main()` catches `CliError`, prints a concise message to stderr, and exits non-zero (status 2). Unexpected exceptions propagate (real bugs surface).

## 10. Testing Strategy (TDD)

All tests under `tests/cli/`. No network; no real venv except one opt-in slow test.

- **slug/validation (`paths.py`):** `slugify` over representative names (`"My Engagement"` → `my_engagement`, `"123app"` → `p_123app`, `"a-b.c"` → `a_b_c`).
- **path detection (`paths.py`):** `find_penpine_root()` returns the repo root in this checkout; `penpine_spec(None)` == `"penpine"`, `penpine_spec(Path("/x"))` == `"-e /x"`.
- **renderer (`scaffold.py`):** over a tiny temp `templates/` fixture — `a.py.tmpl` with `{{ project_name }}` renders to `a.py` with the value; a verbatim `keep.http` containing `{{ x }}` is copied unchanged; subdirs preserved; non-empty dst without `force` raises `ScaffoldError`; unknown placeholder raises.
- **venv (`venv.py`):** `create_venv`/`pip_install` call the injected fake runner with the expected argv; a non-zero fake exit raises `VenvError`.
- **command (`commands/new.py`):** with `--no-venv` into `tmp_path`, assert the full generated tree exists and `requirements.txt` contains the editable spec; non-empty dir without `--force` raises and **leaves the dir untouched**; a forced render into an existing dir does not delete it; a rollback test where rendering fails removes a dir we created.
- **integration (key):** `render` a project with `--no-venv`, add it to `sys.path`, **import every generated module**, and call each `samples.*.demo()` in-process — asserting the validator / module / data_sharing / byo demos return or print a `Finding`. Proves the scaffold is valid, working Python.
- **CLI smoke:** `subprocess` run of `python -m penpine new <tmp> --no-venv` exits 0 and creates the tree.
- **slow (opt-in, marked):** a real `penpine new` with venv creation + install succeeds and the project's `python main.py --help`/import works. Skipped by default.

## 11. Dependencies

- Runtime: none beyond the stdlib (`argparse`, `importlib.resources`, `subprocess`, `venv`, `pathlib`, `re`, `shutil`, `sys`). The generated project depends on penpine (editable) + `jsonpath-ng`.
- Dev/test: `pytest` (existing).

## 12. Forward Hooks

- A future `penpine run` (execute an attack from the CLI against a config) slots in as a second subcommand under the same `main.py` dispatch without disturbing `new`.
- Additional sample templates (new extension points) drop into `templates/.../samples/` and are auto-picked-up by the renderer and the import-everything integration test.
- An interactive wizard could wrap `new` later, reusing `render_project`/`paths`/`venv` unchanged.
