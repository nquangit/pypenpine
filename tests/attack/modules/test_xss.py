from penpine.attack.models import InjectionPoint
from penpine.attack.modules.xss import (
    XSS_MODULE,
    XSS_PAYLOAD_TEMPLATES,
    XssGenerator,
    XssValidator,
)
from penpine.attack.types import AttackType
from penpine.core.parse.http_parser import parse_response


def pt():
    return InjectionPoint("param:x", "param", "x", "v")


def resp(body):
    return parse_response(b"HTTP/1.1 200 OK\r\nContent-Length: %d\r\n\r\n%s" % (len(body), body))


def test_generator_unique_markers_embedded():
    cases = list(XssGenerator().generate(pt(), None))
    assert len(cases) == len(XSS_PAYLOAD_TEMPLATES)
    markers = [c.marker for c in cases]
    assert all(m and m.startswith("PXSS_") for m in markers)
    assert len(set(markers)) == len(markers)
    assert all(c.marker in c.payload.value for c in cases)
    assert all(c.attack_type == AttackType.XSS for c in cases)


def test_validator_detects_verbatim_reflection():
    tc = next(iter(XssGenerator().generate(pt(), None)))
    f = XssValidator().evaluate(tc, resp(tc.payload.value.encode()), None)
    assert f is not None and f.attack_type == AttackType.XSS and f.confidence.name == "HIGH"


def test_validator_escaped_reflection_returns_none():
    tc = next(iter(XssGenerator().generate(pt(), None)))
    escaped = tc.payload.value.replace("<", "&lt;").replace(">", "&gt;").encode()
    assert XssValidator().evaluate(tc, resp(escaped), None) is None


def test_module_metadata():
    assert XSS_MODULE.name == "xss" and XSS_MODULE.applies("param")
