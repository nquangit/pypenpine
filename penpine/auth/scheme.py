"""AuthScheme: how a Session is applied to a Request."""

from __future__ import annotations

import base64

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
