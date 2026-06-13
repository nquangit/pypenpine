import pytest
from penpine.core.message import Request
from penpine.core.headers import Headers
from penpine.core.body.base import Body
from penpine.exceptions import LocatorError


def req_with_json():
    return Request(method="POST", target="/p?a=1&b=2", version="HTTP/1.1",
                   headers=Headers([("Host", "h"), ("Cookie", "sid=xyz"),
                                    ("Content-Type", "application/json")]),
                   body=Body(b'{"user":{"id":7}}', "application/json"))


def test_locate_param():
    r = req_with_json()
    loc = r.locate("param:a")
    assert loc.value == "1"
    assert r.replace_at("param:a", "99").target == "/p?a=99&b=2"


def test_locate_header_and_cookie():
    r = req_with_json()
    assert r.locate("header:Host").value == "h"
    assert r.locate("cookie:sid").value == "xyz"


def test_locate_json():
    r = req_with_json()
    assert r.locate("json:$.user.id").value == 7
    r2 = r.replace_at("json:$.user.id", 8)
    assert r2.body.json.get("$.user.id") == 8


def test_locate_request_line_parts():
    r = req_with_json()
    assert r.locate("method").value == "POST"
    assert r.replace_at("method", "PUT").method == "PUT"


def test_missing_target_raises():
    with pytest.raises(LocatorError):
        req_with_json().locate("param:nope")
