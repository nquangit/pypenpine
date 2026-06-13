from penpine.core.message import Request
from penpine.core.headers import Headers
from penpine.core.body.base import Body


def base():
    return Request(method="POST", target="/p?a=1", version="HTTP/1.1",
                   headers=Headers([("Host", "h"), ("Content-Length", "0")]),
                   body=Body(b""))


def test_with_header_returns_copy():
    r = base()
    r2 = r.set_header("X-Test", "v")
    assert "X-Test" not in r.headers
    assert r2.headers["X-Test"] == "v"


def test_set_param_rebuilds_target():
    r = base().set_param("a", "9")
    assert r.target == "/p?a=9"


def test_with_body_recomputes_content_length():
    r = base().with_body(b"hello")
    assert r.body.raw == b"hello"
    assert r.headers["Content-Length"] == "5"


def test_preserve_content_length_keeps_mismatch():
    r = Request(method="POST", target="/", headers=Headers([("Content-Length", "100")]),
                body=Body(b""), preserve_content_length=True)
    r2 = r.with_body(b"hi")
    assert r2.headers["Content-Length"] == "100"
