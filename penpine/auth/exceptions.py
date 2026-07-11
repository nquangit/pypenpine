"""Auth-layer exceptions."""

from __future__ import annotations

from penpine.exceptions import PenpineError


class AuthError(PenpineError):
    """Base class for auth failures."""


class LoginError(AuthError):
    """A login flow failed."""


class RefreshError(AuthError):
    """A refresh flow failed."""


class AuthConfigError(AuthError):
    """Invalid auth configuration."""
