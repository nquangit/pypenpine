from penpine.core.url import parse_url, parse_query, build_query, set_query_param


def test_parse_url_components():
    u = parse_url("https://example.com:8443/a/b?x=1&y=2")
    assert u.scheme == "https"
    assert u.host == "example.com"
    assert u.port == 8443
    assert u.path == "/a/b"
    assert u.query == "x=1&y=2"


def test_default_ports():
    assert parse_url("http://h/").port == 80
    assert parse_url("https://h/").port == 443


def test_parse_query_preserves_order_and_dupes():
    assert parse_query("a=1&b=2&a=3") == [("a", "1"), ("b", "2"), ("a", "3")]


def test_set_query_param_replaces_first_keeps_rest():
    target = "/p?a=1&b=2"
    assert set_query_param(target, "a", "9") == "/p?a=9&b=2"


def test_set_query_param_adds_when_absent():
    assert set_query_param("/p", "a", "1") == "/p?a=1"
