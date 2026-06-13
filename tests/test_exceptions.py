from penpine.exceptions import (
    PenpineError, ParseError, MalformedRequestError,
    BodyParseError, LocatorError, BuildError,
)


def test_hierarchy():
    assert issubclass(ParseError, PenpineError)
    assert issubclass(MalformedRequestError, ParseError)
    assert issubclass(BodyParseError, ParseError)
    assert issubclass(LocatorError, PenpineError)
    assert issubclass(BuildError, PenpineError)


def test_parse_error_carries_offset():
    err = ParseError("bad", offset=12, snippet="GET / HT")
    assert err.offset == 12
    assert err.snippet == "GET / HT"
    assert "offset=12" in str(err)
