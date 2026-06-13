import pytest

from penpine.core.message import Request
from penpine.core.parse.http_parser import parse_response
from penpine.data.context import Context
from penpine.data.capture import capture, CaptureInterceptor
from penpine.data.extract import Extract
from penpine.data.exceptions import ExtractError


def resp_with_token():
    return parse_response(b"HTTP/1.1 200 OK\r\nX-Token: tk\r\nContent-Length: 0\r\n\r\n")


async def test_manual_capture_writes_to_context():
    ctx = Context()
    out = capture(ctx, resp_with_token(), [Extract("t", header="X-Token")])
    assert out == {"t": "tk"}
    assert ctx.get("t") == "tk"


async def test_manual_capture_is_strict():
    ctx = Context()
    with pytest.raises(ExtractError):
        capture(ctx, resp_with_token(), [Extract("missing", header="Nope")])


async def test_interceptor_captures_present_values():
    ctx = Context()
    ic = CaptureInterceptor(ctx, [Extract("t", header="X-Token")])
    out = await ic.after_receive(Request.from_url("http://h/"), resp_with_token())
    assert ctx.get("t") == "tk"
    assert out.status_code == 200


async def test_interceptor_swallows_missing_and_returns_response():
    ctx = Context()
    resp = resp_with_token()
    ic = CaptureInterceptor(ctx, [Extract("missing", header="Nope"),
                                  Extract("t", header="X-Token")])
    out = await ic.after_receive(Request.from_url("http://h/"), resp)
    assert out is resp
    assert ctx.has("missing") is False
    assert ctx.get("t") == "tk"


async def test_interceptor_before_send_is_passthrough():
    ctx = Context()
    ic = CaptureInterceptor(ctx, [])
    req = Request.from_url("http://h/")
    assert await ic.before_send(req) is req


async def test_capture_interceptor_on_real_engine():
    from penpine.transport.engine import Engine
    from penpine.core.message import Request

    class StubConn:
        def __init__(self, *a, **k):
            pass

        async def open(self):
            return self

        async def send_bytes(self, data):
            pass

        async def read_response(self, method="GET"):
            return parse_response(
                b"HTTP/1.1 200 OK\r\nX-Token: T\r\nContent-Length: 0\r\n\r\n")

        async def close(self):
            pass

    ctx = Context()
    engine = Engine(
        interceptors=[CaptureInterceptor(ctx, [Extract("tok", header="X-Token")])],
        connection_factory=StubConn)
    await engine.send(Request.from_url("http://h:8080/"))
    assert ctx.get("tok") == "T"
