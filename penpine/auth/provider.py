"""AuthProvider: login/refresh/validate flows, plus ready-made providers."""
from __future__ import annotations

import time

from penpine.auth.exceptions import LoginError
from penpine.auth.session import Session
from penpine.core.builder import RequestBuilder
from penpine.core.cookies import parse_set_cookie


class AuthProvider:
    async def login(self, engine) -> Session:
        raise NotImplementedError

    async def refresh(self, engine, session) -> Session:
        return await self.login(engine)

    async def validate(self, engine, session) -> bool:
        return not session.is_expired()


def _check_2xx(resp) -> None:
    if not (200 <= resp.status_code < 300):
        raise LoginError(f"login failed: HTTP {resp.status_code}")


class JsonLoginProvider(AuthProvider):
    def __init__(self, url, payload, *, method="POST", token_path="$.access_token",
                 expires_path=None, headers=None):
        self._url = url
        self._payload = payload
        self._method = method
        self._token_path = token_path
        self._expires_path = expires_path
        self._headers = headers or {}

    async def login(self, engine) -> Session:
        builder = RequestBuilder().method(self._method).url(self._url).json(self._payload)
        for name, value in self._headers.items():
            builder = builder.header(name, value)
        resp = await engine.send(builder.build())
        _check_2xx(resp)
        try:
            token = resp.body.json.get(self._token_path)
        except Exception as exc:
            raise LoginError(f"token not found at {self._token_path}") from exc
        expires_at = None
        if self._expires_path:
            try:
                expires_at = time.time() + float(resp.body.json.get(self._expires_path))
            except Exception:
                expires_at = None
        return Session(token=token, expires_at=expires_at)


class FormLoginProvider(AuthProvider):
    def __init__(self, url, fields, *, method="POST", headers=None):
        self._url = url
        self._fields = fields
        self._method = method
        self._headers = headers or {}

    async def login(self, engine) -> Session:
        builder = RequestBuilder().method(self._method).url(self._url).form(self._fields)
        for name, value in self._headers.items():
            builder = builder.header(name, value)
        resp = await engine.send(builder.build())
        _check_2xx(resp)
        cookies = []
        for name, value in resp.headers.items():
            if name.lower() == "set-cookie":
                parsed = parse_set_cookie(value)
                cookies.append((parsed.name, parsed.value))
        return Session(cookies=cookies)
