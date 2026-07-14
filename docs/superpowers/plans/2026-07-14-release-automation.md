# Release Automation (Gitea) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publish penpine to the Gitea PyPI registry and create a Gitea release on every `v*` tag push, plus a `scripts/bump_version.py` to bump the version and tag, and a "bump on every main merge" policy.

**Architecture:** A `.gitea/workflows/release.yml` triggered on tag push (build → twine-publish → Gitea release with assets). A standalone `scripts/bump_version.py` whose pure version/rewrite logic is unit-tested and whose `main()` does git guards + commit/tag/push. Policy documented in CLAUDE.md; project bumped to `0.1.0` / Beta.

**Tech Stack:** Python 3.11+ stdlib (`argparse`/`re`/`subprocess`), `build` + `twine` (in the workflow only), Gitea Actions (GitHub-Actions-compatible), curl + jq for the Gitea API.

## Global Constraints

- Host/repo: `git.nquangit.io.vn`, `nquangit/pypenpine`. Gitea PyPI registry is per-owner: `<server>/api/packages/nquangit/pypi`.
- Auth: a repo/org secret `PACKAGE_TOKEN` (Gitea PAT, `write:package` + `write:repository`). The workflow references it; creating it + enabling Actions is the user's one-time setup.
- SemVer, tags `vX.Y.Z`. Tag must match `pyproject.toml` `version` (workflow guards this).
- `scripts/` IS linted by `ruff check .` (only `penpine/cli/templates` is excluded) — the script must be ruff-clean. mypy checks only `penpine/`, so the script is not mypy-gated.
- Commits/tags created by the script disable GPG signing (`-c commit.gpgsign=false -c tag.gpgSign=false`), matching the project's no-GPG preference.
- No CI auto-tagging; no pre-release/build-metadata versions (plain `X.Y.Z`); Gitea registry only (not public PyPI).
- Commits use `--no-gpg-sign`.

## Key current-code facts (use exactly)

- `pyproject.toml:3` → `version = "0.0.1"`; `pyproject.toml:12` → `    "Development Status :: 3 - Alpha",`. `[tool.ruff]` `extend-exclude = ["penpine/cli/templates"]` (line 37); `[tool.mypy] files = ["penpine"]`. Version appears nowhere else in the repo.
- No `scripts/` directory yet. Only `.gitea/workflows/ci.yml` exists; it uses `actions/checkout@v4` / `actions/setup-python@v5` (so those actions work on this Gitea).

---

### Task 1: `scripts/bump_version.py` + unit tests

**Files:**
- Create: `scripts/bump_version.py`
- Test: `tests/test_bump_version.py`

**Interfaces:**
- Produces (pure, unit-tested): `parse_version(s) -> tuple[int,int,int]` (rejects non-`X.Y.Z`); `next_version(current: str, spec: str) -> str` (spec ∈ {`patch`,`minor`,`major`} or explicit `X.Y.Z`; explicit must be strictly greater); `read_version(pyproject_text) -> str`; `rewrite_version(pyproject_text, new) -> str` (rewrites exactly the one `version = "X.Y.Z"` line). Plus `main(argv=None) -> int` doing git guards + commit/tag/push, with `--dry-run` and `--no-push`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_bump_version.py`:

```python
import importlib.util
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location(
    "bump_version", Path(__file__).resolve().parents[1] / "scripts" / "bump_version.py"
)
bump_version = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bump_version)


def test_next_version_levels():
    assert bump_version.next_version("0.0.1", "patch") == "0.0.2"
    assert bump_version.next_version("0.0.1", "minor") == "0.1.0"
    assert bump_version.next_version("0.0.1", "major") == "1.0.0"
    assert bump_version.next_version("1.2.3", "minor") == "1.3.0"
    assert bump_version.next_version("1.2.3", "major") == "2.0.0"


def test_next_version_explicit_must_increase():
    assert bump_version.next_version("0.1.0", "0.2.0") == "0.2.0"
    with pytest.raises(ValueError):
        bump_version.next_version("0.2.0", "0.1.0")
    with pytest.raises(ValueError):
        bump_version.next_version("0.2.0", "0.2.0")  # equal is not an increase


def test_parse_version_rejects_non_xyz():
    with pytest.raises(ValueError):
        bump_version.parse_version("1.2")
    with pytest.raises(ValueError):
        bump_version.parse_version("1.2.3b1")


