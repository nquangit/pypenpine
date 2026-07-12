from penpine.attack.generator import PayloadGenerator
from penpine.attack.models import Confidence, Finding, InjectionPoint, Payload, TestCase
from penpine.attack.module import AttackModule
from penpine.attack.types import AttackType
from penpine.attack.validator import Validator


class G(PayloadGenerator):
    def generate(self, point, request):
        yield TestCase(point=point, payload=Payload("X"), attack_type="t")


class V(Validator):
    def evaluate(self, test_case, response, baseline):
        return Finding(
            attack_type="t",
            point=test_case.point,
            payload=test_case.payload,
            confidence=Confidence.HIGH,
            evidence="hit",
        )


def test_module_delegates_generate_and_evaluate():
    m = AttackModule("t", G(), V())
    point = InjectionPoint("param:a", "param", "a", "1")
    cases = list(m.generate(point, object()))
    assert len(cases) == 1
    finding = m.evaluate(cases[0], object())
    assert finding.confidence == Confidence.HIGH


def test_applies_to_filter():
    m = AttackModule("t", G(), V(), applies_to=("param", "json"))
    assert m.applies("param") is True
    assert m.applies("header") is False
    assert AttackModule("u", G(), V()).applies("anything") is True


def test_metadata():
    m = AttackModule("t", G(), V(), applies_to=("param",), description="desc")
    assert m.name == "t"
    assert m.applies_to == ("param",)
    assert m.description == "desc"


def test_attack_type_defaults_to_none():
    assert AttackModule("t", G(), V()).attack_type is None


def test_attack_module_stores_attack_type():
    from penpine.attack.modules.sqli import SQLI_MODULE

    assert SQLI_MODULE.attack_type is AttackType.SQLI
