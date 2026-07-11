import asyncio

from penpine.auth.manager import SessionManager
from penpine.auth.provider import AuthProvider
from penpine.auth.scheme import BearerAuth
from penpine.auth.session import Session
from penpine.core.message import Request
from tests.auth._fakes import FakeEngine


class StubProvider(AuthProvider):
    def __init__(self):
        self.logins = 0

    async def login(self, engine):
        self.logins += 1
        return Session(token=f"tok{self.logins}")


def req():
    return Request.from_url("http://h:8080/resource")


def ok():
    return b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nok"


def unauthorized():
    return b"HTTP/1.1 401 Unauthorized\r\nContent-Length: 0\r\n\r\n"


async def test_first_send_logs_in_and_applies_scheme():
    provider = StubProvider()
    engine = FakeEngine([ok()])
    mgr = SessionManager(provider, BearerAuth(), auth_engine=FakeEngine([]), send_engine=engine)
    resp = await mgr.send(req())
    assert resp.status_code == 200
    assert provider.logins == 1
    assert engine.sent[0].headers["Authorization"] == "Bearer tok1"


async def test_expired_session_triggers_refresh():
    provider = StubProvider()
    engine = FakeEngine([ok()])
    mgr = SessionManager(
        provider, BearerAuth(), auth_engine=FakeEngine([]), send_engine=engine, expiry_skew=0
    )
    import time

    mgr._session = Session(token="old", expires_at=time.time() - 1)
    await mgr.send(req())
    assert provider.logins == 1
    assert engine.sent[0].headers["Authorization"] == "Bearer tok1"


async def test_401_triggers_relogin_and_retry():
    provider = StubProvider()
    engine = FakeEngine([unauthorized(), ok()])
    mgr = SessionManager(provider, BearerAuth(), auth_engine=FakeEngine([]), send_engine=engine)
    resp = await mgr.send(req())
    assert resp.status_code == 200
    assert provider.logins == 2
    assert engine.sent[1].headers["Authorization"] == "Bearer tok2"


async def test_concurrent_first_sends_log_in_once():
    provider = StubProvider()
    engine = FakeEngine([ok()])
    mgr = SessionManager(provider, BearerAuth(), auth_engine=FakeEngine([]), send_engine=engine)
    await asyncio.gather(*(mgr.send(req()) for _ in range(5)))
    assert provider.logins == 1


async def test_is_auth_failure_default():
    mgr = SessionManager(StubProvider(), BearerAuth())
    from penpine.core.parse.http_parser import parse_response

    assert mgr.is_auth_failure(parse_response(unauthorized())) is True
    assert mgr.is_auth_failure(parse_response(ok())) is False


async def test_persistent_401_returns_last_response_after_retries():
    provider = StubProvider()
    engine = FakeEngine([unauthorized()])  # always 401
    mgr = SessionManager(provider, BearerAuth(), auth_engine=FakeEngine([]), send_engine=engine)
    resp = await mgr.send(req(), max_auth_retries=2)
    assert resp.status_code == 401
    assert provider.logins == 3  # initial login + 2 re-logins
