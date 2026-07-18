from penpine.attack.models import InjectionPoint
from penpine.attack.modules.fuzz import FUZZ_PAYLOADS, FuzzGenerator, FuzzValidator
from penpine.attack.types import AttackType
from penpine.core.parse.http_parser import parse_response


def pt(value="hi"):
    return InjectionPoint("param:x", "param", "x", value)


def resp(body=b"ok", status=200):
    line = {200: b"200 OK", 500: b"500 Internal Server Error", 404: b"404 Not Found"}[status]
    return parse_response(
        b"HTTP/1.1 " + line + b"\r\nContent-Length: %d\r\n\r\n%s" % (len(body), body)
    )


def test_generator_yields_all_fuzz_payloads():
    tcs = list(FuzzGenerator().generate(pt(), None))
    assert [c.payload.value for c in tcs] == FUZZ_PAYLOADS
    assert all(c.attack_type == AttackType.FUZZ for c in tcs)


def test_validator_flags_5xx_high():
    tc = next(iter(FuzzGenerator().generate(pt(), None)))
    f = FuzzValidator().evaluate(tc, resp(status=500), baseline=resp(status=200))
    assert f is not None and f.confidence.name == "HIGH" and f.attack_type == AttackType.FUZZ


def test_validator_flags_error_signature_high():
    tc = next(iter(FuzzGenerator().generate(pt(), None)))
    f = FuzzValidator().evaluate(
        tc, resp(b"Traceback (most recent call last):"), baseline=resp(b"ok")
    )
    assert f is not None and f.confidence.name == "HIGH"


def test_validator_flags_status_change_medium():
    tc = next(iter(FuzzGenerator().generate(pt(), None)))
    f = FuzzValidator().evaluate(tc, resp(status=404), baseline=resp(status=200))
    assert f is not None and f.confidence.name == "MEDIUM"


def test_validator_suppresses_when_baseline_also_5xx():
    tc = next(iter(FuzzGenerator().generate(pt(), None)))
    assert FuzzValidator().evaluate(tc, resp(status=500), baseline=resp(status=500)) is None


def test_validator_benign_returns_none():
    tc = next(iter(FuzzGenerator().generate(pt(), None)))
    assert FuzzValidator().evaluate(tc, resp(b"ok"), baseline=resp(b"ok")) is None


async def test_fuzz_runs_end_to_end_and_finds_error():
    from penpine.attack import registry
    from penpine.attack.modules import register_builtins
    from penpine.attack.runner import Runner
    from penpine.core.message import Request
    from tests.attack._fakes import FakeSender

    registry.clear()
    register_builtins()
    try:
        # baseline 200, then every fuzz payload gets a 500
        script = [
            b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nok",
            b"HTTP/1.1 500 Internal Server Error\r\nContent-Length: 3\r\n\r\nerr",
        ]
        report = await Runner(sender=FakeSender(script)).run(
            Request.from_url("http://h/?q=hi"), attack=AttackType.FUZZ
        )
        assert report.findings
    finally:
        registry.clear()
