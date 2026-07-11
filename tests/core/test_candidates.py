from penpine.core.body.base import Body
from penpine.core.headers import Headers
from penpine.core.message import Request


def test_enumerates_params_headers_cookies_json():
    r = Request(
        method="POST",
        target="/api/v1/x?a=1&b=2",
        version="HTTP/1.1",
        headers=Headers(
            [("Host", "h"), ("Cookie", "sid=xyz"), ("Content-Type", "application/json")]
        ),
        body=Body(b'{"name":"ann"}', "application/json"),
    )
    exprs = {f"{c.kind}:{c.name}" if c.name else c.kind for c in r.injection_candidates()}
    assert "param:a" in exprs
    assert "param:b" in exprs
    assert "header:Host" in exprs
    assert "cookie:sid" in exprs
    assert "json:$.name" in exprs


def test_kinds_filter():
    r = Request(method="GET", target="/?a=1", version="HTTP/1.1", headers=Headers([("Host", "h")]))
    only = r.injection_candidates(kinds={"param"})
    assert {c.kind for c in only} == {"param"}


def test_enumerates_path_segments():
    r = Request(
        method="GET",
        target="/api/v1/users?a=1",
        version="HTTP/1.1",
        headers=Headers([("Host", "h")]),
    )
    exprs = {f"{c.kind}:{c.name}" for c in r.injection_candidates()}
    assert "path-seg:0" in exprs
    assert "path-seg:2" in exprs


def test_enumerates_multipart_fields():
    ct = "multipart/form-data; boundary=----b"
    raw = b'------b\r\nContent-Disposition: form-data; name="a"\r\n\r\n1\r\n------b--\r\n'
    r = Request(
        method="POST",
        target="/upload",
        version="HTTP/1.1",
        headers=Headers([("Host", "h"), ("Content-Type", ct)]),
        body=Body(raw, ct),
    )
    cands = r.injection_candidates(kinds={"multipart"})
    assert {c.kind for c in cands} == {"multipart"}
    assert any(c.name == "a" for c in cands)
