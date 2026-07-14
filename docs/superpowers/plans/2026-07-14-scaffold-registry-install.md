# Scaffold Registry Install Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `penpine new` projects install penpine from the Gitea package registry (`--extra-index-url`) instead of an editable local install, and remove the now-obsolete local-source-detection machinery.

**Architecture:** One coherent change: rewrite `requirements.txt.tmpl` to use the registry index, fix the README Setup wording, and delete the `penpine_spec`/`find_penpine_root` plumbing (used only by the old editable install) plus its tests.

**Tech Stack:** Python 3.11+, the scaffold's `render_project`, pytest.

## Global Constraints

- Registry is public (anonymous `pip`); version unpinned (`penpine`). Registry index: `https://git.nquangit.io.vn/api/packages/nquangit/pypi/simple/`.
- Templates under `penpine/cli/templates/` are ruff-excluded but must render and (for `.py`) run.
- After the change, NO template references `penpine_spec` or `penpine_path` (so those render vars are removed).
- Whole suite green; ruff + mypy clean. Commits use `--no-gpg-sign`.

## Key current-code facts (use exactly)

- `find_penpine_root` is used only at `penpine/cli/commands/new.py:30`; `penpine_spec` only at `new.py:41` and `requirements.txt.tmpl:2`. No other production usage — both are safe to delete.
- `penpine/cli/paths.py` also defines `slugify` (keep) and imports `re` (keep, used by slugify), `from pathlib import Path` + `import penpine` (used only by the two functions being removed → drop).
- `new.py` keeps `log` (used by venv warnings) and `paths` (used by `paths.slugify`).
- `docs/README.md.tmpl` Setup section (lines ~7-8) references `{{ penpine_path }}`.
- Test `VARS` dicts carrying `penpine_path`/`penpine_spec`: `tests/cli/test_base_templates.py` (also asserts `-e /tmp/pypenpine` in requirements), `tests/cli/test_generated_main.py`, `tests/cli/test_samples_run.py`.

---

### Task 1: Switch the scaffold to registry install + remove local-install plumbing

**Files:**
- Modify: `penpine/cli/templates/project/requirements.txt.tmpl`, `penpine/cli/templates/project/docs/README.md.tmpl`, `penpine/cli/commands/new.py`, `penpine/cli/paths.py`
- Test: `tests/cli/test_base_templates.py`, `tests/cli/test_paths.py`, `tests/cli/test_generated_main.py`, `tests/cli/test_samples_run.py`

**Interfaces:**
- `penpine/cli/paths.py` after: exports `slugify` only (`find_penpine_root`/`penpine_spec` removed).
- `new.py` render variables after: `project_name`, `project_slug`, `date`, `python_version` (no `penpine_path`/`penpine_spec`).

- [ ] **Step 1: Update the base-templates test to expect the registry (RED)**

In `tests/cli/test_base_templates.py`: remove the `"penpine_path"` and `"penpine_spec"` keys from `VARS`, and replace the requirements assertion:

```python
    # requirements install penpine from the Gitea registry
    reqs = (dst / "requirements.txt").read_text()
    assert "--extra-index-url" in reqs
    assert "penpine" in reqs
    assert "-e " not in reqs
```

(Replaces the old `assert "-e /tmp/pypenpine" in (dst / "requirements.txt").read_text()`.)

- [ ] **Step 2: Run it — verify RED**

Run: `pytest tests/cli/test_base_templates.py -v`
Expected: FAIL — with `penpine_spec`/`penpine_path` removed from `VARS`, `render_project` raises `ScaffoldError: unknown template variable {{ penpine_spec }}` (the old templates still reference them).

- [ ] **Step 3: Rewrite `requirements.txt.tmpl`**

Replace `penpine/cli/templates/project/requirements.txt.tmpl` entirely with:

```
# penpine is installed from the Gitea package registry (public).
--extra-index-url https://git.nquangit.io.vn/api/packages/nquangit/pypi/simple/
penpine
jsonpath-ng>=1.6
```

- [ ] **Step 4: Fix the README Setup wording**

In `penpine/cli/templates/project/docs/README.md.tmpl`, replace:

```
A virtualenv was created at `.venv` with penpine installed editable from
`{{ penpine_path }}`. Activate it:
```

with:

```
A virtualenv was created at `.venv` with penpine installed from the Gitea
package registry (see `requirements.txt`). Activate it:
```

- [ ] **Step 5: Remove the plumbing from `new.py`**

In `penpine/cli/commands/new.py`, delete the `find_penpine_root` call + warning and the two render vars. Replace:

