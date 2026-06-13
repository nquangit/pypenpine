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
