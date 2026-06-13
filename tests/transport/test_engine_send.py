import pytest
from penpine.core.message import Request
from penpine.core.parse.http_parser import parse_response
from penpine.transport.engine import Engine
from penpine.transport.interceptor import Interceptor, RetrySignal
from penpine.transport.exceptions import TransportError


class StubConn:
    instances = []

    def __init__(self, host, port, *, use_tls, tls, proxy, timeouts):
        self.host = host
        self.port = port
        self.use_tls = use_tls
        self.sent = None
        StubConn.instances.append(self)

    async def open(self):
        return self

    async def send_bytes(self, data):
        self.sent = data

    async def read_response(self, method="GET"):
        return parse_response(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nok")

    async def close(self):
        pass


def setup_function():
    StubConn.instances = []


async def test_send_uses_meta_and_returns_response():
    req = Request.from_url("http://h:8080/path")
    engine = Engine(connection_factory=StubConn)
    resp = await engine.send(req)
    assert resp.status_code == 200
    assert StubConn.instances[0].host == "h"
    assert StubConn.instances[0].port == 8080
    assert StubConn.instances[0].use_tls is False
    assert StubConn.instances[0].sent.startswith(b"GET /path")


async def test_https_meta_sets_use_tls():
    req = Request.from_url("https://h/x")
    engine = Engine(connection_factory=StubConn)
    await engine.send(req)
    assert StubConn.instances[0].use_tls is True


async def test_missing_meta_raises():
    req = Request(method="GET", target="/")
    with pytest.raises(TransportError):
        await Engine(connection_factory=StubConn).send(req)


async def test_before_send_transforms_request():
    class AddHeader(Interceptor):
        async def before_send(self, request):
            return request.set_header("X-Auth", "tok")

    req = Request.from_url("http://h:8080/")
    engine = Engine(interceptors=[AddHeader()], connection_factory=StubConn)
    await engine.send(req)
    assert b"X-Auth: tok" in StubConn.instances[0].sent


async def test_retry_signal_retries_until_max():
    calls = {"n": 0}

    class RetryOnce(Interceptor):
        async def after_receive(self, request, response):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RetrySignal
            return response

    req = Request.from_url("http://h:8080/")
    engine = Engine(interceptors=[RetryOnce()], max_retries=1,
                    connection_factory=StubConn)
    resp = await engine.send(req)
    assert resp.status_code == 200
    assert len(StubConn.instances) == 2


async def test_connection_closed_when_open_fails():
    from penpine.transport.exceptions import ConnectError

    state = {"closed": False}

    class FailingConn:
        def __init__(self, *a, **k):
            pass

        async def open(self):
            raise ConnectError("nope")

        async def send_bytes(self, data):
            pass

        async def read_response(self, method="GET"):
            pass

        async def close(self):
            state["closed"] = True

    req = Request.from_url("http://h:8080/")
    with pytest.raises(ConnectError):
        await Engine(connection_factory=FailingConn).send(req)
    assert state["closed"] is True


async def test_http_proxy_plain_http_rewrites_to_absolute_form():
    from penpine.transport.proxy import ProxyConfig

    req = Request.from_url("http://h:8080/path?q=1")
    engine = Engine(proxy=ProxyConfig.from_url("http://127.0.0.1:3128"),
                    connection_factory=StubConn)
    await engine.send(req)
    assert StubConn.instances[0].sent.startswith(b"GET http://h:8080/path?q=1 HTTP/1.1")
