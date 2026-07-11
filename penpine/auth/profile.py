"""AuthProfile: an identity bundling a provider + scheme into a SessionManager."""

from __future__ import annotations

from dataclasses import dataclass

from penpine.auth.manager import SessionManager
from penpine.auth.provider import AuthProvider
from penpine.auth.scheme import AuthScheme


@dataclass
class AuthProfile:
    name: str
    provider: AuthProvider
    scheme: AuthScheme

    def manager(self, *, auth_engine=None, send_engine=None, **kwargs) -> SessionManager:
        return SessionManager(
            self.provider, self.scheme, auth_engine=auth_engine, send_engine=send_engine, **kwargs
        )
