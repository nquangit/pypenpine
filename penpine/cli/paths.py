"""Project-name slugging and local penpine source detection."""
from __future__ import annotations

import re
from pathlib import Path

import penpine

_NON_IDENT = re.compile(r"[^a-z0-9]+")


def slugify(name: str) -> str:
    """An importable, lowercase slug. Empty/digit-leading cores get a 'p_' prefix."""
    slug = _NON_IDENT.sub("_", name.strip().lower()).strip("_")
    if not slug or slug[0].isdigit():
        slug = "p_" + slug
    return slug


def find_penpine_root() -> Path | None:
    """The directory holding penpine's pyproject.toml, or None when penpine is
    installed without a source tree."""
    start = Path(penpine.__file__).resolve().parent
    for candidate in (start, *start.parents):
        pyproject = candidate / "pyproject.toml"
        if pyproject.exists() and 'name = "penpine"' in pyproject.read_text(encoding="utf-8"):
            return candidate
    return None


def penpine_spec(root: Path | None) -> str:
    """The requirements.txt dependency line for penpine."""
    return f"-e {root}" if root is not None else "penpine"
