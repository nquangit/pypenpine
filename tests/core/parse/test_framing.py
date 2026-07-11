import pytest

from penpine.core.headers import Headers
from penpine.core.parse.framing import body_length, decode_chunked
from penpine.exceptions import ParseError


def test_content_length():
    h = Headers([("Content-Length", "5")])
    assert body_length(h) == ("length", 5)


def test_chunked():
    h = Headers([("Transfer-Encoding", "chunked")])
    assert body_length(h) == ("chunked", None)


def test_no_body():
    assert body_length(Headers()) == ("none", 0)


def test_decode_chunked():
    raw = b"4\r\nWiki\r\n5\r\npedia\r\n0\r\n\r\n"
    decoded, consumed = decode_chunked(raw)
    assert decoded == b"Wikipedia"
    assert consumed == len(raw)


def test_decode_chunked_incomplete_raises():
    with pytest.raises(ParseError):
        decode_chunked(b"4\r\nWi")


def test_decode_chunked_with_trailers_consumes_all():
    raw = b"4\r\nWiki\r\n0\r\nX-Trailer: v\r\n\r\n"
    decoded, consumed = decode_chunked(raw)
    assert decoded == b"Wiki"
    assert consumed == len(raw)
