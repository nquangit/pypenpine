import pytest

from penpine.core.message import Request
from penpine.core.parse.http_parser import parse_response
from penpine.transport.engine import Engine
from penpine.transport.interceptor import Interceptor


class _BoomConn:
    def __init__(self, host, port, **kwargs):
        self.host, self.port = host, port

    async def open(self):
        raise ConnectionRefusedError("refused")

    async def send_bytes(self, data):
        return None

    async def read_response(self, method="GET"):
        return parse_response(b"HTTP/1.1 200 OK\r\nContent-Length: 0\r\n\r\n")

    async def close(self):
        return None


class _OkConn(_BoomConn):
    async def open(self):
        return self


class _Recorder(Interceptor):
    def __init__(self, name, log):
        self.name, self.log = name, log

    async def on_error(self, request, exc):
        self.log.append((self.name, request, exc))


async def test_on_error_fires_in_reversed_order_and_reraises():
    log = []
    a, b = _Recorder("a", log), _Recorder("b", log)
    engine = Engine(connection_factory=_BoomConn, interceptors=[a, b])
    with pytest.raises(ConnectionRefusedError):
        await engine.send(Request.from_url("http://h/path"))
    # reversed order: b before a
    assert [name for name, _, _ in log] == ["b", "a"]
    # each got the request and the exception
    assert all(r.target == "/path" and isinstance(e, ConnectionRefusedError) for _, r, e in log)


async def test_on_error_hook_that_raises_does_not_mask_original():
    class _BadHook(Interceptor):
        async def on_error(self, request, exc):
            raise ValueError("hook blew up")

    engine = Engine(connection_factory=_BoomConn, interceptors=[_BadHook()])
    with pytest.raises(ConnectionRefusedError):  # original error, not ValueError
        await engine.send(Request.from_url("http://h/"))


async def test_success_still_returns_and_calls_after_receive():
    seen = []

    class _Watch(Interceptor):
        async def after_receive(self, request, response):
            seen.append(response.status_code)
            return response

    engine = Engine(connection_factory=_OkConn, interceptors=[_Watch()])
    resp = await engine.send(Request.from_url("http://h/"))
    assert resp.status_code == 200
    assert seen == [200]
