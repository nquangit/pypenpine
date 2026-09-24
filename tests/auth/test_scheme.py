from penpine.auth.scheme import (
    BasicAuth,
    BearerAuth,
    CookieAuth,
    HeaderAuth,
    HostScoped,
    MultiScheme,
)
from penpine.auth.session import Session
from penpine.core.headers import Headers
from penpine.core.message import Request


def base_request(headers=None):
    return Request(method="GET", target="/", version="HTTP/1.1", headers=Headers(headers or []))


def test_bearer_from_token():
    r = BearerAuth().apply(base_request(), Session(token="abc"))
    assert r.headers["Authorization"] == "Bearer abc"


def test_bearer_from_data_source():
    s = Session(data={"access": "xyz"})
    r = BearerAuth(token_source="access").apply(base_request(), s)
    assert r.headers["Authorization"] == "Bearer xyz"


def test_basic_static():
    r = BasicAuth("user", "pass").apply(base_request(), Session())
    assert r.headers["Authorization"] == "Basic dXNlcjpwYXNz"


def test_header_auth_custom():
    r = HeaderAuth("X-API-Key").apply(base_request(), Session(token="k1"))
    assert r.headers["X-API-Key"] == "k1"


def test_cookie_merges_and_overrides():
    req = base_request([("Cookie", "a=1; b=2")])
    s = Session(cookies=[("b", "9"), ("c", "3")])
    r = CookieAuth().apply(req, s)
    assert r.headers["Cookie"] == "a=1; b=9; c=3"


def test_multi_scheme_applies_in_order():
    s = Session(token="t", cookies=[("sid", "x")])
    r = MultiScheme([BearerAuth(), CookieAuth()]).apply(base_request(), s)
    assert r.headers["Authorization"] == "Bearer t"
    assert r.headers["Cookie"] == "sid=x"


def test_apply_returns_new_request():
    req = base_request()
    r = BearerAuth().apply(req, Session(token="t"))
    assert "Authorization" not in req.headers
    assert r is not req


def test_header_auth_from_data_source():
    s = Session(data={"key": "K"})
    r = HeaderAuth("X-API-Key", value_source="key").apply(base_request(), s)
    assert r.headers["X-API-Key"] == "K"


def test_host_scoped_applies_on_match():
    scheme = HostScoped(BearerAuth(), "api.example")
    r = scheme.apply(Request.from_url("https://api.example/x"), Session(token="t"))
    assert r.headers["Authorization"] == "Bearer t"


def test_host_scoped_skips_other_host():
    scheme = HostScoped(BearerAuth(), "api.example")
    req = Request.from_url("https://web.example/x")
    r = scheme.apply(req, Session(token="t"))
    assert "Authorization" not in r.headers
    assert r is req  # untouched


def test_host_scoped_ignores_port_and_case():
    scheme = HostScoped(CookieAuth(), "API.Example")
    req = base_request([("Host", "api.example:8443")])
    r = scheme.apply(req, Session(cookies=[("sid", "x")]))
    assert r.headers["Cookie"] == "sid=x"


def test_multi_scheme_host_scoped_separates_material():
    # Cookie only to the web host, bearer only to the API host — no cross-leak.
    scheme = MultiScheme(
        [HostScoped(CookieAuth(), "web.example"), HostScoped(BearerAuth(), "api.example")]
    )
    session = Session(token="jwt", cookies=[("JSESSIONID", "s")])

    web = scheme.apply(Request.from_url("https://web.example/"), session)
    assert web.headers["Cookie"] == "JSESSIONID=s"
    assert "Authorization" not in web.headers

    api = scheme.apply(Request.from_url("https://api.example/"), session)
    assert api.headers["Authorization"] == "Bearer jwt"
    assert "Cookie" not in api.headers
