import pytest

from penpine.core.message import Request
from penpine.core.parse.http_parser import parse_response
from penpine.auth.interceptor import AuthInterceptor
from penpine.auth.manager import SessionManager
from penpine.auth.provider import AuthProvider
from penpine.auth.scheme import BearerAuth
from penpine.auth.session import Session
from penpine.transport.interceptor import RetrySignal
from tests.auth._fakes import FakeEngine


class StubProvider(AuthProvider):
    async def login(self, engine):
        return Session(token="t")


def manager():
    return SessionManager(StubProvider(), BearerAuth(), auth_engine=FakeEngine([]))


async def test_before_send_ensures_and_applies():
    ic = AuthInterceptor(manager())
    out = await ic.before_send(Request.from_url("http://h/r"))
    assert out.headers["Authorization"] == "Bearer t"


async def test_after_receive_raises_retry_on_401():
    mgr = manager()
    await mgr.ensure_fresh()
    assert mgr.session is not None
    ic = AuthInterceptor(mgr)
    resp = parse_response(b"HTTP/1.1 401 Unauthorized\r\nContent-Length: 0\r\n\r\n")
    with pytest.raises(RetrySignal):
        await ic.after_receive(Request.from_url("http://h/r"), resp)
    assert mgr.session is None


async def test_after_receive_passes_through_on_200():
    ic = AuthInterceptor(manager())
    resp = parse_response(b"HTTP/1.1 200 OK\r\nContent-Length: 0\r\n\r\n")
    out = await ic.after_receive(Request.from_url("http://h/r"), resp)
    assert out is resp
