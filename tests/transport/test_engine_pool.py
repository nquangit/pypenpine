from penpine.core.message import Request
from penpine.core.parse.http_parser import parse_response
from penpine.transport.engine import Engine
from penpine.transport.exceptions import IncompleteResponseError

_OK = b"HTTP/1.1 200 OK\r\nContent-Length: 0\r\n\r\n"


class _Conn:
    def __init__(self, host, port, response, fail_on_use=None, **kwargs):
        self.host = host
        self.port = port
        self._resp = response
        self._fail_on = fail_on_use
        self._closed = False
        self.uses = 0

    async def open(self):
        return self

    async def send_bytes(self, data):
        return None

    async def read_response(self, method="GET"):
        self.uses += 1
        if self._fail_on is not None and self.uses == self._fail_on:
            raise IncompleteResponseError("server closed idle connection")
        return self._resp

    async def close(self):
        self._closed = True

    @property
    def closed(self):
        return self._closed


def _counting_factory(response, first_fail_on_use=None):
    created = []

    def factory(host, port, **kwargs):
        fail = first_fail_on_use if not created else None
        conn = _Conn(host, port, response, fail_on_use=fail)
        created.append(conn)
        return conn

    return factory, created


async def test_pool_reuses_connection():
    factory, created = _counting_factory(parse_response(_OK))
    engine = Engine(connection_factory=factory, reuse_connections=True)
    await engine.send(Request.from_url("http://h/a"))
    await engine.send(Request.from_url("http://h/b"))
    assert len(created) == 1
    await engine.aclose()


async def test_default_engine_opens_each_time():
    factory, created = _counting_factory(parse_response(_OK))
    engine = Engine(connection_factory=factory)
    await engine.send(Request.from_url("http://h/a"))
    await engine.send(Request.from_url("http://h/b"))
    assert len(created) == 2


async def test_different_host_uses_separate_connection():
    factory, created = _counting_factory(parse_response(_OK))
    engine = Engine(connection_factory=factory, reuse_connections=True)
    await engine.send(Request.from_url("http://h1/a"))
    await engine.send(Request.from_url("http://h2/a"))
    assert len(created) == 2
    await engine.aclose()


async def test_stale_reused_connection_retries_once():
    factory, created = _counting_factory(parse_response(_OK), first_fail_on_use=2)
    engine = Engine(connection_factory=factory, reuse_connections=True)
    await engine.send(Request.from_url("http://h/a"))
    resp = await engine.send(Request.from_url("http://h/b"))
    assert resp.status_code == 200
    assert len(created) == 2
    assert created[0].closed is True
    await engine.aclose()


async def test_aclose_closes_parked_connections():
    factory, created = _counting_factory(parse_response(_OK))
    engine = Engine(connection_factory=factory, reuse_connections=True)
    await engine.send(Request.from_url("http://h/a"))
    assert created[0].closed is False
    await engine.aclose()
    assert created[0].closed is True


async def test_async_context_manager_closes_pool():
    factory, created = _counting_factory(parse_response(_OK))
    async with Engine(connection_factory=factory, reuse_connections=True) as engine:
        await engine.send(Request.from_url("http://h/a"))
    assert created[0].closed is True


def test_sync_close_drains_pool():
    factory, created = _counting_factory(parse_response(_OK))
    engine = Engine(connection_factory=factory, reuse_connections=True)
    engine.send_sync(Request.from_url("http://h/a"))
    engine.close()
    assert created[0].closed is True
