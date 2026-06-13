import penpine
from penpine.auth import (
    AuthProfile, SessionManager, Session, AuthProvider, JsonLoginProvider,
    BearerAuth, RefreshScheduler, AuthInterceptor, RefreshGate, AuthError,
)
from tests.auth._fakes import FakeEngine


class StubProvider(AuthProvider):
    async def login(self, engine):
        return Session(token="t")


def test_profile_builds_manager():
    profile = AuthProfile("admin", StubProvider(), BearerAuth())
    mgr = profile.manager(auth_engine=FakeEngine([]))
    assert isinstance(mgr, SessionManager)
    assert profile.name == "admin"


def test_public_exports():
    assert all([AuthProfile, SessionManager, RefreshScheduler, AuthInterceptor,
                RefreshGate, JsonLoginProvider, AuthError])
    assert hasattr(penpine, "SessionManager")
    assert hasattr(penpine, "AuthProfile")
    assert penpine.SessionManager is SessionManager
