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
