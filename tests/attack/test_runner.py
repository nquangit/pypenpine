import pytest

from penpine.attack import registry
from penpine.attack.analyze.analyzer import analyze
from penpine.attack.example import EchoGenerator, EchoValidator
from penpine.attack.exceptions import AttackConfigError
from penpine.attack.generator import PayloadGenerator
from penpine.attack.models import InjectionPoint, Payload, TestCase
from penpine.attack.module import AttackModule
from penpine.attack.runner import Runner
from penpine.attack.validator import Validator
from penpine.core.message import Request
from tests.attack._fakes import FakeSender, reflect


@pytest.fixture(autouse=True)
def _clean_registry():
    registry.clear()
    yield
    registry.clear()


def xss_module():
    return AttackModule("xss", EchoGenerator(), EchoValidator(), applies_to=("param",))


async def test_happy_path_finds_reflection_on_tagged_point():
    registry.register(xss_module())
    runner = Runner(sender=FakeSender([reflect]))
    report = await runner.run(Request.from_url("http://h/?q=hi"), attack="xss")
    assert report.attack_type == "xss"
    assert report.baseline is not None
    assert report.findings
    assert all(a.test_case.point.expr == "param:q" for a in report.attempts)
    assert report.attempts[0].finding.confidence.name == "HIGH"


async def test_no_applicable_points_yields_empty_report():
    registry.register(xss_module())
    runner = Runner(sender=FakeSender([reflect]))
    report = await runner.run(Request.from_url("http://h/?id=7"), attack="xss")
    assert len(report) == 0
    assert report.findings == []


async def test_points_override_attacks_untagged_points():
    req = Request.from_url("http://h/?id=7")
    runner = Runner(sender=FakeSender([reflect]))
    report = await runner.run(req, module=xss_module(), points=analyze(req).all())
    assert report.attempts


async def test_bring_your_own_test_cases_without_validator():
    req = Request.from_url("http://h/?a=1")
    point = InjectionPoint.from_locator(req.locate("param:a"))
    tc = TestCase(point=point, payload=Payload("X"), attack_type="custom")
    runner = Runner(sender=FakeSender([reflect]))
    report = await runner.run(req, test_cases=[tc])
    assert len(report) == 1
    assert report.attempts[0].finding is None
    assert report.attempts[0].response is not None
    assert b"a=X" in report.attempts[0].request.serialize()


async def test_error_isolation_records_errors_and_completes():
    registry.register(xss_module())

    class FailingSender:
        async def send(self, request):
            raise RuntimeError("net down")

    report = await Runner(sender=FailingSender()).run(
        Request.from_url("http://h/?q=hi"), attack="xss"
    )
    assert report.baseline is None
    assert len(report) == 1
    assert report.attempts[0].error is not None
    assert report.summary()["failed"] == 1
    assert report.findings == []


async def test_baseline_passed_to_validator():
    captured = {}

    class G(PayloadGenerator):
        def generate(self, point, request):
            yield TestCase(point=point, payload=Payload("X"), attack_type="probe")

    class V(Validator):
        def evaluate(self, test_case, response, baseline):
            captured["baseline"] = baseline
            return None

    req = Request.from_url("http://h/?a=1")
    module = AttackModule("probe", G(), V(), applies_to=("param",))
    await Runner(sender=FakeSender([reflect])).run(req, module=module, points=analyze(req).all())
    assert captured["baseline"] is not None


async def test_unknown_attack_and_no_selector_raise():
    with pytest.raises(AttackConfigError):
        await Runner(sender=FakeSender([reflect])).run(Request.from_url("http://h/"), attack="nope")
    with pytest.raises(AttackConfigError):
        await Runner(sender=FakeSender([reflect])).run(Request.from_url("http://h/"))
