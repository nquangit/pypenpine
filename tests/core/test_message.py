from penpine.core.meta import ConnectionMeta
from penpine.core.message import Request, Response
from penpine.core.headers import Headers
from penpine.core.body.base import Body


def test_request_construct_defaults():
    r = Request(method="GET", target="/", version="HTTP/1.1")
    assert isinstance(r.headers, Headers)
    assert isinstance(r.body, Body)
    assert r.meta == ConnectionMeta()


def test_request_is_immutable():
    r = Request(method="GET", target="/", version="HTTP/1.1")
    try:
        r.method = "POST"
        assert False, "should be frozen"
    except AttributeError:
        pass


def test_clone_produces_equal_independent_copy():
    r = Request(method="GET", target="/", version="HTTP/1.1",
                headers=Headers([("A", "1")]))
    c = r.clone()
    assert c.method == r.method and list(c.headers.items()) == list(r.headers.items())
    assert c is not r


def test_response_fields():
    resp = Response(status_code=200, reason="OK", version="HTTP/1.1")
    assert resp.status_code == 200
    assert resp.reason == "OK"
