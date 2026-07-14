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
    return subprocess.run(["git", *args], cwd=_ROOT, check=True, text=True, capture_output=capture)


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
