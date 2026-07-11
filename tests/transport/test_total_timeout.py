import asyncio

import pytest

from penpine.core.message import Request
from penpine.core.parse.http_parser import parse_response
from penpine.transport.engine import Engine
from penpine.transport.exceptions import TotalTimeout
from penpine.transport.timeouts import Timeouts


class _SlowConn:
    def __init__(self, host, port, **kwargs):
        self.host = host
        self.port = port

    async def open(self):
        await asyncio.sleep(10)
        return self

    async def send_bytes(self, data):
        return None

    async def read_response(self, method="GET"):
        return parse_response(b"HTTP/1.1 200 OK\r\nContent-Length: 0\r\n\r\n")

    async def close(self):
        return None


class _FastConn:
    def __init__(self, host, port, **kwargs):
        self.host = host
        self.port = port

    async def open(self):
        return self

    async def send_bytes(self, data):
        return None

    async def read_response(self, method="GET"):
        return parse_response(b"HTTP/1.1 200 OK\r\nContent-Length: 0\r\n\r\n")

    async def close(self):
        return None


async def test_total_timeout_raises():
    engine = Engine(
        connection_factory=_SlowConn,
        timeouts=Timeouts(connect=None, read=None, total=0.05),
    )
    with pytest.raises(TotalTimeout):
        await engine.send(Request.from_url("http://h/"))


async def test_total_timeout_disabled_completes():
    engine = Engine(
        connection_factory=_FastConn,
        timeouts=Timeouts(connect=None, read=None, total=None),
    )
    resp = await engine.send(Request.from_url("http://h/"))
    assert resp.status_code == 200
