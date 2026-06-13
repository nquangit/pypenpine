from penpine.core.message import Request
from penpine.auth.manager import SessionManager
from penpine.auth.provider import JsonLoginProvider
from penpine.auth.scheme import BearerAuth
from tests.auth._fakes import FakeEngine


def login_response(request):
    login_response.n += 1
    body = b'{"access_token":"TOK%d"}' % login_response.n
    return (b"HTTP/1.1 200 OK\r\nContent-Length: " + str(len(body)).encode()
            + b"\r\n\r\n" + body)
login_response.n = 0


def protected(request):
    auth = request.headers.get("Authorization")
    if auth == f"Bearer TOK{login_response.n}":
        return b"HTTP/1.1 200 OK\r\nContent-Length: 3\r\n\r\nyes"
    return b"HTTP/1.1 401 Unauthorized\r\nContent-Length: 0\r\n\r\n"


async def test_end_to_end_login_apply_and_relogin():
    login_response.n = 0
    auth_engine = FakeEngine([login_response])
    send_engine = FakeEngine([
        b"HTTP/1.1 401 Unauthorized\r\nContent-Length: 0\r\n\r\n",
        protected,
    ])
    provider = JsonLoginProvider("http://h/login", {"u": "a"}, token_path="$.access_token")
    mgr = SessionManager(provider, BearerAuth(),
                         auth_engine=auth_engine, send_engine=send_engine)
    resp = await mgr.send(Request.from_url("http://h/protected"))
    assert resp.status_code == 200
    assert resp.body.raw == b"yes"
    assert len(auth_engine.sent) == 2
