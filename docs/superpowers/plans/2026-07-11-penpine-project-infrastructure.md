# Penpine Project Infrastructure (Tier 1 + Tier 2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add development-workflow tooling (ruff lint+format, mypy, coverage, pre-commit, Gitea Actions CI) and packaging/metadata hygiene (MIT LICENSE + full `pyproject` metadata + `py.typed`) to the penpine repo, with pragmatic gating.

**Architecture:** Configuration-only work plus one mechanical auto-format pass. Ruff and pytest are hard gates; mypy is advisory; coverage is report-only. CI runs on Gitea Actions (GitHub-Actions-compatible YAML). No library logic changes.

**Tech Stack:** ruff, mypy, pytest-cov, pre-commit, setuptools, Gitea/Forgejo Actions. Python 3.11/3.12.

**Spec:** `docs/superpowers/specs/2026-07-11-penpine-project-infrastructure-design.md`

## Global Constraints

- Commit WITHOUT GPG signing: `git -c commit.gpgsign=false commit -m "..."` (the `-c` flag goes BEFORE `commit`). Every commit in this plan uses this form.
- `line-length = 100`; ruff `target-version = "py311"`; `requires-python = ">=3.11"`.
- Ruff lint ruleset: exactly `["E", "F", "W", "I", "UP", "B", "C4", "SIM"]`.
- Ruff (lint + format) and pytest are **gating**. mypy is **advisory** (`continue-on-error` in CI, never gates). Coverage is **report-only** (no `--cov-fail-under`).
- Exclude `penpine/cli/templates` from ruff and from whitespace/EOF hygiene hooks (template files are intentionally verbatim; do not reformat them).
- No new **runtime** dependencies (runtime stays `jsonpath-ng>=1.6`). New tools go in the `dev` extra only.
- License: **MIT**, copyright `2026 nquangit`, author email `huynhngocq5@gmail.com`, repo URL `https://git.nquangit.io.vn/nquangit/pypenpine`.
- The full suite baseline is **327 passed, 1 skipped**. No task may change that (the one-time format pass must be behavior-preserving).

---

### Task 1: Ruff config, dev extra, and one-time normalization

**Files:**
- Modify: `pyproject.toml` (add `[tool.ruff]` + `[tool.ruff.lint]`; add `ruff` to `dev`)
- Modify (mechanical): all `penpine/**/*.py` and `tests/**/*.py` touched by `ruff format`/`--fix`

**Interfaces:**
- Produces: a ruff configuration later tasks (pre-commit, CI) invoke via `ruff check .` / `ruff format --check .`.

- [ ] **Step 1: Add ruff config and dev dependency to `pyproject.toml`.**

Add `ruff>=0.6` to the `dev` list in `[project.optional-dependencies]`:
```toml
[project.optional-dependencies]
dev = ["pytest>=8.0", "pytest-asyncio>=0.23", "ruff>=0.6"]
```
Add these two tables (place them after `[tool.setuptools.package-data]`):
```toml
[tool.ruff]
line-length = 100
target-version = "py311"
extend-exclude = ["penpine/cli/templates"]

[tool.ruff.lint]
select = ["E", "F", "W", "I", "UP", "B", "C4", "SIM"]
```

- [ ] **Step 2: Install the dev toolchain.**

Run: `pip install -e ".[dev]"`
Expected: installs ruff (and existing pytest deps) without error.

- [ ] **Step 3: Commit the config (before touching code) so the normalization diff is isolated.**

```bash
git add pyproject.toml
git -c commit.gpgsign=false commit -m "build: add ruff config and dev extra"
```

- [ ] **Step 4: Auto-fix and format the tree.**

Run: `ruff check --fix . && ruff format .`
Expected: ruff rewrites imports/format and reports remaining non-auto-fixable findings (if any).

- [ ] **Step 5: Resolve any residual lint findings minimally (behavior-preserving).**

Run: `ruff check .`
For each remaining finding: prefer a minimal, obviously-safe edit; if a `B`/`SIM` rule would require restructuring logic, instead silence it on that line with `# noqa: <CODE>  # <one-word reason>` rather than change behavior. Do NOT broaden the global `select`/`ignore`. Re-run `ruff check .` until clean.
Expected final: `ruff check .` prints `All checks passed!`

- [ ] **Step 6: Verify format is stable and behavior is unchanged.**

Run: `ruff format --check . && python -m pytest -q`
Expected: format check passes; tests show `327 passed, 1 skipped`.

- [ ] **Step 7: Commit the normalization.**

```bash
git add -A
git -c commit.gpgsign=false commit -m "style: normalize codebase with ruff format and autofix"
```

---

