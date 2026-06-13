from penpine.core.body.form_body import FormBody


def test_parse_preserves_order_and_dupes():
    fb = FormBody.from_bytes(b"a=1&b=2&a=3")
    assert fb.fields == [("a", "1"), ("b", "2"), ("a", "3")]


def test_get_returns_first():
    fb = FormBody.from_bytes(b"a=1&a=3")
    assert fb.get("a") == "1"


def test_set_returns_new_and_reserializes():
    fb = FormBody.from_bytes(b"a=1&b=2")
    fb2 = fb.set("a", "9")
    assert fb.get("a") == "1"
    assert fb2.get("a") == "9"
    assert fb2.to_bytes() == b"a=9&b=2"


def test_url_decoding():
    fb = FormBody.from_bytes(b"q=hello%20world")
    assert fb.get("q") == "hello world"
