from penpine.core.parse.http_parser import parse_response
from penpine.attack.models import InjectionPoint
from penpine.attack.modules.traversal import (
    TraversalGenerator, TraversalValidator, TRAVERSAL_PAYLOADS, TRAVERSAL_MODULE,
)


def pt():
    return InjectionPoint("param:file", "param", "file", "x")


def resp(body):
    return parse_response(b"HTTP/1.1 200 OK\r\nContent-Length: %d\r\n\r\n%s" % (len(body), body))


def test_generator_yields_payloads():
    cases = list(TraversalGenerator().generate(pt(), None))
    assert [c.payload.value for c in cases] == TRAVERSAL_PAYLOADS
    assert all(c.attack_type == "path-traversal" for c in cases)


def test_validator_detects_passwd():
    tc = next(iter(TraversalGenerator().generate(pt(), None)))
    f = TraversalValidator().evaluate(tc, resp(b"root:x:0:0:root:/root:/bin/bash"), None)
    assert f is not None and f.confidence.name == "HIGH"


def test_validator_detects_win_ini():
    tc = next(iter(TraversalGenerator().generate(pt(), None)))
    assert TraversalValidator().evaluate(tc, resp(b"[extensions]\r\nfoo=bar"), None) is not None


def test_validator_clean_and_baseline_guard():
    tc = next(iter(TraversalGenerator().generate(pt(), None)))
    assert TraversalValidator().evaluate(tc, resp(b"hello"), None) is None
    passwd = resp(b"root:x:0:0:root:/root:/bin/bash")
    assert TraversalValidator().evaluate(tc, passwd, passwd) is None


def test_module_metadata():
    assert TRAVERSAL_MODULE.name == "path-traversal"
    assert TRAVERSAL_MODULE.applies("path-seg")


def test_module_applies_to_multipart():
    assert TRAVERSAL_MODULE.applies("multipart")