### Task 2: mypy (advisory) config + `py.typed`

**Files:**
- Create: `penpine/py.typed` (empty)
- Modify: `pyproject.toml` (add `[tool.mypy]`; add `mypy` to `dev`; add `py.typed` to package-data)

**Interfaces:**
- Consumes: ruff config from Task 1 (unchanged).
- Produces: a `mypy` config so `mypy` (bare) checks `penpine`; a shipped `py.typed` marker (PEP 561).

- [ ] **Step 1: Create the marker file.**

Create `penpine/py.typed` as an empty file:
```bash
: > penpine/py.typed
```

- [ ] **Step 2: Update `pyproject.toml`.**

Add `mypy>=1.11` to the `dev` list. Add the mypy config table (after the ruff tables):
```toml
[tool.mypy]
python_version = "3.11"
files = ["penpine"]
ignore_missing_imports = true
```
Add the `py.typed` entry to the existing `[tool.setuptools.package-data]` table (keep the `penpine.cli` entry):
```toml
[tool.setuptools.package-data]
"penpine" = ["py.typed"]
"penpine.cli" = ["templates/**/*", "templates/**/.*"]
```

- [ ] **Step 3: Install and run mypy (advisory — record the baseline).**

Run: `pip install -e ".[dev]" && mypy`
Expected: mypy runs to completion and prints either `Success: no issues found` or a count like `Found N errors in M files`. **Record N** in the commit body — this is the advisory baseline, NOT a gate. Do not fix errors in this task.

- [ ] **Step 4: Confirm tests still green and the marker is packaged.**

Run: `python -m pytest -q`
Expected: `327 passed, 1 skipped`.
Run: `pip show -f penpine 2>/dev/null | grep py.typed || echo "editable-install: verified via build in Task 5"`
Expected: prints a `py.typed` path, or the editable-install note (wheel packaging is verified in Task 5).

- [ ] **Step 5: Commit.**

```bash
git add pyproject.toml penpine/py.typed
git -c commit.gpgsign=false commit -m "build: add advisory mypy config and py.typed marker (baseline: <N> errors)"
```

---

### Task 3: Coverage config

**Files:**
- Modify: `pyproject.toml` (add `[tool.coverage.run]` + `[tool.coverage.report]`; add `pytest-cov` to `dev`)

**Interfaces:**
- Produces: coverage config so `pytest --cov=penpine` reports (no floor).

- [ ] **Step 1: Update `pyproject.toml`.**

Add `pytest-cov>=5.0` to the `dev` list. Add the coverage tables (after the mypy table):
```toml
[tool.coverage.run]
source = ["penpine"]
branch = true

[tool.coverage.report]
show_missing = true
```

- [ ] **Step 2: Install and run coverage.**

Run: `pip install -e ".[dev]" && python -m pytest --cov=penpine --cov-report=term-missing -q`
Expected: `327 passed, 1 skipped` followed by a coverage table (a `TOTAL` line with a percentage). No failure on coverage (no floor configured).

- [ ] **Step 3: Commit.**

```bash
git add pyproject.toml
git -c commit.gpgsign=false commit -m "build: add report-only coverage config (pytest-cov)"
```

---

### Task 4: pre-commit config

**Files:**
- Create: `.pre-commit-config.yaml`
- Modify: `pyproject.toml` (add `pre-commit` to `dev`)

**Interfaces:**
- Consumes: the ruff config from Task 1 (the ruff hooks respect `pyproject.toml`).
- Produces: a pre-commit config developers install with `pre-commit install`.

- [ ] **Step 1: Create `.pre-commit-config.yaml`.**

```yaml
repos:
  - repo: https://github.com/pre-commit/pre-commit-hooks
    rev: v5.0.0
    hooks:
      - id: trailing-whitespace
        exclude: ^penpine/cli/templates/
      - id: end-of-file-fixer
        exclude: ^penpine/cli/templates/
      - id: check-yaml
      - id: check-toml
      - id: check-merge-conflict
      - id: check-added-large-files
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.6.9
    hooks:
      - id: ruff
        args: [--fix]
      - id: ruff-format
```

- [ ] **Step 2: Add `pre-commit` to the `dev` extra in `pyproject.toml`.**

The `dev` list becomes:
```toml
dev = ["pytest>=8.0", "pytest-asyncio>=0.23", "ruff>=0.6", "mypy>=1.11", "pytest-cov>=5.0", "pre-commit>=3.7"]
```

- [ ] **Step 3: Validate the config (offline-safe) and run it if network allows.**

