from penpine.core.body.base import Body


def test_raw_preserved_and_text():
    b = Body(b"hello", content_type="text/plain")
    assert b.raw == b"hello"
    assert b.text() == "hello"
    assert len(b) == 5


def test_empty_body():
    b = Body(b"")
    assert b.raw == b""
    assert b.text() == ""


def test_equality_on_raw():
    assert Body(b"x") == Body(b"x")
    assert Body(b"x") != Body(b"y")
