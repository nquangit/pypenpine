import pytest

from penpine.core.message import Request
from penpine.core.parse.http_parser import parse_response
from penpine.attack import registry
from penpine.attack.example import EchoGenerator, EchoValidator, ECHO_MODULE
from penpine.attack.models import InjectionPoint


@pytest.fixture(autouse=True)
def _clean_registry():
    registry.clear()
    yield
    registry.clear()


def point():
    loc = Request.from_url("http://h/p?a=1").locate("param:a")
    return InjectionPoint.from_locator(loc)


def test_generator_yields_marked_testcase():
    cases = list(EchoGenerator().generate(point(), object()))
    assert len(cases) == 1
    tc = cases[0]
    assert tc.attack_type == "echo"
    assert tc.marker and tc.marker == tc.payload.value
    assert tc.marker.startswith("PENPINE_ECHO_")


def test_validator_detects_reflection():
    cases = list(EchoGenerator().generate(point(), object()))
    tc = cases[0]
    reflecting = parse_response(
        b"HTTP/1.1 200 OK\r\nContent-Length: %d\r\n\r\n%s"
        % (len(tc.marker), tc.marker.encode()))
    finding = EchoValidator().evaluate(tc, reflecting, None)
    assert finding is not None
    assert finding.attack_type == "echo"
    assert finding.confidence.name == "HIGH"
    assert finding.response is reflecting


def test_validator_no_reflection_returns_none():
    cases = list(EchoGenerator().generate(point(), object()))
    not_reflecting = parse_response(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nok")
    assert EchoValidator().evaluate(cases[0], not_reflecting, None) is None


def test_echo_module_round_trip_via_registry():
    registry.register(ECHO_MODULE)
    m = registry.get("echo")
    assert m.applies("param") is True
    tc = list(m.generate(point(), object()))[0]
    reflecting = parse_response(
        b"HTTP/1.1 200 OK\r\nContent-Length: %d\r\n\r\n%s"
        % (len(tc.marker), tc.marker.encode()))
    assert m.evaluate(tc, reflecting) is not None
