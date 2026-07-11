from penpine.core.message import Request

CHROME_GET = (
    "curl 'https://api.example.com/v1/items?page=2' \\\n"
    "  -H 'accept: application/json' \\\n"
    "  -H 'authorization: Bearer abc.def' \\\n"
    "  -b 'sid=xyz' \\\n"
    "  --compressed"
)

FIREFOX_POST = (
    "curl 'https://api.example.com/login' -X POST "
    "-H 'Content-Type: application/json' "
    '--data-raw $\'{"user":"ann","pw":"p@ss"}\''
)


def test_request_from_curl_classmethod_chrome_get():
    req = Request.from_curl(CHROME_GET)
    assert req.method == "GET"
    assert req.target == "/v1/items?page=2"
    assert req.headers.get("authorization") == "Bearer abc.def"
    assert req.headers.get("Cookie") == "sid=xyz"
    assert (req.meta.scheme, req.meta.host, req.meta.port) == ("https", "api.example.com", 443)


def test_request_from_curl_firefox_post_ansi_c_body():
    req = Request.from_curl(FIREFOX_POST)
    assert req.method == "POST"
    assert req.body.raw == b'{"user":"ann","pw":"p@ss"}'
    assert req.headers.get("Content-Type") == "application/json"


def test_loaders_from_curl_matches_classmethod():
    from penpine.core.loaders import from_curl

    a = from_curl("curl 'http://h/p'")
    b = Request.from_curl("curl 'http://h/p'")
    assert a.method == b.method and a.target == b.target and a.meta == b.meta


def test_from_curl_result_is_sendable_meta_set():
    req = Request.from_curl("curl 'https://t.example:8443/api' -d 'x=1'")
    assert req.meta.host == "t.example"
    assert req.meta.port == 8443
    assert req.meta.scheme == "https"
