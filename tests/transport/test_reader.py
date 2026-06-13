import pytest
from penpine.transport.reader import ResponseReader
from penpine.transport.stream import FakeByteStream
from penpine.transport.exceptions import IncompleteResponseError


async def test_content_length_body():
    raw = b"HTTP/1.1 200 OK\r\nContent-Length: 5\r\n\r\nhello"
    resp = await ResponseReader.read(FakeByteStream(raw), request_method="GET")
    assert resp.status_code == 200
    assert resp.body.raw == b"hello"
    assert resp.raw == raw


async def test_chunked_body_decoded_and_raw_preserved():
    raw = (b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n"
           b"5\r\nhello\r\n0\r\n\r\n")
    resp = await ResponseReader.read(FakeByteStream(raw), request_method="GET")
    assert resp.body.raw == b"hello"
    assert resp.raw == raw


async def test_chunked_with_trailers():
    raw = (b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n"
           b"4\r\nWiki\r\n0\r\nX-T: v\r\n\r\n")
    resp = await ResponseReader.read(FakeByteStream(raw), request_method="GET")
    assert resp.body.raw == b"Wiki"
    assert resp.raw == raw


async def test_read_until_eof_when_no_framing():
    raw = b"HTTP/1.1 200 OK\r\nConnection: close\r\n\r\nbodybytes"
    resp = await ResponseReader.read(FakeByteStream(raw), request_method="GET")
    assert resp.body.raw == b"bodybytes"


async def test_head_request_has_no_body():
    raw = b"HTTP/1.1 200 OK\r\nContent-Length: 5\r\n\r\n"
    resp = await ResponseReader.read(FakeByteStream(raw), request_method="HEAD")
    assert resp.body.raw == b""


async def test_304_has_no_body():
    raw = b"HTTP/1.1 304 Not Modified\r\nContent-Length: 5\r\n\r\n"
    resp = await ResponseReader.read(FakeByteStream(raw), request_method="GET")
    assert resp.status_code == 304
    assert resp.body.raw == b""


async def test_truncated_headers_raise():
    with pytest.raises(IncompleteResponseError):
        await ResponseReader.read(FakeByteStream(b"HTTP/1.1 200 OK\r\nContent-"),
                                  request_method="GET")
