import pytest

from penpine.core.curl import _assemble_data, _split_header, _tokenize
from penpine.exceptions import BuildError


def test_tokenize_strips_leading_curl_and_splits_quotes():
    toks = _tokenize("curl 'http://h/a b' -H \"X: 1\"")
    assert toks == ["http://h/a b", "-H", "X: 1"]


def test_tokenize_joins_line_continuations():
    cmd = "curl 'http://h/' \\\n  -H 'A: 1' \\\n  -H 'B: 2'"
    assert _tokenize(cmd) == ["http://h/", "-H", "A: 1", "-H", "B: 2"]


def test_tokenize_decodes_ansi_c_quoting():
    toks = _tokenize("curl 'http://h/' --data-raw $'a\\tb\\nc'")
    assert toks == ["http://h/", "--data-raw", "a\tb\nc"]


def test_tokenize_unbalanced_quote_raises():
    with pytest.raises(BuildError):
        _tokenize("curl 'http://h/")


def test_split_header_colon_and_semicolon():
    assert _split_header("Content-Type: application/json") == ("Content-Type", "application/json")
    assert _split_header("X-Empty;") == ("X-Empty", "")


def test_assemble_data_joins_and_urlencodes():
    assert _assemble_data([("data", "a=1"), ("data", "b=2")]) == "a=1&b=2"
    assert _assemble_data([("urlencode", "q=a b")]) == "q=a%20b"
    assert _assemble_data([("urlencode", "plain value")]) == "plain%20value"
    assert _assemble_data([("raw", '{"x":1}')]) == '{"x":1}'
