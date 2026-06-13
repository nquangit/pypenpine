import pytest

from penpine.core.message import Request
from penpine.core.headers import Headers
from penpine.data.identity import Identity
from penpine.data.context import Context
from penpine.data.profile import DataProfile
from penpine.data.extract import Extract
from penpine.data.exceptions import DataError
from tests.auth._fakes import FakeEngine


def ok():
    return b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nok"


async def test_send_delegates_to_manager():
    engine = FakeEngine([ok()])
    ident = Identity("A", manager=engine)
    resp = await ident.send(Request.from_url("http://h/r"))
    assert resp.status_code == 200
    assert len(engine.sent) == 1


async def test_send_without_manager_raises():
    ident = Identity("A")
    with pytest.raises(DataError):
        await ident.send(Request.from_url("http://h/r"))


def test_render_merges_data_and_ctx_with_ctx_override():
    data = DataProfile("A", {"k": "from_data", "fixture": "F"})
    ctx = Context({"k": "from_ctx"})
    ident = Identity("A", data=data, context=ctx)
    req = Request(method="GET", target="/{{k}}/{{fixture}}", headers=Headers([("Host", "h")]))
    out = ident.render(req)
    assert out.target == "/from_ctx/F"


def test_capture_writes_to_identity_context():
    from penpine.core.parse.http_parser import parse_response
    ctx = Context()
    ident = Identity("A", context=ctx)
    resp = parse_response(b"HTTP/1.1 200 OK\r\nX-Token: tk\r\nContent-Length: 0\r\n\r\n")
    ident.capture(resp, [Extract("t", header="X-Token")])
    assert ctx.get("t") == "tk"


def test_defaults_create_empty_data_and_context():
    ident = Identity("A")
    assert isinstance(ident.data, DataProfile)
    assert isinstance(ident.ctx, Context)
    assert ident.manager is None


def test_send_sync_delegates_and_no_manager_raises():
    class SyncStub:
        def send_sync(self, request, **kw):
            return "RESP"

    assert Identity("A", manager=SyncStub()).send_sync(
        Request.from_url("http://h/")) == "RESP"
    with pytest.raises(DataError):
        Identity("A").send_sync(Request.from_url("http://h/"))
