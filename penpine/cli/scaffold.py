"""Render the project template tree into a destination directory."""

from __future__ import annotations

import re
from pathlib import Path

from penpine.cli.exceptions import ScaffoldError

_PLACEHOLDER = re.compile(r"\{\{\s*([^}\s]+)\s*\}\}")
_HERE = Path(__file__).resolve().parent
_DEFAULT_SOURCE = _HERE / "templates" / "project"


def _render_text(text: str, variables: dict) -> str:
    def _sub(match: re.Match) -> str:
        key = match.group(1)
        if key not in variables:
            raise ScaffoldError(f"unknown template variable {{{{ {key} }}}}")
        return str(variables[key])

    return _PLACEHOLDER.sub(_sub, text)


def _map_segment(segment: str) -> str:
    if segment.startswith("dot-"):
        return "." + segment[len("dot-") :]
    return segment


def render_project(dst, variables: dict, *, source=None, force: bool = False) -> list:
    """Render every file under `source` into `dst`. `*.tmpl` files are variable-
    substituted and lose the suffix; all other files are copied verbatim; a
    `dot-` filename prefix maps to a leading `.`. Returns the files written."""
    dst = Path(dst)
    src = Path(source) if source is not None else _DEFAULT_SOURCE
    if dst.exists() and any(dst.iterdir()) and not force:
        raise ScaffoldError(f"target {dst} is not empty (use force=True / --force)")

    written = []
    for path in sorted(p for p in src.rglob("*") if p.is_file()):
        parts = [_map_segment(part) for part in path.relative_to(src).parts]
        rendered = parts[-1].endswith(".tmpl")
        if rendered:
            parts[-1] = parts[-1][: -len(".tmpl")]
        out_path = dst.joinpath(*parts)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        data = path.read_bytes()
        if rendered:
            data = _render_text(data.decode("utf-8"), variables).encode("utf-8")
        out_path.write_bytes(data)
        written.append(out_path)
    return written
