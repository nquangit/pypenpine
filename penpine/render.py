"""Rich terminal rendering for reports and findings (presentation-only)."""

from __future__ import annotations

from rich.console import Console

__all__ = ["console"]

console = Console()

_MAX_FIELD = 200
_CONFIDENCE_STYLES = {"HIGH": "bold red", "MEDIUM": "yellow", "LOW": "dim cyan"}


def _status_style(status: object) -> str:
    try:
        code = int(status)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return "red"
    if 200 <= code < 300:
        return "green"
    if 300 <= code < 400:
        return "cyan"
    if 400 <= code < 500:
        return "yellow"
    return "red"


def _confidence_style(confidence: object) -> str:
    name = getattr(confidence, "name", str(confidence))
    return _CONFIDENCE_STYLES.get(name, "white")


def _humanize_bytes(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    kb = n / 1024
    if kb < 1024:
        return f"{kb:.1f} kB"
    return f"{kb / 1024:.1f} MB"


def _truncate(s: object, limit: int = _MAX_FIELD) -> str:
    s = str(s)
    return s if len(s) <= limit else s[: limit - 1] + "…"
