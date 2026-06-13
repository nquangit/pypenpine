from penpine.core.message import Request
from penpine.auth.manager import SessionManager
from penpine.auth.provider import AuthProvider
from penpine.auth.scheme import BearerAuth
from penpine.auth.session import Session
from tests.auth._fakes import FakeEngine


class StubProvider(AuthProvider):
    async def login(self, engine):
        return Session(token="t")


def req():
    return Request.from_url("http://h:8080/r")


def ok():
    return b"HTTP/1.1 200 OK\r\nContent-Length: 0\r\n\r\n"


async def test_send_many_preserves_order():
    mgr = SessionManager(StubProvider(), BearerAuth(),
                         auth_engine=FakeEngine([]), send_engine=FakeEngine([ok()]))
    resps = await mgr.send_many([req(), req(), req()])
    assert [r.status_code for r in resps] == [200, 200, 200]


def test_send_sync_and_context_manager():
    with SessionManager(StubProvider(), BearerAuth(),
                        auth_engine=FakeEngine([]),
                        send_engine=FakeEngine([ok()])) as mgr:
        resp = mgr.send_sync(req())
        assert resp.status_code == 200
        resps = mgr.send_many_sync([req(), req()])
        assert [r.status_code for r in resps] == [200, 200]
