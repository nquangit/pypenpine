"""Penpine L2 session & auth."""

from penpine.auth.exceptions import (
    AuthConfigError,
    AuthError,
    LoginError,
    RefreshError,
)
from penpine.auth.gate import RefreshGate
from penpine.auth.interceptor import AuthInterceptor
from penpine.auth.manager import SessionManager
from penpine.auth.profile import AuthProfile
from penpine.auth.provider import (
    AuthProvider,
    FlowLoginProvider,
    FormLoginProvider,
    JsonLoginProvider,
)
from penpine.auth.scheduler import RefreshScheduler
from penpine.auth.scheme import (
    AuthScheme,
    BasicAuth,
    BearerAuth,
    CookieAuth,
    HeaderAuth,
    MultiScheme,
)
from penpine.auth.session import Session

__all__ = [
    "Session",
    "AuthScheme",
    "BearerAuth",
    "BasicAuth",
    "CookieAuth",
    "HeaderAuth",
    "MultiScheme",
    "AuthProvider",
    "JsonLoginProvider",
    "FormLoginProvider",
    "FlowLoginProvider",
    "RefreshGate",
    "SessionManager",
    "RefreshScheduler",
    "AuthInterceptor",
    "AuthProfile",
    "AuthError",
    "LoginError",
    "RefreshError",
    "AuthConfigError",
]
