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
    FlowAuthProvider,
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
    HostScoped,
    MultiScheme,
)
from penpine.auth.session import Session
from penpine.auth.tokens import jwt_claims, jwt_expiry

__all__ = [
    "Session",
    "AuthScheme",
    "BearerAuth",
    "BasicAuth",
    "CookieAuth",
    "HeaderAuth",
    "HostScoped",
    "MultiScheme",
    "AuthProvider",
    "JsonLoginProvider",
    "FormLoginProvider",
    "FlowLoginProvider",
    "FlowAuthProvider",
    "RefreshGate",
    "SessionManager",
    "RefreshScheduler",
    "AuthInterceptor",
    "AuthProfile",
    "jwt_claims",
    "jwt_expiry",
    "AuthError",
    "LoginError",
    "RefreshError",
    "AuthConfigError",
]
