from penpine.core.message import Request
from penpine.core.parse.http_parser import parse_response
from penpine.transport.engine import Engine


class StubConn:
    def __init__(self, host, port, *, use_tls, tls, proxy, timeouts):
        pass

    async def open(self):
        return self

    async def send_bytes(self, data):
        pass

    async def read_response(self, method="GET"):
        return parse_response(b"HTTP/1.1 201 Created\r\nContent-Length: 0\r\n\r\n")

    async def close(self):
        pass


def test_send_sync_blocks_and_returns_result():
    req = Request.from_url("http://h:8080/")
    engine = Engine(connection_factory=StubConn)
    try:
        resp = engine.send_sync(req)
        assert resp.status_code == 201
        resp2 = engine.send_many_sync([req, req])
        assert [r.status_code for r in resp2] == [201, 201]
    finally:
        engine.close()


def test_engine_context_manager_closes_loop():
    req = Request.from_url("http://h:8080/")
    with Engine(connection_factory=StubConn) as engine:
        assert engine.send_sync(req).status_code == 201
