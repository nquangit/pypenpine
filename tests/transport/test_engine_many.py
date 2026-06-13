import asyncio
from penpine.core.message import Request
from penpine.core.parse.http_parser import parse_response
from penpine.transport.engine import Engine


class CountingConn:
    live = 0
    peak = 0

    def __init__(self, host, port, *, use_tls, tls, proxy, timeouts):
        self.port = port

    async def open(self):
        CountingConn.live += 1
        CountingConn.peak = max(CountingConn.peak, CountingConn.live)
        await asyncio.sleep(0.01)
        return self

    async def send_bytes(self, data):
        pass

    async def read_response(self, method="GET"):
        return parse_response(
            f"HTTP/1.1 200 OK\r\nContent-Length: 1\r\n\r\n{self.port % 10}".encode())

    async def close(self):
        CountingConn.live -= 1


async def test_send_many_preserves_order():
    reqs = [Request.from_url(f"http://h:{8000+i}/") for i in range(5)]
    engine = Engine(connection_factory=CountingConn)
    resps = await engine.send_many(reqs)
    assert [r.status_code for r in resps] == [200] * 5
    assert len(resps) == 5


async def test_send_many_respects_concurrency_limit():
    CountingConn.live = 0
    CountingConn.peak = 0
    reqs = [Request.from_url(f"http://h:{8000+i}/") for i in range(10)]
    engine = Engine(max_concurrency=3, connection_factory=CountingConn)
    await engine.send_many(reqs)
    assert CountingConn.peak <= 3


async def test_send_many_return_exceptions():
    class Boom:
        def __init__(self, *a, **k):
            pass

        async def open(self):
            raise RuntimeError("boom")

        async def close(self):
            pass

    reqs = [Request.from_url("http://h:8080/")]
    engine = Engine(connection_factory=Boom)
    results = await engine.send_many(reqs, return_exceptions=True)
    assert isinstance(results[0], RuntimeError)
