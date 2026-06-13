from penpine.core.cookies import parse_cookie_header, parse_set_cookie


def test_parse_request_cookie_header():
    assert parse_cookie_header("a=1; b=2; a=3") == [("a", "1"), ("b", "2"), ("a", "3")]


def test_parse_set_cookie():
    c = parse_set_cookie("sid=abc; Path=/; HttpOnly; Max-Age=60")
    assert c.name == "sid"
    assert c.value == "abc"
    assert c.attributes["path"] == "/"
    assert c.attributes["max-age"] == "60"
    assert c.flags == {"httponly"}