```python
    root = paths.find_penpine_root()
    if root is None:
        log.warning(
            "could not detect a local penpine source; requirements.txt will "
            "use a plain 'penpine' spec (needs penpine on an index)"
        )

    variables = {
        "project_name": name,
        "project_slug": paths.slugify(name),
        "penpine_path": str(root) if root else "",
        "penpine_spec": paths.penpine_spec(root),
        "date": date.today().isoformat(),
        "python_version": f"{sys.version_info.major}.{sys.version_info.minor}",
    }
```

with:

```python
    variables = {
        "project_name": name,
        "project_slug": paths.slugify(name),
        "date": date.today().isoformat(),
        "python_version": f"{sys.version_info.major}.{sys.version_info.minor}",
    }
```

- [ ] **Step 6: Remove `find_penpine_root`/`penpine_spec` from `paths.py`**

Replace `penpine/cli/paths.py` entirely with:

```python
"""Project-name slugging for the scaffolder."""

from __future__ import annotations

import re

_NON_IDENT = re.compile(r"[^a-z0-9]+")


def slugify(name: str) -> str:
    """An importable, lowercase slug. Empty/digit-leading cores get a 'p_' prefix."""
    slug = _NON_IDENT.sub("_", name.strip().lower()).strip("_")
    if not slug or slug[0].isdigit():
        slug = "p_" + slug
    return slug
```

- [ ] **Step 7: Trim `test_paths.py`**

Replace `tests/cli/test_paths.py` entirely with:

```python
from penpine.cli.paths import slugify


def test_slugify_normalizes_names():
    assert slugify("My Engagement") == "my_engagement"
    assert slugify("a-b.c") == "a_b_c"
    assert slugify("123app") == "p_123app"
    assert slugify("  ok  ") == "ok"
    assert slugify("--!!--") == "p_"  # empty core -> prefixed
```

- [ ] **Step 8: Drop the dead vars from the other scaffold-test VARS**

In `tests/cli/test_generated_main.py` and `tests/cli/test_samples_run.py`, remove the `"penpine_path"` and `"penpine_spec"` entries from each `VARS` dict (they're no longer referenced by any template; render ignores extras, but keep the tests honest).

- [ ] **Step 9: Run the cli suite — verify GREEN**

Run: `pytest tests/cli -v`
Expected: PASS (base-templates now asserts the registry line; paths tests trimmed; generated-main + samples-run still render and run offline).

- [ ] **Step 10: Whole suite + gates**

Run: `pytest -q && ruff check . && ruff format --check . && mypy penpine`
Expected: all pass; ruff clean; mypy `Success` (no unused-import errors in `paths.py`).

- [ ] **Step 11: Manual render check**

Run:
```bash
python - <<'PY'
import tempfile, pathlib
from datetime import date
from penpine.cli.scaffold import render_project
d = tempfile.mkdtemp()
render_project(d, {"project_name":"x","project_slug":"x","date":date.today().isoformat(),"python_version":"3.12"})
req = (pathlib.Path(d)/"requirements.txt").read_text()
readme = (pathlib.Path(d)/"docs"/"README.md").read_text()
print(req)
assert "--extra-index-url https://git.nquangit.io.vn/api/packages/nquangit/pypi/simple/" in req
assert "penpine" in req and "-e " not in req
assert "penpine_path" not in readme and "editable from" not in readme
print("RENDER_OK")
PY
```
Expected: prints the registry requirements + `RENDER_OK` (confirms no leftover `{{ }}` vars and the README wording changed).

- [ ] **Step 12: Commit**

```bash
git add penpine/cli/templates/project/requirements.txt.tmpl penpine/cli/templates/project/docs/README.md.tmpl penpine/cli/commands/new.py penpine/cli/paths.py tests/cli/test_base_templates.py tests/cli/test_paths.py tests/cli/test_generated_main.py tests/cli/test_samples_run.py
git commit --no-gpg-sign -m "feat(cli): install scaffolded projects from the Gitea registry (--extra-index-url)"
```

---

## Notes for the implementer

- Render `VARS` in the scaffold tests pass EXTRA keys harmlessly (render only substitutes referenced `{{ }}`), so removing `penpine_path`/`penpine_spec` is a cleanliness pass — it won't fix or break rendering on its own. The real gate is that no template still references them (which would raise `ScaffoldError` at render).
- After removing the two functions from `paths.py`, confirm `import penpine` and `from pathlib import Path` are gone (they were only used there) so ruff doesn't flag unused imports.
- The opt-in slow e2e test (`tests/cli/test_e2e_venv.py`, `PENPINE_SLOW`-gated) now installs from the registry — out of scope here; leave it, but know it needs network + the published package to pass.