Run: `pip install -e ".[dev]" && pre-commit validate-config .pre-commit-config.yaml && echo CONFIG_OK`
Expected: prints `CONFIG_OK` (schema valid; works without network).
Then run: `pre-commit run --all-files`
Expected: all hooks pass (Task 1 already normalized the tree). **If** pre-commit cannot fetch hook repositories (no network to github.com), that is acceptable for this task — the `validate-config` + `CONFIG_OK` above is the required gate; note the network limitation in the commit body.

- [ ] **Step 4: Confirm no unintended changes (templates untouched).**

Run: `git status --porcelain penpine/cli/templates`
Expected: empty (the `exclude:` kept template files — e.g. `dot-gitignore`, `requests/sample.http` — untouched).

- [ ] **Step 5: Commit.**

```bash
git add .pre-commit-config.yaml pyproject.toml
git -c commit.gpgsign=false commit -m "build: add pre-commit config (ruff + hygiene hooks)"
```

---

### Task 5: MIT LICENSE + full package metadata

**Files:**
- Create: `LICENSE`
- Modify: `pyproject.toml` (`[project]` metadata + `[project.urls]`)

**Interfaces:**
- Consumes: `README.md` (wired as `readme`), `penpine/py.typed` (Task 2, verified shipped here).
- Produces: a buildable, metadata-complete distribution.

- [ ] **Step 1: Create `LICENSE` (MIT).**

