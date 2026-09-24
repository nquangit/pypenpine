import time

from penpine.auth.exceptions import LoginError
from penpine.auth.provider import FlowAuthProvider
from penpine.auth.session import Session
from penpine.core.message import Request
from penpine.data.extract import Extract
from penpine.flow.flow import Flow
from penpine.flow.step import Step
from tests.auth.test_tokens import make_jwt
from tests.flow._fakes import FakeActor, response

_JSON = b"Content-Type: application/json\r\n"


def _login_flow():
    return Flow(
        steps=[
            Step(
                "submit",
                request=Request.from_url("http://t/login"),
                capture=[
                    Extract("access_token", json="$.access_token"),
                    Extract("refresh_token", json="$.refresh_token"),
                ],
            ),
        ]
    )


def _refresh_flow():
    return Flow(
        steps=[
            Step(
                "exchange",
                request=Request.from_url("http://t/refresh?rt={{refresh_token}}"),
                capture=[
                    Extract("access_token", json="$.access_token"),
                    Extract("refresh_token", json="$.refresh_token", required=False),
                ],
            ),
        ]
    )


async def test_login_maps_token_refresh_and_jwt_expiry():
    exp = int(time.time()) + 3600
    jwt = make_jwt({"exp": exp})
    body = b'{"access_token":"%s","refresh_token":"R1"}' % jwt.encode()
    engine = FakeActor(script=[response(body, headers=_JSON)])
    provider = FlowAuthProvider(_login_flow(), _refresh_flow(), token_key="access_token")

    session = await provider.login(engine)

    assert session.token == jwt
    assert session.data["refresh_token"] == "R1"
    assert session.expires_at == float(exp)


async def test_refresh_carries_cookie_and_rotates_refresh_token():
    exp = int(time.time()) + 3600
    jwt2 = make_jwt({"exp": exp})
    body = b'{"access_token":"%s","refresh_token":"R2"}' % jwt2.encode()
    engine = FakeActor(script=[response(body, headers=_JSON)])
    provider = FlowAuthProvider(_login_flow(), _refresh_flow(), token_key="access_token")

    old = Session(token="old", cookies=[("JSESSIONID", "s")], data={"refresh_token": "R1"})
    session = await provider.refresh(engine, old)

    assert session.token == jwt2
    assert session.data["refresh_token"] == "R2"  # rotated token picked up
    assert ("JSESSIONID", "s") in session.cookies  # cookie carried over
    assert b"rt=R1" in engine.sent[0].serialize()  # seeded from the old session


async def test_refresh_failure_falls_back_to_login():
    exp = int(time.time()) + 3600
    jwt = make_jwt({"exp": exp})
    login_body = b'{"access_token":"%s","refresh_token":"R9"}' % jwt.encode()
    engine = FakeActor(
        script=[
            response(b"{}", status=b"401 Unauthorized", headers=_JSON),  # refresh: no token
            response(login_body, headers=_JSON),  # relogin succeeds
        ]
    )
    provider = FlowAuthProvider(_login_flow(), _refresh_flow(), token_key="access_token")

    old = Session(token="old", data={"refresh_token": "R1"})
    session = await provider.refresh(engine, old)

    assert session.token == jwt  # came from the fallback login
    assert len(engine.sent) == 2


async def test_refresh_failure_raises_when_relogin_disabled():
    from penpine.auth.exceptions import RefreshError

    engine = FakeActor(script=[response(b"{}", status=b"401 Unauthorized", headers=_JSON)])
    provider = FlowAuthProvider(
        _login_flow(), _refresh_flow(), token_key="access_token", relogin_on_refresh_error=False
    )

    import pytest

    with pytest.raises(RefreshError):
        await provider.refresh(engine, Session(data={"refresh_token": "R1"}))


def _refresh_token_only_login():
    return Flow(
        steps=[
            Step(
                "submit",
                request=Request.from_url("http://t/login"),
                capture=[Extract("refresh_token", json="$.refresh_token")],
            ),
        ]
    )


async def test_login_chains_refresh_when_no_access_token():
    # Login yields only a refresh token -> the provider runs the refresh flow
    # right away, so the returned session already carries an access token (no
    # cold-start "Bearer None").
    exp = int(time.time()) + 3600
    jwt = make_jwt({"exp": exp})
    engine = FakeActor(
        script=[
            response(b'{"refresh_token":"R1"}', headers=_JSON),  # login
            response(b'{"access_token":"%s"}' % jwt.encode(), headers=_JSON),  # exchange
        ]
    )
    provider = FlowAuthProvider(
        _refresh_token_only_login(), _refresh_flow(), token_key="access_token"
    )

    session = await provider.login(engine)

    assert session.token == jwt  # obtained by the chained refresh
    assert session.expires_at == float(exp)
    assert session.data["refresh_token"] == "R1"  # carried from login
    assert len(engine.sent) == 2  # login + exchange
    assert b"rt=R1" in engine.sent[1].serialize()  # exchange used login's refresh token


async def test_login_chain_failure_raises_login_error():
    # If the immediate exchange fails, that's a login failure -- no relogin loop.
    engine = FakeActor(
        script=[
            response(b'{"refresh_token":"R1"}', headers=_JSON),  # login
            response(b"{}", status=b"401 Unauthorized", headers=_JSON),  # exchange fails
        ]
    )
    provider = FlowAuthProvider(
        _refresh_token_only_login(), _refresh_flow(), token_key="access_token"
    )

    import pytest

    with pytest.raises(LoginError):
        await provider.login(engine)
    assert len(engine.sent) == 2  # login + one failed exchange, no retry storm


async def test_login_without_token_or_refresh_stays_tokenless():
    # No access token and no refresh token -> nothing to chain; not marked expired.
    login = Flow(
        steps=[
            Step(
                "submit",
                request=Request.from_url("http://t/login"),
                capture=[Extract("misc", json="$.misc", required=False)],
            ),
        ]
    )
    engine = FakeActor(script=[response(b'{"other":1}', headers=_JSON)])
    provider = FlowAuthProvider(login, _refresh_flow(), token_key="access_token")

    session = await provider.login(engine)

    assert session.token is None
    assert session.expires_at is None
    assert len(engine.sent) == 1  # login only, no exchange attempted
