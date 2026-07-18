from penpine.attack.models import InjectionPoint
from penpine.attack.modules.ssrf import SsrfGenerator, SsrfValidator
from penpine.attack.types import AttackType
from penpine.core.parse.http_parser import parse_response


def pt(value="http://example.com"):
    return InjectionPoint("param:url", "param", "url", value)


def resp(body):
    return parse_response(b"HTTP/1.1 200 OK\r\nContent-Length: %d\r\n\r\n%s" % (len(body), body))


def test_generator_yields_metadata_and_file_targets():
    values = [c.payload.value for c in SsrfGenerator().generate(pt(), None)]
    assert any("169.254.169.254" in v for v in values)
    assert any(v.startswith("file://") for v in values)
    assert all(c.attack_type == AttackType.SSRF for c in [*SsrfGenerator().generate(pt(), None)])


def test_validator_detects_metadata_signature_medium():
    tc = next(iter(SsrfGenerator().generate(pt(), None)))
    body = b'{"ami-id":"ami-123","instance-id":"i-1"}'
    f = SsrfValidator().evaluate(tc, resp(body), baseline=resp(b"ok"))
    assert f is not None and f.confidence.name == "MEDIUM" and f.attack_type == AttackType.SSRF


def test_validator_detects_passwd_file_read():
    tc = next(iter(SsrfGenerator().generate(pt(), None)))
    f = SsrfValidator().evaluate(tc, resp(b"root:x:0:0:root:/root:/bin/bash"), baseline=resp(b"ok"))
    assert f is not None and f.attack_type == AttackType.SSRF


def test_validator_suppresses_signature_in_baseline():
    tc = next(iter(SsrfGenerator().generate(pt(), None)))
    b = resp(b"root:x:0:0:root:/root:/bin/bash")
    assert SsrfValidator().evaluate(tc, b, baseline=b) is None


def test_validator_benign_returns_none():
    tc = next(iter(SsrfGenerator().generate(pt(), None)))
    assert SsrfValidator().evaluate(tc, resp(b"ok"), baseline=resp(b"ok")) is None


async def test_ssrf_runs_end_to_end_and_finds_metadata():
    from penpine.attack import registry
    from penpine.attack.modules import register_builtins
    from penpine.attack.runner import Runner
    from penpine.core.message import Request
    from tests.attack._fakes import FakeSender

    registry.clear()
    register_builtins()
    try:
        metadata_body = b'{"ami-id":"ami-1","instance-id":"i-1"}'
        script = [
            b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nok",
            b"HTTP/1.1 200 OK\r\nContent-Length: %d\r\n\r\n%s"
            % (len(metadata_body), metadata_body),
        ]
        report = await Runner(sender=FakeSender(script)).run(
            Request.from_url("http://h/?url=http://x"), attack=AttackType.SSRF
        )
        assert report.findings
    finally:
        registry.clear()
