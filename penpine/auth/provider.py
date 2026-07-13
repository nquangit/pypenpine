"""AuthProvider: login/refresh/validate flows, plus ready-made providers."""

from __future__ import annotations

import time

from penpine.auth.exceptions import LoginError
from penpine.auth.session import Session
from penpine.core.builder import RequestBuilder
from penpine.core.cookies import parse_set_cookie
from penpine.flow.exceptions import StepError
from penpine.flow.flow import Flow


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
    def __init__(
        self,
        url,
        payload,
        *,
        method="POST",
        token_path="$.access_token",
        expires_path=None,
        headers=None,
    ):
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


class FlowLoginProvider(AuthProvider):
    """Log in by running a Flow and mapping its captured context to a Session.

    The login Flow is run with the provided `engine` as its actor (login has no
    auth yet), so its steps should rely on the flow's default actor rather than
    naming their own. Capture the token/expiry/cookies/data in the flow via
    `Extract`, then name the context keys here.

    Each `cookie_keys` entry is used as both the context key to read and the
    cookie name sent on the wire — name your captured context keys after the
    real cookie names (or capture into a key matching the cookie name). Keys are
    optional; a `token_key` that isn't present in the captured context yields
    `Session.token = None` (typically the login step's required Extract fails
    first, raising LoginError).
    """

    def __init__(self, flow, *, token_key=None, expires_key=None, cookie_keys=None, data_keys=None):
        self._flow = flow
        self._token_key = token_key
        self._expires_key = expires_key
        self._cookie_keys = list(cookie_keys or [])
        self._data_keys = list(data_keys or [])

    async def login(self, engine) -> Session:
        run_flow = Flow(
            steps=self._flow.steps,
            actor=engine,
            continue_on_error=self._flow.continue_on_error,
        )
        try:
            result = await run_flow.run()
        except StepError as exc:
            raise LoginError(f"login flow failed at step {exc.name!r}") from exc

        ctx = result.context
        token = ctx.get(self._token_key) if self._token_key else None
        expires_at = None
        if self._expires_key and self._expires_key in ctx:
            try:
                expires_at = time.time() + float(ctx[self._expires_key])
            except (TypeError, ValueError):
                expires_at = None
        cookies = [(k, ctx[k]) for k in self._cookie_keys if k in ctx]
        data = {k: ctx[k] for k in self._data_keys if k in ctx}
        return Session(token=token, cookies=cookies, data=data, expires_at=expires_at)
