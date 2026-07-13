import pytest

from penpine.attack import registry
from penpine.attack.analyze.analyzer import analyze
from penpine.attack.example import EchoGenerator, EchoValidator
from penpine.attack.exceptions import AttackConfigError
from penpine.attack.generator import PayloadGenerator
from penpine.attack.models import InjectionPoint, Payload, TestCase
from penpine.attack.module import AttackModule
from penpine.attack.modules import register_builtins
from penpine.attack.modules.differential import BooleanSqliModule
from penpine.attack.modules.sqli import SQLI_MODULE
from penpine.attack.modules.xss import XSS_MODULE
from penpine.attack.runner import Runner
from penpine.attack.types import AttackType
from penpine.attack.validator import Validator
from penpine.core.message import Request
from tests.attack._fakes import FakeSender, reflect


@pytest.fixture(autouse=True)
def _clean_registry():
    registry.clear()
    yield
    registry.clear()


def xss_module():
    return AttackModule(
        "xss", EchoGenerator(), EchoValidator(), attack_type=AttackType.XSS, applies_to=("param",)
    )


async def test_happy_path_finds_reflection_on_tagged_point():
    registry.register(xss_module())
    runner = Runner(sender=FakeSender([reflect]))
    report = await runner.run(Request.from_url("http://h/?q=hi"), attack=AttackType.XSS)
    assert report.attack_type == AttackType.XSS
    assert report.baseline is not None
    assert report.findings
    assert all(a.test_case.point.expr == "param:q" for a in report.attempts)
    assert report.attempts[0].finding.confidence.name == "HIGH"


async def test_no_applicable_points_yields_empty_report():
    registry.register(xss_module())
    runner = Runner(sender=FakeSender([reflect]))
    report = await runner.run(Request.from_url("http://h/?id=7"), attack=AttackType.XSS)
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
        Request.from_url("http://h/?q=hi"), attack=AttackType.XSS
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
    # registry is empty (autouse fixture) -- no signature module of any category
    # is registered, so category resolution yields no modules either way.
    with pytest.raises(AttackConfigError):
        await Runner(sender=FakeSender([reflect])).run(
            Request.from_url("http://h/"), attack=AttackType.XSS
        )
    with pytest.raises(AttackConfigError):
        await Runner(sender=FakeSender([reflect])).run(Request.from_url("http://h/"))


async def test_run_by_category_uses_signature_module_not_differential():
    registry.clear()
    register_builtins()
    try:
        sender = FakeSender([b"HTTP/1.1 200 OK\r\nContent-Length: 8\r\n\r\nbaseline"])
        req = Request.from_url("http://t/item?q=hello")  # 'q' -> sqli candidate
        report = await Runner(sender=sender).run(req, attack=AttackType.SQLI)
        assert report.summary()["sent"] > 0
        # only the error-based signature module ran; no blind/differential probes
        techniques = {a.test_case.payload.technique for a in report}
        assert techniques == {"error-based"}
    finally:
        registry.clear()


async def test_run_accepts_a_module_class_and_instantiates_it():
    sender = FakeSender([b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nok"])
    req = Request.from_url("http://t/item?id=7")  # 'id' -> sqli candidate
    # pass the CLASS, not an instance -- the Runner must instantiate it (probe path)
    report = await Runner(sender=sender).run(req, module=BooleanSqliModule)
    assert report.summary()["sent"] == 1  # one point ('id') probed, ran without error
    assert report.attack_type is AttackType.SQLI


async def test_run_accepts_a_list_of_module_instances():
    sender = FakeSender([b"HTTP/1.1 200 OK\r\nContent-Length: 8\r\n\r\nbaseline"])
    req = Request.from_url("http://t/item?q=hello")  # 'q' -> sqli + xss candidate
    report = await Runner(sender=sender).run(req, module=[SQLI_MODULE, XSS_MODULE])
    techniques = {a.test_case.payload.technique for a in report}
    assert "error-based" in techniques  # sqli ran
    assert "reflected" in techniques  # xss ran
    assert report.attack_type is None  # heterogeneous -> None


async def test_run_accepts_a_list_of_attack_types():
    registry.clear()
    register_builtins()
    try:
        sender = FakeSender([b"HTTP/1.1 200 OK\r\nContent-Length: 8\r\n\r\nbaseline"])
        req = Request.from_url("http://t/item?q=hello")
        report = await Runner(sender=sender).run(req, attack=[AttackType.SQLI, AttackType.XSS])
        techniques = {a.test_case.payload.technique for a in report}
        assert {"error-based", "reflected"} <= techniques
        assert report.attack_type is None
    finally:
        registry.clear()


async def test_run_single_module_keeps_its_attack_type():
    sender = FakeSender([b"HTTP/1.1 200 OK\r\nContent-Length: 8\r\n\r\nbaseline"])
    req = Request.from_url("http://t/item?q=hello")
    report = await Runner(sender=sender).run(req, module=[SQLI_MODULE])  # list of one
    assert report.attack_type is AttackType.SQLI


async def test_run_bare_class_needing_args_raises_config_error():
    class _NeedsArg:
        def __init__(self, required):  # required constructor arg
            self.required = required

    with pytest.raises(AttackConfigError):
        await Runner().run(Request.from_url("http://t/x"), module=_NeedsArg)


async def test_run_does_not_mask_a_typeerror_from_module_init_body():
    class _BadInit:
        attack_type = AttackType.SQLI
        name = "bad"

        def __init__(self):
            raise TypeError("genuine bug in __init__")

        def applies(self, kind):
            return True

    with pytest.raises(TypeError, match="genuine bug"):
        await Runner().run(Request.from_url("http://t/x"), module=_BadInit)
