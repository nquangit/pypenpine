import pytest

from penpine.core.parse.http_parser import parse_response
from penpine.data.extract import Extract, extract_value, run_extractors
from penpine.data.exceptions import ExtractError


def json_resp():
    return parse_response(
        b'HTTP/1.1 200 OK\r\nContent-Length: 22\r\n\r\n{"user":{"id":"U7"}}\r\n')


def test_extract_json():
    assert extract_value(json_resp(), Extract("id", json="$.user.id")) == "U7"


def test_extract_header():
    resp = parse_response(b"HTTP/1.1 200 OK\r\nX-Token: tk\r\nContent-Length: 0\r\n\r\n")
    assert extract_value(resp, Extract("t", header="X-Token")) == "tk"


def test_extract_cookie():
    resp = parse_response(
        b"HTTP/1.1 200 OK\r\nSet-Cookie: sid=abc; Path=/\r\nContent-Length: 0\r\n\r\n")
    assert extract_value(resp, Extract("s", cookie="sid")) == "abc"


def test_extract_regex_group_and_whole():
    resp = parse_response(b"HTTP/1.1 200 OK\r\nContent-Length: 11\r\n\r\ncsrf=XY9abc")
    assert extract_value(resp, Extract("c", regex=r"csrf=(\w+)")) == "XY9abc"
    assert extract_value(resp, Extract("c", regex=r"csrf=\w+")) == "csrf=XY9abc"


def test_extract_status():
    resp = parse_response(b"HTTP/1.1 201 Created\r\nContent-Length: 0\r\n\r\n")
    assert extract_value(resp, Extract("code", status=True)) == 201


def test_required_miss_raises_and_optional_default():
    resp = parse_response(b"HTTP/1.1 200 OK\r\nContent-Length: 0\r\n\r\n")
    with pytest.raises(ExtractError):
        extract_value(resp, Extract("t", header="Nope"))
    assert extract_value(resp, Extract("t", header="Nope", required=False, default="d")) == "d"


def test_no_source_raises():
    with pytest.raises(ExtractError):
        extract_value(json_resp(), Extract("x"))


def test_run_extractors_returns_dict():
    resp = parse_response(
        b'HTTP/1.1 200 OK\r\nX-Token: tk\r\nContent-Length: 22\r\n\r\n{"user":{"id":"U7"}}\r\n')
    out = run_extractors(resp, [Extract("id", json="$.user.id"), Extract("t", header="X-Token")])
    assert out == {"id": "U7", "t": "tk"}


def test_json_non_json_body_raises_clear_error():
    resp = parse_response(b"HTTP/1.1 200 OK\r\nContent-Length: 9\r\n\r\n<html>err")
    with pytest.raises(ExtractError, match="not JSON"):
        extract_value(resp, Extract("x", json="$.id"))


def test_json_path_miss_respects_required_and_default():
    resp = parse_response(b'HTTP/1.1 200 OK\r\nContent-Length: 9\r\n\r\n{"a":1}\r\n')
    with pytest.raises(ExtractError):
        extract_value(resp, Extract("x", json="$.missing"))
    assert extract_value(resp, Extract("x", json="$.missing",
                                        required=False, default="d")) == "d"


def test_extract_cookie_among_multiple_set_cookie():
    resp = parse_response(
        b"HTTP/1.1 200 OK\r\nSet-Cookie: a=1\r\n"
        b"Set-Cookie: sid=abc; Path=/\r\nContent-Length: 0\r\n\r\n")
    assert extract_value(resp, Extract("s", cookie="sid")) == "abc"
