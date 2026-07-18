from penpine.attack.models import InjectionPoint
from penpine.attack.modules.cmdi import CmdiGenerator, CmdiValidator
from penpine.attack.types import AttackType
from penpine.core.parse.http_parser import parse_response


def pt(value="hi"):
    return InjectionPoint("param:x", "param", "x", value)


def resp(body):
    return parse_response(b"HTTP/1.1 200 OK\r\nContent-Length: %d\r\n\r\n%s" % (len(body), body))


def test_generator_marks_payloads():
    tcs = list(CmdiGenerator().generate(pt(), None))
    assert tcs and all(c.attack_type == AttackType.CMDI and "marker" in c.payload.meta for c in tcs)


def test_validator_detects_command_output_reflection():
    tc = next(iter(CmdiGenerator().generate(pt(), None)))
    m = tc.payload.meta["marker"]
    # command output (the bare marker) reflected, NOT the literal payload
    f = CmdiValidator().evaluate(tc, resp(f"output {m} end".encode()), None)
    assert f is not None and f.confidence.name == "HIGH" and f.attack_type == AttackType.CMDI


def test_validator_ignores_literal_payload_echo():
    tc = next(iter(CmdiGenerator().generate(pt(), None)))
    assert CmdiValidator().evaluate(tc, resp(tc.payload.value.encode()), None) is None


def test_validator_benign_returns_none():
    tc = next(iter(CmdiGenerator().generate(pt(), None)))
    assert CmdiValidator().evaluate(tc, resp(b"ok"), None) is None


async def test_cmdi_runs_end_to_end_and_finds_injection():
    import re

    from penpine.attack import registry
    from penpine.attack.modules import register_builtins
    from penpine.attack.runner import Runner
    from penpine.core.message import Request
    from tests.attack._fakes import FakeSender

    marker_re = re.compile(rb"cmdi_[0-9a-fA-F]+")

    def reflect_marker_in_body(request):
        raw = request.serialize()
        match = marker_re.search(raw)
        body = match.group(0) if match else b"ok"
        return b"HTTP/1.1 200 OK\r\nContent-Length: %d\r\n\r\n%s" % (len(body), body)

    registry.clear()
    register_builtins()
    try:
        sender = FakeSender([reflect_marker_in_body])
        report = await Runner(sender=sender).run(
            Request.from_url("http://h/?q=hi"), attack=AttackType.CMDI
        )
        assert report.findings
    finally:
        registry.clear()