def test_read_and_rewrite_version_touches_only_version_line():
    text = '[project]\nname = "penpine"\nversion = "0.0.1"\ndescription = "x"\n'
    assert bump_version.read_version(text) == "0.0.1"
    out = bump_version.rewrite_version(text, "0.1.0")
    assert 'version = "0.1.0"' in out
    assert bump_version.read_version(out) == "0.1.0"
    # nothing else changed
    assert out.replace('"0.1.0"', '"0.0.1"') == text


def test_read_version_missing_raises():
    with pytest.raises(ValueError):
        bump_version.read_version('[project]\nname = "penpine"\n')
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_bump_version.py -v`
Expected: FAIL — `scripts/bump_version.py` does not exist (module load error).

- [ ] **Step 3: Implement the script**

Create `scripts/bump_version.py`:

```python
#!/usr/bin/env python3
"""Bump penpine's version, commit, tag vX.Y.Z, and push (triggers release.yml).

Usage:
    python scripts/bump_version.py <patch|minor|major | X.Y.Z> [--dry-run] [--no-push]

Run this AFTER merging a change to main. Guards: must be on `main`, clean working
tree, and the target tag must not already exist locally. The tag push triggers
.gitea/workflows/release.yml (build -> publish to the Gitea PyPI registry ->
create a release).
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_PYPROJECT = _ROOT / "pyproject.toml"
_VERSION_RE = re.compile(r'(?m)^(version\s*=\s*")(\d+\.\d+\.\d+)(")\s*$')
_NO_GPG = ["-c", "commit.gpgsign=false", "-c", "tag.gpgSign=false"]


def parse_version(s: str) -> tuple[int, int, int]:
    m = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", s)
    if not m:
        raise ValueError(f"not a X.Y.Z version: {s!r}")
    return int(m[1]), int(m[2]), int(m[3])


def next_version(current: str, spec: str) -> str:
    major, minor, patch = parse_version(current)
    if spec == "major":
        return f"{major + 1}.0.0"
    if spec == "minor":
        return f"{major}.{minor + 1}.0"
    if spec == "patch":
        return f"{major}.{minor}.{patch + 1}"
    if parse_version(spec) <= (major, minor, patch):
        raise ValueError(f"explicit version {spec} is not greater than current {current}")
    return spec


def read_version(text: str) -> str:
    m = _VERSION_RE.search(text)
    if not m:
        raise ValueError('no `version = "X.Y.Z"` line found in pyproject.toml')
    return m.group(2)


def rewrite_version(text: str, new: str) -> str:
    new_text, n = _VERSION_RE.subn(rf"\g<1>{new}\g<3>", text, count=1)
    if n != 1:
        raise ValueError("failed to rewrite the version line")
    return new_text


def _git(*args: str, capture: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=_ROOT, check=True, text=True, capture_output=capture
    )


def _guard_clean_main() -> None:
    branch = _git("rev-parse", "--abbrev-ref", "HEAD", capture=True).stdout.strip()
    if branch != "main":
        raise SystemExit(f"refusing to release from branch {branch!r} (switch to main first)")
    if _git("status", "--porcelain", capture=True).stdout.strip():
        raise SystemExit("working tree is not clean; commit or stash first")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="bump version, tag, and push a release")
    parser.add_argument("spec", help="patch | minor | major | X.Y.Z")
    parser.add_argument("--dry-run", action="store_true", help="print actions, change nothing")
    parser.add_argument("--no-push", action="store_true", help="commit + tag locally, do not push")
    args = parser.parse_args(argv)

    text = _PYPROJECT.read_text()
    current = read_version(text)
    new = next_version(current, args.spec)
    tag = f"v{new}"

    if _git("tag", "--list", tag, capture=True).stdout.strip():
        raise SystemExit(f"tag {tag} already exists")

    print(f"bump {current} -> {new}  (tag {tag})")
    if args.dry_run:
        print("dry-run: no changes made")
        return 0

    _guard_clean_main()
    _PYPROJECT.write_text(rewrite_version(text, new))
    _git(*_NO_GPG, "commit", "-m", f"chore(release): {tag}", "--", "pyproject.toml")
    _git(*_NO_GPG, "tag", "-a", tag, "-m", tag)

    if args.no_push:
        print(f"created commit + tag {tag} locally (--no-push).")
        print("push when ready:  git push origin main --follow-tags")
        return 0

    _git("push", "origin", "main")
    _git("push", "origin", tag)
    print(f"pushed {tag}; the release workflow will build, publish, and release it.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run the tests**

Run: `pytest tests/test_bump_version.py -v`
Expected: PASS (5 passed).

- [ ] **Step 5: Smoke the dry-run (no changes)**

Run: `python scripts/bump_version.py minor --dry-run`
Expected: prints `bump 0.0.1 -> 0.1.0  (tag v0.1.0)` then `dry-run: no changes made`; `git status --porcelain` shows no changes.

- [ ] **Step 6: Lint**

Run: `ruff check scripts/bump_version.py tests/test_bump_version.py && ruff format --check scripts/bump_version.py tests/test_bump_version.py`
Expected: clean (run `ruff format` on them if needed).

- [ ] **Step 7: Commit**

```bash
git add scripts/bump_version.py tests/test_bump_version.py
git commit --no-gpg-sign -m "feat(release): add scripts/bump_version.py (bump + tag + push)"
```

---

### Task 2: `.gitea/workflows/release.yml`

**Files:**
- Create: `.gitea/workflows/release.yml`

**Interfaces:** none (CI config). Consumes the `PACKAGE_TOKEN` secret and the tag pushed by Task 1's script.

- [ ] **Step 1: Write the workflow**

Create `.gitea/workflows/release.yml`:

```yaml
name: release
# Publish to the Gitea PyPI registry and create a release when a version tag is
# pushed. Requires a repo/org secret PACKAGE_TOKEN (Gitea PAT with write:package
# and write:repository). Cut a release with: python scripts/bump_version.py <level>
on:
  push:
    tags:
      - "v*"

jobs:
  publish:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - name: Install build tooling
        run: pip install build twine

      - name: Verify tag matches pyproject version
        run: |
          set -euo pipefail
          VERSION=$(python -c "import re,pathlib;print(re.search(r'version\s*=\s*\"([^\"]+)\"', pathlib.Path('pyproject.toml').read_text()).group(1))")
          echo "pyproject version: $VERSION | tag: ${GITHUB_REF_NAME}"
          if [ "${GITHUB_REF_NAME}" != "v${VERSION}" ]; then
            echo "::error::tag ${GITHUB_REF_NAME} does not match pyproject version v${VERSION}"
            exit 1
          fi

      - name: Build sdist + wheel
        run: python -m build

      - name: Publish to Gitea PyPI registry
        env:
          TWINE_USERNAME: nquangit
          TWINE_PASSWORD: ${{ secrets.PACKAGE_TOKEN }}
        run: |
          twine upload --non-interactive \
            --repository-url "${GITHUB_SERVER_URL}/api/packages/nquangit/pypi" \
            dist/*

      - name: Create Gitea release with assets
        env:
          TOKEN: ${{ secrets.PACKAGE_TOKEN }}
        run: |
          set -euo pipefail
          TAG="${GITHUB_REF_NAME}"
          API="${GITHUB_SERVER_URL}/api/v1/repos/${GITHUB_REPOSITORY}"
          PREV=$(git describe --tags --abbrev=0 "${TAG}^" 2>/dev/null || true)
          if [ -n "${PREV}" ]; then
            BODY=$(git log --pretty='- %s' "${PREV}..${TAG}")
          else
            BODY="Initial release."
          fi
          PAYLOAD=$(jq -n --arg tag "$TAG" --arg body "$BODY" \
            '{tag_name:$tag, name:$tag, body:$body, draft:false, prerelease:false}')
          # Create the release; if it already exists (re-run), look it up by tag.
          RID=$(curl -sS -X POST "$API/releases" \
            -H "Authorization: token $TOKEN" -H "Content-Type: application/json" \
            -d "$PAYLOAD" | jq -r '.id // empty')
          if [ -z "$RID" ]; then
            RID=$(curl -sS "$API/releases/tags/$TAG" \
              -H "Authorization: token $TOKEN" | jq -r '.id // empty')
          fi
          if [ -z "$RID" ]; then
            echo "::error::could not create or find release for $TAG"; exit 1
          fi
          for f in dist/*; do
            echo "uploading asset: $(basename "$f")"
            curl -sSf -X POST "$API/releases/$RID/assets?name=$(basename "$f")" \
              -H "Authorization: token $TOKEN" -F "attachment=@$f" >/dev/null
          done
          echo "release $TAG created with $(ls dist | wc -l) assets"
```

- [ ] **Step 2: Validate the YAML**

Run: `python -c "import yaml,sys; yaml.safe_load(open('.gitea/workflows/release.yml')); print('yaml ok')"`
Expected: `yaml ok`. (If PyYAML isn't installed, `pip install pyyaml` first — it's only for this check.)

- [ ] **Step 3: Dry-run the version-guard shell logic locally**

Run (mimics the guard step against the current tree, expecting a MISMATCH since HEAD isn't a tag yet — this proves the guard's comparison works):

```bash
VERSION=$(python -c "import re,pathlib;print(re.search(r'version\s*=\s*\"([^\"]+)\"', pathlib.Path('pyproject.toml').read_text()).group(1))")
echo "version=$VERSION"; [ "v$VERSION" = "v0.0.1" ] && echo "guard-logic-ok"
```
Expected: `version=0.0.1` then `guard-logic-ok` (confirms the version-extraction one-liner works).

- [ ] **Step 4: Smoke `python -m build`**

Run: `pip install build >/dev/null 2>&1; python -m build 2>&1 | tail -5 && ls dist/`
Expected: builds `penpine-0.0.1.tar.gz` + `penpine-0.0.1-py3-none-any.whl` in `dist/` (confirms packaging metadata is valid). Then clean up: `rm -rf dist/ build/ penpine.egg-info/` (do not commit build artifacts; confirm they're git-ignored).

- [ ] **Step 5: Commit**

```bash
git add .gitea/workflows/release.yml
git commit --no-gpg-sign -m "ci(release): publish to Gitea PyPI + create release on tag push"
```

---

### Task 3: Versioning policy (CLAUDE.md) + Beta classifier + regression

**Files:**
- Modify: `CLAUDE.md`, `pyproject.toml`
- Test: whole suite

**Interfaces:** documentation + metadata.

- [ ] **Step 1: Flip the classifier to Beta**

In `pyproject.toml`, change line 12 from `    "Development Status :: 3 - Alpha",` to:

```toml
    "Development Status :: 4 - Beta",
```

(Leave `version = "0.0.1"` unchanged — Task's post-merge step bumps it via the script.)

- [ ] **Step 2: Add the versioning policy to CLAUDE.md**

In `CLAUDE.md`, under the `## Conventions` section, append:

```markdown
- **Versioning & releases.** SemVer; releases are git tags `vX.Y.Z`. **Every merge
  to `main` is followed by a version bump: `python scripts/bump_version.py
  <patch|minor|major>`**, which rewrites `pyproject.toml`, commits, tags, and pushes.
  The tag push triggers `.gitea/workflows/release.yml` (build → publish to the Gitea
  PyPI registry → create a release). Do not hand-edit the version or create tags
  manually. Publishing needs a `PACKAGE_TOKEN` repo secret (Gitea PAT with
  `write:package` + `write:repository`) and Actions enabled on the repo.
```

- [ ] **Step 3: Whole suite + gates**

Run: `pytest -q && ruff check . && ruff format --check . && mypy penpine`
Expected: all pass (the new script test included); ruff clean (scripts/ is linted); mypy `Success`.

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md pyproject.toml
git commit --no-gpg-sign -m "docs: versioning/release policy; mark project Beta"
```

---

## Post-merge: cut the first release (`0.1.0`)

Not a branch task — done on `main` after this plan merges (the controller runs it):

```bash
# on main, after merging the release-automation branch:
python scripts/bump_version.py minor --no-push
# -> pyproject 0.0.1 -> 0.1.0, commit "chore(release): v0.1.0", local tag v0.1.0
```

Nothing is pushed (honoring "before I push into origin"). When the user is ready:
`git push origin main --follow-tags` — the `v0.1.0` tag then fires `release.yml`.

## Notes for the implementer

- **The script's git/guard `main()` is not unit-tested** (it shells out to git/network); only the pure `parse/next/read/rewrite` functions are. Verify `main()` via the `--dry-run` smoke (Task 1 Step 5). Do not add tests that create real commits/tags/pushes.
- **Do not commit build artifacts** (`dist/`, `build/`, `*.egg-info`) — clean them after the build smoke.
- The workflow is not runnable in-sandbox; its correctness rests on the YAML lint, the version-guard dry-run, the build smoke, and inspection against Gitea's API (`/api/packages/<owner>/pypi`, `/api/v1/repos/<owner>/<repo>/releases`).
