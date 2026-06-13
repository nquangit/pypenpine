import pytest
from penpine.core.parse.http_parser import parse_request, parse_response
from penpine.exceptions import MalformedRequestError


def test_parse_simple_get():
    raw = b"GET /a?x=1 HTTP/1.1\r\nHost: h\r\n\r\n"
    req = parse_request(raw)
    assert req.method == "GET"
    assert req.target == "/a?x=1"
    assert req.version == "HTTP/1.1"
    assert req.headers["Host"] == "h"
    assert req.body.raw == b""
    assert req.raw == raw


def test_parse_post_with_length():
    raw = b"POST / HTTP/1.1\r\nContent-Length: 4\r\n\r\nbody"
    req = parse_request(raw)
    assert req.body.raw == b"body"


def test_preserves_duplicate_and_mixed_case_headers():
    raw = b"GET / HTTP/1.1\r\nX-A: 1\r\nx-a: 2\r\n\r\n"
    req = parse_request(raw)
    assert req.headers.get_all("x-a") == ["1", "2"]


def test_lenient_lf_only_line_endings_warns():
    raw = b"GET / HTTP/1.1\nHost: h\n\n"
    req = parse_request(raw)
    assert req.headers["Host"] == "h"
    assert any("LF" in w or "line ending" in w for w in req.parse_warnings)


def test_strict_rejects_lf_only():
    raw = b"GET / HTTP/1.1\nHost: h\n\n"
    with pytest.raises(MalformedRequestError):
        parse_request(raw, strict=True)


def test_parse_response():
    raw = b"HTTP/1.1 404 Not Found\r\nContent-Length: 2\r\n\r\nno"
    resp = parse_response(raw)
    assert resp.status_code == 404
    assert resp.reason == "Not Found"
    assert resp.body.raw == b"no"
