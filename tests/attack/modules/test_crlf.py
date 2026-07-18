from penpine.attack.models import InjectionPoint
from penpine.attack.modules.crlf import INJECTED_HEADER, CrlfGenerator, CrlfValidator
from penpine.attack.types import AttackType
from penpine.core.parse.http_parser import parse_response


def pt(value="hi"):
    return InjectionPoint("param:x", "param", "x", value)


def test_generator_marks_payloads_with_marker():
    tcs = list(CrlfGenerator().generate(pt(), None))
    assert tcs and all(c.attack_type == AttackType.CRLF for c in tcs)
    assert all("marker" in c.payload.meta for c in tcs)


def test_validator_detects_injected_response_header():
    tc = next(iter(CrlfGenerator().generate(pt(), None)))
    m = tc.payload.meta["marker"]
    raw = b"HTTP/1.1 200 OK\r\n%s: %s\r\nContent-Length: 0\r\n\r\n" % (
        INJECTED_HEADER.encode(),
        m.encode(),
    )
    f = CrlfValidator().evaluate(tc, parse_response(raw), None)
    assert f is not None and f.confidence.name == "HIGH" and f.attack_type == AttackType.CRLF


def test_validator_no_injection_returns_none():
    tc = next(iter(CrlfGenerator().generate(pt(), None)))
    clean = parse_response(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nok")
    assert CrlfValidator().evaluate(tc, clean, None) is None


async def test_crlf_runs_end_to_end_and_finds_injection():
    import re

    from penpine.attack import registry
    from penpine.attack.modules import register_builtins
    from penpine.attack.runner import Runner
    from penpine.core.message import Request
    from tests.attack._fakes import FakeSender

    marker_re = re.compile(rb"crlfpp_[0-9a-fA-F]+")

    def reflect_marker_as_header(request):
        raw = request.serialize()
        match = marker_re.search(raw)
        body = b"ok"
        header = b"%s: %s\r\n" % (INJECTED_HEADER.encode(), match.group(0)) if match else b""
        return (
            b"HTTP/1.1 200 OK\r\n"
            + header
            + b"Content-Length: %d\r\n\r\n%s"
            % (
                len(body),
                body,
            )
        )

    registry.clear()
    register_builtins()
    try:
        sender = FakeSender([reflect_marker_as_header])
        report = await Runner(sender=sender).run(
            Request.from_url("http://h/?q=hi"), attack=AttackType.CRLF
        )
        assert report.findings
    finally:
        registry.clear()
