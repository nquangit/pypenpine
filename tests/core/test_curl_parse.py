import base64

import pytest

from penpine.core.curl import parse_curl
from penpine.exceptions import BuildError


def test_simple_get_sets_meta_and_host():
    req = parse_curl("curl 'https://api.example/things?id=1'")
    assert req.method == "GET"
    assert req.target == "/things?id=1"
    assert req.headers.get("Host") == "api.example"
    assert req.meta.scheme == "https"
    assert req.meta.host == "api.example"
    assert req.meta.port == 443


def test_headers_preserved_in_order():
    req = parse_curl("curl 'http://h/' -H 'A: 1' -H 'B: 2'")
    names = [n for n, _ in req.headers.items()]
    assert names == ["Host", "A", "B"]


def test_data_infers_post_and_content_type_and_length():
    req = parse_curl("curl 'http://h/x' --data-raw 'a=1&b=2'")
    assert req.method == "POST"
    assert req.body.raw == b"a=1&b=2"
    assert req.headers.get("Content-Type") == "application/x-www-form-urlencoded"
    assert req.headers.get("Content-Length") == "7"


def test_explicit_content_type_not_overridden():
    req = parse_curl("curl 'http://h/x' -H 'Content-Type: text/plain' -d 'hi'")
    assert req.headers.get("Content-Type") == "text/plain"


def test_json_flag_sets_body_and_content_type_and_accept():
    req = parse_curl("curl 'http://h/x' --json '{\"a\":1}'")
    assert req.method == "POST"
    assert req.body.raw == b'{"a":1}'
    assert req.headers.get("Content-Type") == "application/json"
    assert req.headers.get("Accept") == "application/json"


def test_dash_G_moves_data_to_query_and_clears_body():
    req = parse_curl("curl 'http://h/s?x=1' -G --data-urlencode 'q=a b'")
    assert req.method == "GET"
    assert req.target == "/s?x=1&q=a%20b"
    assert req.body.raw == b""


def test_explicit_method_wins():
    req = parse_curl("curl 'http://h/x' -X DELETE")
    assert req.method == "DELETE"


def test_basic_auth_cookie_ua_referer():
    req = parse_curl("curl 'http://h/' -u 'a:b' -b 'k=v' -A 'agent/1' -e 'http://ref/'")
    expected = "Basic " + base64.b64encode(b"a:b").decode()
    assert req.headers.get("Authorization") == expected
    assert req.headers.get("Cookie") == "k=v"
    assert req.headers.get("User-Agent") == "agent/1"
    assert req.headers.get("Referer") == "http://ref/"


def test_long_flag_equals_form():
    req = parse_curl("curl 'http://h/x' --data-raw='y=2' --request=PUT")
    assert req.method == "PUT"
    assert req.body.raw == b"y=2"


def test_ignored_value_flag_does_not_capture_url():
    req = parse_curl("curl -x http://proxy:8080 -k --max-time 30 'http://real/target'")
    assert req.meta.host == "real"
    assert req.target == "/target"


def test_unknown_flag_ignored():
    req = parse_curl("curl --totally-unknown 'http://h/ok'")
    assert req.meta.host == "h"


def test_non_default_port_in_host_header():
    req = parse_curl("curl 'http://h:8000/p'")
    assert req.headers.get("Host") == "h:8000"
    assert req.meta.port == 8000


def test_form_flag_raises():
    with pytest.raises(BuildError):
        parse_curl("curl 'http://h/' -F 'a=b'")


def test_no_url_raises():
    with pytest.raises(BuildError):
        parse_curl("curl -X POST")
