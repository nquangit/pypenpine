from penpine.attack.analyze import detectors as d


def test_is_numeric_and_integer():
    assert d.is_numeric("12") and d.is_numeric(12) and d.is_numeric("1.5") and d.is_numeric(1.5)
    assert not d.is_numeric("ab") and not d.is_numeric("") and not d.is_numeric(None)
    assert not d.is_numeric(True)
    assert d.is_integer("12") and d.is_integer(-3) and d.is_integer("12")
    assert not d.is_integer("1.5") and not d.is_integer("x")


def test_is_url():
    assert d.is_url("http://x") and d.is_url("https://x/y") and d.is_url("//cdn/x")
    assert not d.is_url("/path") and not d.is_url("x") and not d.is_url(None)


def test_is_path():
    assert d.is_path("../etc/passwd") and d.is_path("a/b") and d.is_path("c\\d")
    assert not d.is_path("abc") and not d.is_path("http://x")


def test_is_email_uuid_json_bool_empty():
    assert d.is_email("a@b.com") and not d.is_email("a@b")
    assert d.is_uuid("12345678-1234-1234-1234-123456789abc")
    assert not d.is_uuid("nope")
    assert d.looks_like_json('{"a":1}') and d.looks_like_json("[1]")
    assert not d.looks_like_json("plain")
    assert d.is_boolean("true") and d.is_boolean("0") and d.is_boolean(False)
    assert not d.is_boolean("maybe")
    assert d.is_empty(None) and d.is_empty("   ") and not d.is_empty("x")
