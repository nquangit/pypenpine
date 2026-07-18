from penpine.attack.models import InjectionPoint
from penpine.attack.modules.nosqli import NosqliGenerator, NosqliValidator
from penpine.attack.types import AttackType
from penpine.core.parse.http_parser import parse_response


def pt(value="admin"):
    return InjectionPoint("param:user", "param", "user", value)


def resp(body, status=200):
    line = b"200 OK" if status == 200 else b"500 Internal Server Error"
    return parse_response(
        b"HTTP/1.1 " + line + b"\r\nContent-Length: %d\r\n\r\n%s" % (len(body), body)
    )


def test_generator_yields_operator_payloads():
    tcs = list(NosqliGenerator().generate(pt(), None))
    assert tcs and all(c.attack_type == AttackType.NOSQLI for c in tcs)
    assert any("$ne" in c.payload.value for c in tcs)


def test_validator_detects_nosql_error_high():
    tc = next(iter(NosqliGenerator().generate(pt(), None)))
    f = NosqliValidator().evaluate(
        tc, resp(b"MongoError: E11000 duplicate key"), baseline=resp(b"ok")
    )
    assert f is not None and f.confidence.name == "HIGH" and f.attack_type == AttackType.NOSQLI


def test_validator_flags_status_change_medium():
    tc = next(iter(NosqliGenerator().generate(pt(), None)))
    f = NosqliValidator().evaluate(tc, resp(b"boom", status=500), baseline=resp(b"ok"))
    assert f is not None and f.confidence.name == "MEDIUM"


def test_validator_benign_returns_none():
    tc = next(iter(NosqliGenerator().generate(pt(), None)))
    assert NosqliValidator().evaluate(tc, resp(b"ok"), baseline=resp(b"ok")) is None


def test_validator_suppresses_signature_in_baseline():
    tc = next(iter(NosqliGenerator().generate(pt(), None)))
    b = resp(b"MongoError: E11000 duplicate key")
    assert NosqliValidator().evaluate(tc, b, baseline=b) is None


async def test_nosqli_runs_end_to_end_and_finds_injection():
    from penpine.attack import registry
    from penpine.attack.modules import register_builtins
    from penpine.attack.runner import Runner
    from penpine.core.message import Request
    from tests.attack._fakes import FakeSender

    registry.clear()
    register_builtins()
    try:
        error_body = b"MongoError: E11000 duplicate key"
        script = [
            b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nok",
            b"HTTP/1.1 200 OK\r\nContent-Length: %d\r\n\r\n%s" % (len(error_body), error_body),
        ]
        report = await Runner(sender=FakeSender(script)).run(
            Request.from_url("http://h/?user=admin"), attack=AttackType.NOSQLI
        )
        assert report.findings
    finally:
        registry.clear()
