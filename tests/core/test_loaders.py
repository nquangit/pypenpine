from penpine.core.message import Request


def test_from_raw_string():
    r = Request.from_raw("GET / HTTP/1.1\r\nHost: h\r\n\r\n")
    assert r.method == "GET"
    assert r.headers["Host"] == "h"


def test_from_raw_sets_meta_when_provided():
    r = Request.from_raw(b"GET / HTTP/1.1\r\nHost: h\r\n\r\n", scheme="https", host="h", port=443)
    assert r.meta.scheme == "https"
    assert r.meta.host == "h"
    assert r.meta.port == 443


def test_from_file(tmp_path):
    p = tmp_path / "req.txt"
    p.write_bytes(b"GET /x HTTP/1.1\r\nHost: h\r\n\r\n")
    r = Request.from_file(str(p))
    assert r.target == "/x"


def test_from_url_builds_request_and_meta():
    r = Request.from_url("https://example.com:8443/a?x=1", method="GET")
    assert r.method == "GET"
    assert r.target == "/a?x=1"
    assert r.headers["Host"] == "example.com:8443"
    assert r.meta.scheme == "https"
    assert r.meta.port == 8443
