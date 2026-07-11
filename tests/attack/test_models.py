from penpine.attack.models import (
    Confidence,
    Finding,
    InjectionPoint,
    Payload,
    TestCase,
)
from penpine.core.message import Request


def test_from_locator_param():
    loc = Request.from_url("http://h/p?a=1").locate("param:a")
    point = InjectionPoint.from_locator(loc)
    assert point.expr == "param:a"
    assert point.kind == "param"
    assert point.name == "a"
    assert point.value == "1"
    assert point.attack_types == ()


def test_from_locator_request_line_kind():
    loc = Request.from_url("http://h/p").locate("method")
    point = InjectionPoint.from_locator(loc)
    assert point.expr == "method"
    assert point.kind == "method"
    assert point.name == ""
    assert point.value == "GET"


def test_from_locator_json():
    req = Request.from_raw(
        b"POST / HTTP/1.1\r\nHost: h\r\nContent-Type: application/json\r\n"
        b'Content-Length: 14\r\n\r\n{"user":"ann"}'
    )
    loc = req.locate("json:$.user")
    point = InjectionPoint.from_locator(loc)
    assert point.expr == "json:$.user"
    assert point.kind == "json"


def test_payload_and_testcase_defaults():
    p = Payload("' OR 1=1--", technique="boolean")
    assert p.value == "' OR 1=1--"
    assert p.technique == "boolean"
    assert p.meta == {}
    point = InjectionPoint("param:a", "param", "a", "1")
    tc = TestCase(point=point, payload=p, attack_type="sqli")
    assert tc.request is None
    assert tc.marker is None
    assert tc.meta == {}


def test_confidence_ordering():
    assert Confidence.HIGH > Confidence.LOW
    assert Confidence(2) == Confidence.MEDIUM


def test_finding_defaults():
    point = InjectionPoint("param:a", "param", "a", "1")
    f = Finding(
        attack_type="sqli",
        point=point,
        payload=Payload("x"),
        confidence=Confidence.HIGH,
        evidence="sql error in body",
    )
    assert f.request is None
    assert f.response is None
    assert f.meta == {}
