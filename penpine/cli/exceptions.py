"""CLI exception hierarchy."""

from __future__ import annotations

from penpine.exceptions import PenpineError


class CliError(PenpineError):
    """Base class for CLI failures."""


class ScaffoldError(CliError):
    """Project scaffolding failed (bad name, non-empty target, template bug)."""


class VenvError(CliError):
    """Virtualenv creation or dependency install failed."""
