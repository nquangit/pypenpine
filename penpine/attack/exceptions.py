"""Attack-layer exceptions."""
from __future__ import annotations

from penpine.exceptions import PenpineError


class AttackError(PenpineError):
    """Base class for attack-framework failures."""


class AttackConfigError(AttackError):
    """Unknown/duplicate module or invalid module configuration."""
