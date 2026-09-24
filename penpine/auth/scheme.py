"""AuthScheme: how a Session is applied to a Request."""

from __future__ import annotations

import base64

from penpine.auth.exceptions import AuthError
from penpine.auth.session import Session
from penpine.core.cookies import parse_cookie_header
from penpine.core.message import Request


class AuthScheme:
    def apply(self, request: Request, session: Session) -> Request:
        raise NotImplementedError


class BearerAuth(AuthScheme):
    def __init__(self, token_source: str | None = None):
        self._source = token_source

    def apply(self, request: Request, session: Session) -> Request:
        token = session.data[self._source] if self._source else session.token
        return request.set_header("Authorization", f"Bearer {token}")


class BasicAuth(AuthScheme):
    def __init__(self, username: str, password: str):
        self._username = username
        self._password = password

    def apply(self, request: Request, session: Session) -> Request:
        token = base64.b64encode(f"{self._username}:{self._password}".encode()).decode()
        return request.set_header("Authorization", f"Basic {token}")


class HeaderAuth(AuthScheme):
    def __init__(self, name: str, value_source: str | None = None):
        self._name = name
        self._source = value_source

    def apply(self, request: Request, session: Session) -> Request:
        value = session.data[self._source] if self._source else session.token
        if value is None:
            raise AuthError(f"HeaderAuth({self._name!r}): no value to apply (session has no token)")
        return request.set_header(self._name, value)


class CookieAuth(AuthScheme):
    def apply(self, request: Request, session: Session) -> Request:
        merged: list[list[str]] = []
        index: dict[str, int] = {}
        for name, value in parse_cookie_header(request.headers.get("Cookie", "")):
            index[name] = len(merged)
            merged.append([name, value])
        for name, value in session.cookies:
            if name in index:
                merged[index[name]][1] = value
            else:
                index[name] = len(merged)
                merged.append([name, value])
        cookie = "; ".join(f"{name}={value}" for name, value in merged)
        return request.set_header("Cookie", cookie)


class MultiScheme(AuthScheme):
    def __init__(self, schemes):
        self._schemes = list(schemes)

    def apply(self, request: Request, session: Session) -> Request:
        for scheme in self._schemes:
            request = scheme.apply(request, session)
        return request


class HostScoped(AuthScheme):
    """Apply an inner scheme only when the request targets one of ``hosts``.

    The host is read from ``request.meta.host`` (set by the loaders/builder),
    falling back to the ``Host`` header; the port is ignored. This lets a single
    ``MultiScheme`` bind, say, a cookie to the web host and a bearer token to the
    API host without leaking either material across hosts.
    """

    def __init__(self, inner: AuthScheme, *hosts: str):
        self._inner = inner
        self._hosts = {h.lower() for h in hosts}

    def _host_of(self, request: Request) -> str:
        host = request.meta.host or request.headers.get("Host", "") or ""
        return host.split(":", 1)[0].lower()

    def apply(self, request: Request, session: Session) -> Request:
        if self._host_of(request) in self._hosts:
            return self._inner.apply(request, session)
        return request
