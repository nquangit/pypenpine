from penpine.core.parse.http_parser import parse_response
from penpine.attack.models import InjectionPoint
from penpine.attack.modules.redirect import (
    RedirectGenerator, RedirectValidator, REDIRECT_PAYLOADS, CANARY_HOST, REDIRECT_MODULE,
)


def pt():
    return InjectionPoint("param:next", "param", "next", "x")


def test_generator_uses_canary_host():
    cases = list(RedirectGenerator().generate(pt(), None))
    assert [c.payload.value for c in cases] == REDIRECT_PAYLOADS
    assert all(CANARY_HOST in c.payload.value for c in cases)
    assert all(c.attack_type == "open-redirect" for c in cases)


def test_validator_detects_redirect_to_canary():
    tc = next(iter(RedirectGenerator().generate(pt(), None)))
    resp = parse_response(
        b"HTTP/1.1 302 Found\r\nLocation: https://penpine-canary.example/x\r\n"
        b"Content-Length: 0\r\n\r\n")
    f = RedirectValidator().evaluate(tc, resp, None)
    assert f is not None and f.attack_type == "open-redirect" and f.confidence.name == "HIGH"


def test_validator_non_redirect_or_other_host_returns_none():
    tc = next(iter(RedirectGenerator().generate(pt(), None)))
    ok = parse_response(b"HTTP/1.1 200 OK\r\nContent-Length: 0\r\n\r\n")
    assert RedirectValidator().evaluate(tc, ok, None) is None
    other = parse_response(
        b"HTTP/1.1 302 Found\r\nLocation: https://legit.example/\r\nContent-Length: 0\r\n\r\n")
    assert RedirectValidator().evaluate(tc, other, None) is None


def test_module_metadata():
    assert REDIRECT_MODULE.name == "open-redirect" and REDIRECT_MODULE.applies("param")
