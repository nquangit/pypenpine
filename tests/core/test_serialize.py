import pytest
from penpine.core.parse.http_parser import parse_request
from penpine.core.serialize import serialize_request

CORPUS = [
    b"GET /a?x=1 HTTP/1.1\r\nHost: h\r\n\r\n",
    b"POST / HTTP/1.1\r\nContent-Length: 4\r\nHost: h\r\n\r\nbody",
    b"GET / HTTP/1.1\r\nX-A: 1\r\nx-a: 2\r\nHOST: H\r\n\r\n",
]


@pytest.mark.parametrize("raw", CORPUS)
def test_roundtrip_byte_exact(raw):
    req = parse_request(raw)
    assert serialize_request(req) == raw


def test_request_serialize_method():
    raw = b"GET / HTTP/1.1\r\nHost: h\r\n\r\n"
    assert parse_request(raw).serialize() == raw


def test_roundtrip_chunked_body_is_byte_exact():
    raw = (b"POST / HTTP/1.1\r\nHost: h\r\nTransfer-Encoding: chunked\r\n\r\n"
           b"5\r\nhello\r\n0\r\n\r\n")
    assert parse_request(raw).serialize() == raw


def test_roundtrip_colonless_header_verbatim():
    raw = b"GET / HTTP/1.1\r\nHost: h\r\nBadHeaderLineNoColon\r\n\r\n"
    assert parse_request(raw).serialize() == raw


def test_roundtrip_lf_only_preserved():
    raw = b"GET / HTTP/1.1\nHost: h\n\n"
    assert parse_request(raw).serialize() == raw


def test_roundtrip_json_post_byte_exact():
    raw = b'POST /a HTTP/1.1\r\nHost: h\r\nContent-Type: application/json\r\nContent-Length: 10\r\n\r\n{"a":1234}'
    assert parse_request(raw).serialize() == raw


def test_serialize_rebuilds_after_mutation():
    raw = b"GET /a HTTP/1.1\r\nHost: h\r\n\r\n"
    req = parse_request(raw).set_header("X-New", "v")
    out = req.serialize()
    assert b"X-New: v" in out
    assert out.startswith(b"GET /a HTTP/1.1")
