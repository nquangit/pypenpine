# Release Automation (Gitea) — Design

**Date:** 2026-07-14
**Status:** Approved
**Repo/host:** `nquangit/pypenpine` on `git.nquangit.io.vn` (Gitea).

## Problem & goals

The project has no release tooling. We want:

1. A **Gitea Actions workflow** that, on a version tag push, **publishes the package
   to the Gitea PyPI registry** and **creates a Gitea release** with the built
   artifacts.
2. A **script** to bump the version and push a tag (which triggers #1).
3. A **policy**: every merge to `main` is followed by a version bump + tag.
4. Bump the project from `0.0.1` (Alpha) to **`0.1.0` (Beta)** as the first release.

**Decisions locked (brainstorm):** version → `0.1.0`, classifier → `4 - Beta`;
tag mechanism → **manual `scripts/bump_version.py` + documented policy** (no CI
auto-tagging); the first release goes through the script (`0.0.1 --minor--> 0.1.0`).

## Current state

- `pyproject.toml`: `version = "0.0.1"` (static), setuptools build-backend,
  classifier `Development Status :: 3 - Alpha`. Version appears nowhere else.
- `origin` = `https://git.nquangit.io.vn/nquangit/pypenpine.git`. No tags yet.
- Only `.gitea/workflows/ci.yml` exists (lint/format gating, mypy advisory, tests).

## Component 1 — Release workflow (`.gitea/workflows/release.yml`)

**Trigger:** `on: push: tags: ["v*"]`.

**Job (ubuntu-latest):**
1. `actions/checkout` (with `fetch-depth: 0` so changelog can see history/tags).
2. `actions/setup-python` (3.12); `pip install build twine`.
3. **Version↔tag guard:** read `version` from `pyproject.toml`; assert the pushed
   tag equals `v<version>`. Fail loudly on mismatch (a tag must not publish a
   different version).
4. `python -m build` → `dist/*.whl` + `dist/*.tar.gz`.
5. **Publish to the Gitea PyPI registry:**
   `twine upload --repository-url ${{ github.server_url }}/api/packages/nquangit/pypi
   -u nquangit -p ${{ secrets.PACKAGE_TOKEN }} --non-interactive dist/*`.
6. **Create the Gitea release** via the API
   (`POST ${{ github.server_url }}/api/v1/repos/${{ github.repository }}/releases`,
   `Authorization: token ${{ secrets.PACKAGE_TOKEN }}`) with `tag_name` = the tag,
   `name` = the tag, `body` = an auto changelog (`git log <prev-tag>..<tag>`
   one-line; "initial release" when there is no previous tag), `draft:false`,
   `prerelease:false`. Then **upload each `dist/*` file as a release asset**
   (`POST /releases/{id}/assets?name=<file>`).

**Auth / prerequisites (documented, user-provided):** the repo must have Actions
enabled and a secret **`PACKAGE_TOKEN`** = a Gitea PAT with `write:package` +
`write:repository` scopes. Host/owner come from `github.server_url` /
`github.repository` context vars where possible; the PyPI registry path needs the
owner (`nquangit`) explicitly (Gitea package registry is per-owner).

**Idempotency / failure:** if the release already exists (re-run), the API returns
409 — the step tolerates that and proceeds to (or skips) asset upload. A failed
publish leaves the tag in place; re-running the workflow (or re-pushing) retries.

## Component 2 — Bump script (`scripts/bump_version.py`)

CLI: `python scripts/bump_version.py <patch|minor|major | X.Y.Z> [--dry-run] [--no-push]`.

**Behavior:**
1. **Guards:** current branch is `main`; working tree clean; resolves the current
   version from `pyproject.toml`.
2. Compute the new version: bump the given semver component, or use an explicit
   `X.Y.Z`. Reject a non-increasing explicit version. (Pre-release/build suffixes
   are out of scope — plain `X.Y.Z` only.)
3. Guard: tag `v<new>` must not already exist (local or `origin`).
4. Rewrite the `version = "..."` line in `pyproject.toml`.
5. `git commit -m "chore(release): v<new>"` (pyproject only), annotated tag
   `git tag -a v<new> -m "v<new>"`, then (unless `--no-push`) `git push origin main`
   + `git push origin v<new>`. **Signing disabled** (`-c commit.gpgsign=false -c
   tag.gpgSign=false`) to match the project's no-GPG preference.
6. `--dry-run` prints every action (new version, commit, tag, push) and changes
   nothing. `--no-push` does the local commit + tag but skips the push (for
   reviewing before publishing, e.g. the very first release).

**Design:** a single focused module. The version parse/increment and the pyproject
rewrite are pure functions (unit-tested); the git/guards are a thin `main()`.
Structure so the pure logic is testable without touching git or the network.

## Component 3 — Versioning policy (CLAUDE.md) + classifier

Add to CLAUDE.md **Conventions**:

> **Versioning & releases.** SemVer; releases are git tags `vX.Y.Z`. **Every merge
> to `main` is followed by a version bump via `python scripts/bump_version.py
> <patch|minor|major>`**, which commits the bump, tags it, and pushes — the tag
> push triggers `.gitea/workflows/release.yml` (build → publish to the Gitea PyPI
> registry → create a release). Do not hand-edit `pyproject.toml`'s version or
> create tags manually. Publishing needs a `PACKAGE_TOKEN` repo secret (Gitea PAT,
> `write:package` + `write:repository`).

`pyproject.toml`: `Development Status :: 3 - Alpha` → `Development Status :: 4 - Beta`.

## Component 4 — The first release (`0.1.0`)

Sequence (after the setup below is merged to `main`):

1. The setup work (workflow, script + test, CLAUDE policy, classifier flip) lands on
   `main` with `version` still `0.0.1`.
2. Run `python scripts/bump_version.py minor --no-push` → rewrites to `0.1.0`,
   commits `chore(release): v0.1.0`, tags `v0.1.0` **locally** (no push, honoring
   "before I push into origin"). Everything — the session's `main` commits and the
   `v0.1.0` tag — is then ready for the user to push when they choose
   (`git push origin main --follow-tags`). The tag push triggers the release
   workflow on Gitea.

The first release thus demonstrates the exact flow every future release uses (just
with `--no-push`, since the user is doing the origin push themselves this time).

## Testing

- **Bump script (unit, no git/network):** version parsing; `patch`/`minor`/`major`
  increments (incl. `0.0.1 --minor--> 0.1.0`); explicit `X.Y.Z`; rejecting a
  non-increasing version; the `pyproject.toml` version-line rewrite (idempotent,
  touches only the `[project]` version). `--dry-run` makes no changes.
- **Build smoke:** `python -m build` yields a valid `penpine-<v>` sdist + wheel
  (run once during implementation to confirm packaging metadata is intact).
- **Workflow:** YAML-validated; the tag↔version guard and changelog shell logic
  dry-run in a scratch checkout. The publish/release API calls are verified by
  inspection against Gitea's documented endpoints (can't run in-sandbox).
- Whole suite stays green; ruff + mypy clean (the script is under `scripts/`, so
  confirm ruff's config lints or excludes it consistently).

## Non-goals

- No CI auto-tagging on push to `main` (manual script + policy only).
- No pre-release/build-metadata version handling (plain `X.Y.Z`).
- No publishing to public PyPI (Gitea registry only).
- The workflow references `PACKAGE_TOKEN`; creating the secret / enabling Actions
  is the user's one-time setup.

## Rollout

One implementation plan: (1) `scripts/bump_version.py` + its test; (2)
`.gitea/workflows/release.yml`; (3) CLAUDE.md policy + pyproject classifier; (4)
build smoke + suite/gates. Then (post-merge) run the script to cut `v0.1.0`.
