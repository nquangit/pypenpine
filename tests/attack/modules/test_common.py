import re

from penpine.attack.modules._common import body_text, marker, search_signatures
from penpine.core.parse.http_parser import parse_response


def test_marker_unique_and_prefixed():
    a, b = marker("PX"), marker("PX")
    assert a.startswith("PX_") and b.startswith("PX_") and a != b


def test_body_text():
    resp = parse_response(b"HTTP/1.1 200 OK\r\nContent-Length: 5\r\n\r\nhello")
    assert body_text(resp) == "hello"


def test_search_signatures_returns_first_match_or_none():
    patterns = [re.compile(r"ORA-\d+"), re.compile(r"mysql", re.I)]
    assert search_signatures("error ORA-00933 here", patterns).group(0) == "ORA-00933"
    assert search_signatures("a MySQL thing", patterns).group(0).lower() == "mysql"
    assert search_signatures("nothing here", patterns) is None
