from penpine.attack.models import InjectionPoint
from penpine.attack.modules.ssti import SstiGenerator, SstiValidator
from penpine.attack.types import AttackType
from penpine.core.parse.http_parser import parse_response


def pt(value="hi"):
    return InjectionPoint("param:x", "param", "x", value)


def resp(body):
    return parse_response(b"HTTP/1.1 200 OK\r\nContent-Length: %d\r\n\r\n%s" % (len(body), body))


def test_generator_embeds_product_and_expression_in_meta():
    tcs = list(SstiGenerator().generate(pt(), None))
    assert tcs and all(c.attack_type == AttackType.SSTI for c in tcs)
    tc = tcs[0]
    assert "product" in tc.payload.meta and "expr" in tc.payload.meta
    assert str(tc.payload.meta["product"]) not in tc.payload.value  # the literal isn't the product


def test_validator_detects_evaluated_product():
    tc = next(iter(SstiGenerator().generate(pt(), None)))
    product = tc.payload.meta["product"]
    f = SstiValidator().evaluate(tc, resp(f"result: {product} done".encode()), None)
    assert f is not None and f.confidence.name == "HIGH" and f.attack_type == AttackType.SSTI


def test_validator_ignores_reflected_expression_without_eval():
    tc = next(iter(SstiGenerator().generate(pt(), None)))
    # the raw expression echoed back (not evaluated) -> not a finding
    assert SstiValidator().evaluate(tc, resp(tc.payload.value.encode()), None) is None


def test_validator_benign_returns_none():
    tc = next(iter(SstiGenerator().generate(pt(), None)))
    assert SstiValidator().evaluate(tc, resp(b"nothing here"), None) is None


async def test_ssti_runs_end_to_end():
    # a,b are random per-payload, so a static FakeSender can't reflect the exact
    # product; assert the run completes and sends payloads (true-positive detection
    # is covered by test_validator_detects_evaluated_product above).
    from penpine.attack import registry
    from penpine.attack.modules import register_builtins
    from penpine.attack.runner import Runner
    from penpine.core.message import Request
    from tests.attack._fakes import FakeSender

    registry.clear()
    register_builtins()
    try:
        sender = FakeSender([b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nok"])
        report = await Runner(sender=sender).run(
            Request.from_url("http://h/?q=hi"), attack=AttackType.SSTI
        )
        assert report.summary()["sent"] > 0
    finally:
        registry.clear()
