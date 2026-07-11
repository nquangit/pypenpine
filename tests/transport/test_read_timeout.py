import asyncio

import pytest

from penpine.transport.connection import Connection
from penpine.transport.exceptions import ReadTimeout
from penpine.transport.stream import ByteStream
from penpine.transport.timeouts import Timeouts


class _HangingStream(ByteStream):
    async def read(self, n=-1):
        await asyncio.sleep(10)
        return b""

    async def close(self):
        return None

    @property
    def closed(self):
        return False


class _CompleteStream(ByteStream):
    def __init__(self, data):
        self._data = data
        self._sent = False

    async def read(self, n=-1):
        if self._sent:
            return b""
        self._sent = True
        return self._data

    async def close(self):
        return None

    @property
    def closed(self):
        return False


async def test_read_timeout_raises():
    hanging = _HangingStream()

    async def _open(host, port, timeouts):
        return hanging

    conn = Connection("h", 80, timeouts=Timeouts(read=0.05), stream_opener=_open)
    await conn.open()
    with pytest.raises(ReadTimeout):
        await conn.read_response("GET")


async def test_read_timeout_disabled_completes():
    raw = b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nhi"
    stream = _CompleteStream(raw)

    async def _open(host, port, timeouts):
        return stream

    conn = Connection("h", 80, timeouts=Timeouts(read=None), stream_opener=_open)
    await conn.open()
    resp = await conn.read_response("GET")
    assert resp.status_code == 200
    assert resp.body.raw == b"hi"
