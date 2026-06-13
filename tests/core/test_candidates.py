from penpine.core.message import Request
from penpine.core.headers import Headers
from penpine.core.body.base import Body


def test_enumerates_params_headers_cookies_json():
    r = Request(method="POST", target="/api/v1/x?a=1&b=2", version="HTTP/1.1",
                headers=Headers([("Host", "h"), ("Cookie", "sid=xyz"),
                                 ("Content-Type", "application/json")]),
                body=Body(b'{"name":"ann"}', "application/json"))
    exprs = {f"{c.kind}:{c.name}" if c.name else c.kind
             for c in r.injection_candidates()}
    assert "param:a" in exprs
    assert "param:b" in exprs
    assert "header:Host" in exprs
    assert "cookie:sid" in exprs
    assert "json:$.name" in exprs


def test_kinds_filter():
    r = Request(method="GET", target="/?a=1", version="HTTP/1.1",
                headers=Headers([("Host", "h")]))
    only = r.injection_candidates(kinds={"param"})
    assert {c.kind for c in only} == {"param"}
