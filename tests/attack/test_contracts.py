import pytest

from penpine.attack.generator import PayloadGenerator
from penpine.attack.validator import Validator
from penpine.attack.models import InjectionPoint, Payload, TestCase, Finding, Confidence


def test_abcs_cannot_be_instantiated():
    with pytest.raises(TypeError):
        PayloadGenerator()
    with pytest.raises(TypeError):
        Validator()


def test_concrete_generator_and_validator_work():
    point = InjectionPoint("param:a", "param", "a", "1")

    class G(PayloadGenerator):
        def generate(self, point, request):
            yield TestCase(point=point, payload=Payload("X"), attack_type="t")

    class V(Validator):
        def evaluate(self, test_case, response, baseline):
            return Finding(attack_type="t", point=test_case.point,
                           payload=test_case.payload, confidence=Confidence.LOW,
                           evidence="ok")

    cases = list(G().generate(point, object()))
    assert len(cases) == 1 and cases[0].attack_type == "t"
    finding = V().evaluate(cases[0], object(), None)
    assert finding.confidence == Confidence.LOW
