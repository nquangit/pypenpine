import pytest

from penpine.transport.exceptions import IncompleteResponseError
from penpine.transport.stream import FakeByteStream


async def test_read_returns_up_to_n_then_empty_on_eof():
    s = FakeByteStream(b"hello")
    assert await s.read(3) == b"hel"
    assert await s.read(10) == b"lo"
    assert await s.read(10) == b""


async def test_readexactly_ok_and_incomplete():
    s = FakeByteStream(b"abc")
    assert await s.readexactly(2) == b"ab"
    with pytest.raises(IncompleteResponseError):
        await s.readexactly(5)


async def test_readline_includes_newline():
    s = FakeByteStream(b"line1\r\nline2")
    assert await s.readline() == b"line1\r\n"
    assert await s.readline() == b"line2"


async def test_write_and_sent_and_tls_and_close():
    s = FakeByteStream()
    s.write(b"xy")
    await s.drain()
    assert s.sent == b"xy"
    await s.start_tls(object(), "example.com")
    assert s.tls_calls == ["example.com"]
    assert not s.closed
    await s.close()
    assert s.closed
