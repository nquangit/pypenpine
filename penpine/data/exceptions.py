"""Data-layer exceptions."""

from __future__ import annotations

from penpine.exceptions import PenpineError


class DataError(PenpineError):
    """Base class for data/context failures."""


class ExtractError(DataError):
    """A required extraction target was absent or its spec was invalid."""


class TemplateError(DataError):
    """An unknown placeholder was encountered during a strict render."""
