from penpine.core.headers import Headers


def test_preserves_order_casing_duplicates():
    h = Headers([("Host", "a"), ("X-Foo", "1"), ("x-foo", "2")])
    assert list(h.items()) == [("Host", "a"), ("X-Foo", "1"), ("x-foo", "2")]


def test_case_insensitive_lookup():
    h = Headers([("Content-Type", "application/json")])
    assert h["content-type"] == "application/json"
    assert h.get("CONTENT-TYPE") == "application/json"
    assert h.get("missing", "d") == "d"
    assert "CONTENT-type" in h


def test_get_all_returns_every_match():
    h = Headers([("Set-Cookie", "a=1"), ("set-cookie", "b=2")])
    assert h.get_all("set-cookie") == ["a=1", "b=2"]


def test_mutators_return_new_instance_and_keep_original():
    h = Headers([("A", "1")])
    h2 = h.add("A", "2")
    assert list(h.items()) == [("A", "1")]
    assert list(h2.items()) == [("A", "1"), ("A", "2")]
    h3 = h2.set("a", "9")
    assert list(h3.items()) == [("a", "9")]
    h4 = h3.remove("A")
    assert list(h4.items()) == []