```
MIT License

Copyright (c) 2026 nquangit

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

- [ ] **Step 2: Replace the `[project]` table's metadata in `pyproject.toml`.**

The `[project]` table becomes (keep `name`/`version`; update `description`; add the rest):
```toml
[project]
name = "penpine"
version = "0.0.1"
description = "A layered Python pentesting framework"
readme = "README.md"
license = { text = "MIT" }
authors = [{ name = "nquangit", email = "huynhngocq5@gmail.com" }]
keywords = ["pentesting", "security", "http", "fuzzing", "web-security"]
requires-python = ">=3.11"
dependencies = ["jsonpath-ng>=1.6"]
classifiers = [
    "Development Status :: 3 - Alpha",
    "Intended Audience :: Developers",
    "License :: OSI Approved :: MIT License",
    "Programming Language :: Python :: 3.11",
    "Programming Language :: Python :: 3.12",
    "Topic :: Security",
]
```
Add after the `[project.scripts]` table:
```toml
[project.urls]
Homepage = "https://git.nquangit.io.vn/nquangit/pypenpine"
Repository = "https://git.nquangit.io.vn/nquangit/pypenpine"
```

- [ ] **Step 3: Build and validate the distribution (includes `py.typed`).**

Run: `pip install build twine >/dev/null && python -m build && twine check dist/*`
Expected: builds `penpine-0.0.1.tar.gz` and `penpine-0.0.1-py3-none-any.whl`; `twine check` prints `PASSED` for both.
Run: `python -m zipfile -l dist/penpine-0.0.1-py3-none-any.whl | grep -E "py.typed|templates/project/main.py.tmpl"`
Expected: both `penpine/py.typed` and the template file are listed (confirms `py.typed` and templates ship).
**Fallback:** if `python -m build` *errors* (not just warns) on `license = { text = "MIT" }` under a very new setuptools (>=77, PEP 639), change that line to `license = "MIT"` and remove the `License :: OSI Approved :: MIT License` classifier, then re-run. A deprecation *warning* is acceptable — do not change it for a mere warning.

- [ ] **Step 4: Clean build artifacts (they are gitignored but remove to be tidy).**

Run: `rm -rf dist build *.egg-info/PKG-INFO 2>/dev/null; git status --porcelain | grep -E "^\?\? (dist|build)/" && echo "WARN untracked build dirs" || echo "clean"`
Expected: `clean` (or the dirs are gitignored — confirm they are not staged).

- [ ] **Step 5: Commit.**

```bash
git add LICENSE pyproject.toml
git -c commit.gpgsign=false commit -m "build: add MIT LICENSE and complete package metadata"
```

---

### Task 6: Gitea Actions CI workflow

**Files:**
- Create: `.gitea/workflows/ci.yml`

**Interfaces:**
- Consumes: all tool configs (ruff/mypy/coverage) and the `dev` extra from Tasks 1–5.
- Produces: a CI pipeline running the gates on push + PR.

- [ ] **Step 1: Create `.gitea/workflows/ci.yml`.**

```yaml
name: ci
on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: ["3.11", "3.12"]
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python-version }}
      - name: Install
        run: pip install -e ".[dev]"
      - name: Lint
        run: ruff check .
      - name: Format check
        run: ruff format --check .
      - name: Type check (advisory)
        run: mypy penpine
        continue-on-error: true
      - name: Tests + coverage
        run: pytest --cov=penpine --cov-report=term-missing
```

- [ ] **Step 2: Validate the workflow YAML.**

Run: `pre-commit run check-yaml --files .gitea/workflows/ci.yml`
Expected: the `check-yaml` hook passes (`Passed`). (pre-commit + PyYAML are installed from Task 4.)
Fallback if hook repos are unfetchable: `python -c "import yaml; yaml.safe_load(open('.gitea/workflows/ci.yml')); print('YAML_OK')"` → expects `YAML_OK` (PyYAML ships with pre-commit).

- [ ] **Step 3: Sanity-check the gate commands locally (they must be the same ones CI runs).**

Run: `ruff check . && ruff format --check . && python -m pytest --cov=penpine --cov-report=term-missing -q`
Expected: lint clean, format clean, `327 passed, 1 skipped` + coverage table. (mypy is advisory and intentionally not part of this gate check.)

- [ ] **Step 4: Commit.**

```bash
git add .gitea/workflows/ci.yml
git -c commit.gpgsign=false commit -m "ci: add Gitea Actions workflow (lint/format gate, mypy advisory, tests+coverage on 3.11/3.12)"
```

---

### Task 7: README "Development" section

**Files:**
- Modify: `README.md` (insert a `## Development` section before `## Status & roadmap`)

**Interfaces:**
- Consumes: the dev workflow established in Tasks 1–6.

- [ ] **Step 1: Insert the Development section.**

Immediately BEFORE the existing `## Status & roadmap` heading in `README.md`, insert:
```markdown
## Development

Install the dev toolchain and the pre-commit hooks:

    pip install -e ".[dev]"
    pre-commit install

Run the same checks CI runs:

    ruff check . && ruff format --check .   # lint + format (gating)
    mypy penpine                            # type check (advisory)
    pytest --cov=penpine                    # tests + coverage

```

- [ ] **Step 2: Verify formatting hooks leave the README clean.**

Run: `pre-commit run --files README.md || true; git diff --stat README.md`
Expected: the only change is the added Development section (a trailing-whitespace/EOF fix is fine; no other content altered). If pre-commit can't fetch hooks (offline), skip this and just confirm the section is present: `grep -n "## Development" README.md`.

- [ ] **Step 3: Commit.**

```bash
git add README.md
git -c commit.gpgsign=false commit -m "docs: add Development section to README"
```

---

### Final verification (after all tasks)

- [ ] Run the full gate exactly as CI will: `ruff check . && ruff format --check . && python -m pytest --cov=penpine --cov-report=term-missing -q` → lint/format clean, `327 passed, 1 skipped`, coverage table printed.
- [ ] `mypy` runs to completion (advisory).
- [ ] `python -m build && twine check dist/*` → both PASSED; `py.typed` in the wheel; then `rm -rf dist build`.
- [ ] Branch commit graph is a clean sequence of unsigned (`%G?` = `N`) commits.

---

## Self-Review

**Spec coverage:**
- §4 Ruff (config, line-length 100, ruleset, template exclude, normalization commit) → Task 1. ✓
- §5 mypy advisory + `py.typed` + package-data → Task 2. ✓ (mypy CI advisory wiring → Task 6.)
- §6 coverage report-only → Task 3. ✓
- §7 pre-commit (ruff + hygiene, template exclude, not mypy) → Task 4. ✓
- §8 Gitea Actions (matrix 3.11/3.12, gate vs advisory steps, YAML fallback) → Task 6. ✓
- §9 MIT LICENSE + metadata + urls + dev extras + py.typed package-data → Tasks 1–5 (dev extras accrete across tasks; LICENSE/metadata in Task 5; package-data in Task 2). ✓
- §10 README Development section → Task 7. ✓
- §11 verification (ruff clean, format clean, 327 pass, mypy runs, build+twine, py.typed shipped, YAML parses, pre-commit passes) → distributed across task verify steps + Final verification. ✓
- §12 sequencing (ruff+normalize → mypy/py.typed → coverage → pre-commit → metadata/LICENSE → CI → README) → Tasks 1–7 in order. ✓

**Placeholder scan:** No TBD/TODO. The only intentional fill-in is the mypy baseline error count `<N>` in Task 2's commit message, which is a value the implementer measures at that step (not a deferred decision). ✓

**Type/name consistency:** `dev` extra grows monotonically and the final membership (Task 4 Step 2) lists all six tools; `[tool.setuptools.package-data]` has both the `penpine` (Task 2) and `penpine.cli` (pre-existing) entries; ruff ruleset string is identical in the Global Constraints and Task 1; the gate command (`ruff check . && ruff format --check . && pytest --cov=penpine`) is identical in Task 6 Step 3 and Final verification. ✓
