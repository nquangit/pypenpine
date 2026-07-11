# Penpine — Project Infrastructure (Tier 1 + Tier 2) (Design Spec)

**Date:** 2026-07-11
**Status:** Approved for implementation planning
**Scope:** Development-workflow tooling (lint/format, type-checking, coverage, pre-commit, CI) plus packaging/metadata hygiene. No library feature work; the only change to existing source is a one-time auto-format normalization.

---

## 1. Context

The library (L0–L4d + CLI scaffolder) is complete: ~3,900 LOC, 327 tests (1 opt-in slow), clean layering. But the workflow scaffolding around it is nearly absent — `pyproject.toml` declares only `pytest`/`pytest-asyncio`, there is no CI, no linter/formatter, no type-check gate, no coverage, no `py.typed` marker, and the package metadata is stale (`description` still says "L0 HTTP message core"). This spec adds that infrastructure so the existing quality is protected and every future feature rides on green gates.

Facts established during brainstorming:
- Remote is self-hosted at `git.nquangit.io.vn` (Gitea/Forgejo). **CI target: Gitea/Forgejo Actions** (GitHub-Actions-compatible YAML under `.gitea/workflows/`).
- Local interpreter is Python 3.12.11 (pyenv); `requires-python = ">=3.11"`.
- `ruff`/`mypy` are not currently installed.
- Line lengths: max 107, only **2 lines > 100 chars**, 36 lines > 88 → `line-length = 100` minimizes format churn.
- All modules compile.

**Decisions (this round):**
- **Gating is pragmatic:** ruff (lint + format) and pytest **fail** the build; type-checking is **advisory** (runs, never blocks) on day one.
- **Type checker: mypy**, advisory in CI (pure-Python, pyproject-native). Pyright continues in the IDE; it is not run in CI.
- **Coverage: report-only**, no enforced floor initially.
- **License: MIT**, with full package metadata.
- **pre-commit** runs ruff + hygiene hooks, **not** mypy.

## 2. Goals & Non-Goals

**Goals**
- Ruff lint + format configured, the tree normalized once, and both gating CI + pre-commit.
- mypy configured and running in CI as an advisory (non-blocking) step; `penpine/py.typed` shipped so consumers get types.
- Coverage measured and reported in CI (no floor).
- A `.pre-commit-config.yaml` developers can install.
- A Gitea Actions workflow running lint/format/type/test on push + PR across Python 3.11 and 3.12.
- MIT `LICENSE` + complete, accurate `pyproject` metadata (description, readme, license, authors, urls, keywords, classifiers).
- `dev` extras declaring the full toolchain.
- A short README "Development" section.

**Non-Goals (documented follow-ups)**
- Any library feature/bugfix (timeouts, pooling, report export, `penpine run`, differential attacks) — separate specs.
- Enforced coverage floor or hard type-gate (tighten later once baselines are known).
- Publishing to an index / release automation.
- A task runner (nox/tox/make) — pyproject + pre-commit + CI suffice (YAGNI).
- Pyright in CI (stays IDE-only).

## 3. Deliverables (file-by-file)

```
LICENSE                       # new — MIT
.pre-commit-config.yaml       # new — ruff + hygiene hooks
.gitea/workflows/ci.yml       # new — Gitea Actions pipeline
penpine/py.typed              # new — PEP 561 marker (empty file)
pyproject.toml                # modified — metadata, dev extras, tool configs
README.md                     # modified — add "Development" section
<all penpine/**.py, tests/**.py>  # modified once by `ruff format` + `ruff check --fix`
```

## 4. Ruff configuration

`[tool.ruff]` in `pyproject.toml`:
- `line-length = 100`
- `target-version = "py311"`
- `[tool.ruff.lint] select = ["E", "F", "W", "I", "UP", "B", "C4", "SIM"]`
  (pycodestyle errors/warnings, pyflakes, isort, pyupgrade, bugbear, comprehensions, simplify).
- Per-file ignores as needed for tests and templates — notably the generated project templates under `penpine/cli/templates/` are template sources (some with intentionally unusual content); exclude that directory from ruff: `[tool.ruff] extend-exclude = ["penpine/cli/templates"]`.
- If `ruff check --fix` + `ruff format` surface a small number of unavoidable warnings (e.g. a bugbear rule that would change behavior), silence them narrowly with `# noqa: <CODE>` and record which in the plan — do not broaden the global ignore set.

**Normalization commit:** a single, isolated commit runs `ruff format .` then `ruff check --fix .` and commits the result, so subsequent diffs are logic-only. This commit must not change runtime behavior — verified by the test suite still passing (327).

## 5. mypy configuration (advisory)

`[tool.mypy]`:
- `python_version = "3.11"`
- `packages = ["penpine"]` (checked target; tests not type-gated)
- `ignore_missing_imports = true` (covers `jsonpath_ng`)
- Lenient defaults (no `--strict`); the intent is signal, not a wall.
- Runs in CI with `continue-on-error: true`. The plan records the **baseline error count** from the first run so future tightening has a reference; it is not a gate.

`penpine/py.typed`: an empty marker file, shipped via `[tool.setuptools.package-data]` (`"penpine" = ["py.typed"]`), so `pip`-installed consumers receive inline types (PEP 561).

