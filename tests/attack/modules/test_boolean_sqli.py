from penpine.attack.models import Confidence, InjectionPoint
from penpine.attack.modules.differential import (
    BOOLEAN_SQLI_MODULE,
    BooleanSqliModule,
    _similar,
)
from penpine.attack.types import AttackType
from penpine.core.message import Request
from penpine.core.parse.http_parser import parse_response


def _resp(status, body):
    return parse_response(
        b"HTTP/1.1 %d X\r\nContent-Length: %d\r\n\r\n%s" % (status, len(body), body)
    )


def test_similar_status_and_length():
    a = _resp(200, b"hello world")
    b = _resp(200, b"hello worlx")  # same length, same status
    assert _similar(a, b, tolerance=0) is True
    assert _similar(a, _resp(404, b"hello world"), tolerance=0) is False
    assert _similar(a, _resp(200, b"short"), tolerance=2) is False
    assert _similar(a, None, tolerance=0) is False


class _BoolSender:
    """TRUE payloads render like the baseline; FALSE payloads differ."""

    def __init__(self):
        self.base = _resp(200, b"A" * 500)

    async def send(self, request):
        raw = request.serialize()
        if b"1%3D2" in raw or b"1'%3D'2" in raw or b"1=2" in raw:  # FALSE condition
            return _resp(200, b"B" * 50)
        return self.base  # baseline + TRUE condition


async def test_boolean_module_flags_injectable_point():
    module = BooleanSqliModule()
    point = InjectionPoint(expr="param:q", kind="param", name="q", value="hi")
    req = Request.from_url("http://h/s?q=hi")
    finding = await module.probe(point, req, _BoolSender())
    assert finding is not None
    assert finding.attack_type == AttackType.SQLI
    assert finding.confidence == Confidence.HIGH
    assert finding.response is not None


class _StaticSender:
    async def send(self, request):
        return _resp(200, b"same for everything")


async def test_boolean_module_no_finding_when_uniform():
    module = BooleanSqliModule()
    point = InjectionPoint(expr="param:q", kind="param", name="q", value="hi")
    finding = await module.probe(point, Request.from_url("http://h/s?q=hi"), _StaticSender())
    assert finding is None


def test_module_metadata():
    assert BOOLEAN_SQLI_MODULE.name == "sqli-boolean"
    assert BOOLEAN_SQLI_MODULE.attack_type == AttackType.SQLI
    assert BOOLEAN_SQLI_MODULE.applies("param") is True
    assert BOOLEAN_SQLI_MODULE.applies("header") is False
