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


def test_error_signature_matches_and_suppresses_baseline():
    from penpine.attack.modules._common import GENERIC_ERROR_SIGNATURES, error_signature
    from penpine.core.parse.http_parser import parse_response

    def r(body):
        return parse_response(
            b"HTTP/1.1 200 OK\r\nContent-Length: %d\r\n\r\n%s" % (len(body), body)
        )

    err = r(b"Traceback (most recent call last): File x")
    assert error_signature(err, None, GENERIC_ERROR_SIGNATURES) is not None
    # same signature already in baseline -> not attributable
    assert error_signature(err, err, GENERIC_ERROR_SIGNATURES) is None
    assert error_signature(r(b"all good"), None, GENERIC_ERROR_SIGNATURES) is None