## 6. Coverage configuration

`[tool.coverage.run] source = ["penpine"]`, `branch = true`; `[tool.coverage.report] show_missing = true`, `skip_covered = false`. CI runs `pytest --cov=penpine --cov-report=term-missing`. No `--cov-fail-under` initially.

## 7. pre-commit

`.pre-commit-config.yaml`:
- `pre-commit-hooks`: `trailing-whitespace`, `end-of-file-fixer`, `check-yaml`, `check-toml`, `check-merge-conflict`, `check-added-large-files`.
- `ruff-pre-commit`: `ruff` (lint, with `--fix`) and `ruff-format`.
- Pinned hook revisions. Excludes mirror ruff's `penpine/cli/templates` exclusion where relevant (hygiene hooks may still run on templates; ensure they don't corrupt `dot-gitignore`/`sample.http` — configure `end-of-file-fixer`/`trailing-whitespace` to leave `penpine/cli/templates/` untouched via `exclude:`).

## 8. Gitea Actions workflow

`.gitea/workflows/ci.yml`:
- Name `ci`; triggers `on: [push, pull_request]`.
- One job `test` with `strategy.matrix.python-version: ["3.11", "3.12"]`, `runs-on: ubuntu-latest`.
- Steps:
  1. `actions/checkout@v4`
  2. `actions/setup-python@v5` with the matrix version
  3. `pip install -e ".[dev]"`
  4. `ruff check .` — **gate**
  5. `ruff format --check .` — **gate**
  6. `mypy penpine` — **advisory** (`continue-on-error: true`)
  7. `pytest --cov=penpine --cov-report=term-missing` — **gate**
- The opt-in `slow` venv test remains skipped (no `PENPINE_SLOW`), so CI does not build a real venv.

**Compatibility note:** Gitea Actions consumes GitHub-Actions-compatible YAML and the `actions/*` marketplace actions; if the instance's runner lacks network access to `github.com` for action resolution, the fallback is to replace `setup-python` with a `python:3.11`/`python:3.12` container image and a plain `pip` step. The plan should implement the `actions/*` form (the common case) and note this fallback.

## 9. Packaging / metadata

`LICENSE`: standard MIT text, copyright `2026 nquangit`.

`[project]` in `pyproject.toml`:
- `description = "A layered Python pentesting framework"`
- `readme = "README.md"`
- `license = { text = "MIT" }`
- `authors = [{ name = "nquangit", email = "huynhngocq5@gmail.com" }]`
- `keywords = ["pentesting", "security", "http", "fuzzing", "web-security"]`
- `classifiers`: Development Status :: 3 - Alpha; Intended Audience :: Developers; License :: OSI Approved :: MIT License; Programming Language :: Python :: 3.11 and :: 3.12; Topic :: Security.
- `[project.urls]`: `Homepage`/`Repository` = `https://git.nquangit.io.vn/nquangit/pypenpine`.
- `[project.optional-dependencies] dev = ["pytest>=8.0", "pytest-asyncio>=0.23", "ruff>=0.6", "mypy>=1.11", "pytest-cov>=5.0", "pre-commit>=3.7"]`.

`[tool.setuptools.package-data]` gains `"penpine" = ["py.typed"]` (keeping the existing `"penpine.cli"` templates entry).

## 10. README "Development" section

Append a concise section documenting:
```
pip install -e ".[dev]"
pre-commit install
ruff check . && ruff format --check .   # lint + format
mypy penpine                            # types (advisory)
pytest --cov=penpine                    # tests + coverage
```

## 11. Testing / Verification Strategy

This is infrastructure; the gates themselves are the deliverable. Verification (also the CI contract):
- `ruff check .` exits clean.
- `ruff format --check .` exits clean.
- `pytest` → **327 passed, 1 skipped** (unchanged; the format normalization introduced no behavior change).
- `mypy penpine` runs to completion (advisory); baseline issue count recorded in the plan.
- `python -m build` produces sdist + wheel; `twine check dist/*` passes; the wheel contains `penpine/py.typed`.
- `.gitea/workflows/ci.yml` and `.pre-commit-config.yaml` parse as valid YAML.
- `pre-commit run --all-files` passes (after normalization).

## 12. Sequencing note for the plan

Order matters to keep diffs clean:
1. Add ruff config + dev deps, then the isolated `ruff format`/`--fix` normalization commit (touches many files, zero logic change).
2. mypy config + `py.typed` + package-data.
3. Coverage config.
4. pre-commit config.
5. Metadata + LICENSE.
6. Gitea Actions workflow.
7. README Development section.
Each step is independently committable and verifiable.

## 13. Dependencies

- New dev dependencies only: `ruff`, `mypy`, `pytest-cov`, `pre-commit` (added to the `dev` extra). No new runtime dependencies. Python 3.11+.

## 14. Forward Hooks

- Tightening later is additive: add `--cov-fail-under=<N>`, flip mypy to a gate (drop `continue-on-error`), or broaden the ruff ruleset — each a one-line change once baselines are comfortable.
- The green CI + `py.typed` + metadata are prerequisites for the eventual index publish (out of scope here).
