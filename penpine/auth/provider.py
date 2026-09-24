"""AuthProvider: login/refresh/validate flows, plus ready-made providers."""

from __future__ import annotations

import time

from penpine.auth.exceptions import LoginError, RefreshError
from penpine.auth.session import Session
from penpine.auth.tokens import jwt_expiry
from penpine.core.builder import RequestBuilder
from penpine.core.cookies import parse_set_cookie
from penpine.data.context import Context
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


class FlowAuthProvider(AuthProvider):
    """Token-exchange auth driven by two Flows: one to log in, one to refresh.

    ``login_flow`` runs with no auth and establishes the initial material —
    cookie, refresh token, and (when the login response carries it) the first
    access token. ``refresh_flow`` is seeded with the current session's cookies +
    data, so its steps can reference ``{{refresh_token}}`` (or ``{{<cookie
    name>}}``) to exchange the refresh token for a fresh access token.

    Both flows yield a context dict that is mapped onto a Session:

    * ``token_key``   -> ``Session.token``   (the access token; its JWT ``exp``
      sets ``expires_at``, which is what drives ``SessionManager`` to refresh)
    * ``cookie_keys`` -> ``Session.cookies`` (entry name == cookie name on wire)
    * ``data_keys``   -> ``Session.data``    (e.g. ``"refresh_token"``)

    On refresh the previous session's cookies and data are carried over, then
    overwritten by anything the refresh flow re-captured (e.g. a rotated refresh
    token). If the refresh flow fails and ``relogin_on_refresh_error`` is set, a
    full ``login`` is run, so an expired refresh token self-heals.

    When login yields a refresh token but no access token yet, the provider runs
    the refresh flow immediately, so the returned session already carries an
    access token and the very first send does not go out as ``Bearer None``. As
    a safety net, a session still left without a token but holding a refresh
    token is marked already-expired so the next send exchanges it.
    """

    def __init__(
        self,
        login_flow,
        refresh_flow,
        *,
        token_key,
        cookie_keys=None,
        data_keys=("refresh_token",),
        relogin_on_refresh_error=True,
    ):
        self._login_flow = login_flow
        self._refresh_flow = refresh_flow
        self._token_key = token_key
        self._cookie_keys = list(cookie_keys or [])
        self._data_keys = list(data_keys)
        self._relogin = relogin_on_refresh_error

    async def _run(self, flow, engine, seed=None) -> dict:
        run_flow = Flow(
            steps=flow.steps,
            actor=engine,
            context=Context(seed or {}),
            continue_on_error=flow.continue_on_error,
        )
        return (await run_flow.run()).context

    def _session(self, ctx: dict, *, carry: Session | None = None) -> Session:
        # Carry the old cookies/data forward, then let the fresh context win --
        # but a missing optional capture (None) must not wipe the carried value.
        cookies = dict(carry.cookies) if carry else {}
        data = dict(carry.data) if carry else {}
        for k in self._cookie_keys:
            if ctx.get(k) is not None:
                cookies[k] = ctx[k]
        for k in self._data_keys:
            if ctx.get(k) is not None:
                data[k] = ctx[k]  # picks up a rotated refresh token
        token = ctx.get(self._token_key)
        if token is not None:
            expires_at = jwt_expiry(token)
        elif data.get("refresh_token"):
            # Refresh token but no access token yet: mark expired so the next
            # send exchanges it for the first access token.
            expires_at = 0.0
        else:
            expires_at = None
        return Session(
            token=token,
            cookies=list(cookies.items()),
            data=data,
            expires_at=expires_at,
        )

    async def _exchange(self, engine, session) -> Session:
        """Run the refresh flow against `session`'s material (seeding its cookies
        + data into the flow context) and map the result, carrying the old
        cookies/data forward. Raises StepError if the flow fails."""
        seed = {**dict(session.cookies), **(session.data or {})}
        ctx = await self._run(self._refresh_flow, engine, seed=seed)
        return self._session(ctx, carry=session)

    async def login(self, engine) -> Session:
        try:
            ctx = await self._run(self._login_flow, engine)
        except StepError as exc:
            raise LoginError(f"login flow failed at step {exc.name!r}") from exc
        session = self._session(ctx)
        if session.token is None and session.data.get("refresh_token"):
            # Login gave us a refresh token but no access token; fetch the first
            # access token now so the first send carries a real bearer instead of
            # `Bearer None`. No relogin fallback here — that would recurse.
            try:
                session = await self._exchange(engine, session)
            except StepError as exc:
                raise LoginError(f"initial token exchange failed at step {exc.name!r}") from exc
        return session

    async def refresh(self, engine, session) -> Session:
        try:
            return await self._exchange(engine, session)
        except StepError as exc:
            if self._relogin:
                return await self.login(engine)
            raise RefreshError(f"refresh flow failed at step {exc.name!r}") from exc
