# Scaffold: install penpine from the Gitea registry — Design

**Date:** 2026-07-14
**Status:** Approved

## Problem

Scaffolded projects (`penpine new`) install penpine as an **editable install of the
local source** (`requirements.txt` = `-e <auto-detected local path>`, falling back
to bare `penpine`). Now that penpine is published to the Gitea package registry,
generated projects should install the **published package from the registry** via
`--extra-index-url`.

**Decisions (approved):** registry is **public** (anonymous `pip` works); version
is **unpinned** (`penpine`, latest); do a **full clean switch** — remove the
now-obsolete local-editable-install machinery rather than leave it dead/misleading.

## Change

### 1. `requirements.txt.tmpl` (the core change)

```
# penpine is installed from the Gitea package registry (public).
--extra-index-url https://git.nquangit.io.vn/api/packages/nquangit/pypi/simple/
penpine
jsonpath-ng>=1.6
```

`--extra-index-url` *adds* the Gitea registry to the default PyPI index, so penpine
comes from Gitea and its dependency (`jsonpath-ng`) resolves from PyPI. No template
variables remain in this file.

### 2. Remove the obsolete local-install machinery

Everything below exists solely to support the editable-local install being replaced:

- `docs/README.md.tmpl` — the Setup section says penpine is "installed editable from
  `{{ penpine_path }}`". Rewrite to "installed from the Gitea package registry (see
  `requirements.txt`)". Drops the `{{ penpine_path }}` reference.
- `penpine/cli/commands/new.py` — remove the `find_penpine_root()` call and the
  "could not detect a local penpine source …" warning; drop `penpine_path` and
  `penpine_spec` from the render variables. Keep `paths.slugify`.
- `penpine/cli/paths.py` — remove `penpine_spec()` and `find_penpine_root()` (both
  now unused). Keep `slugify()`.
- Tests — `tests/cli/test_paths.py`: drop `test_penpine_spec` and
  `test_find_penpine_root_locates_this_repo` and their imports (keep the slugify
  test). In the scaffold tests (`test_base_templates.py`, `test_generated_main.py`,
  `test_samples_run.py`), drop the now-unused `penpine_spec`/`penpine_path` keys from
  their `VARS` dicts (render ignores extra keys, so this is a cleanliness pass; but
  if any test asserts on penpine_spec/penpine_path rendering, update it).

## Consequences (intended)

- `penpine new <name>` (which creates a venv and `pip install -r requirements.txt`)
  now installs penpine **from the registry** — it needs network and the package
  published. `--no-venv` still skips install. This is the desired behavior; the
  offline editable-local convenience is intentionally gone.
- The opt-in slow e2e test (`tests/cli/test_e2e_venv.py`, gated behind
  `PENPINE_SLOW`) builds a real venv and installs from `requirements.txt`, so it now
  depends on the registry + network. It's opt-in, so normal CI is unaffected; note
  it in that test if it needs a skip when the registry is unreachable.

## Testing

- `render_project` still renders cleanly (no unknown `{{ }}` vars remain — the two
  removed vars are no longer referenced by any template).
- `tests/cli/` suite green: base-templates, generated-main (runs the attack path
  offline), samples-run — all still pass with the trimmed variable set.
- `pytest -q` whole suite green; ruff + mypy clean.
- Manual check: render a project and confirm `requirements.txt` contains the
  `--extra-index-url` line + `penpine`, and the README Setup no longer references a
  local path.

## Non-goals

- No version pinning (unpinned `penpine`).
- No auth handling (registry is public).
- No change to venv creation / `pip_install` mechanics (only what they install).

## Rollout

Small, mostly-deletion change; one plan (or inline execution given the size):
(1) `requirements.txt.tmpl` + README; (2) remove `penpine_spec`/`find_penpine_root`
plumbing from `new.py`/`paths.py`; (3) test cleanup + full regression.
