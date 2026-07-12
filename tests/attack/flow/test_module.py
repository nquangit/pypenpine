import pytest

from penpine.attack.flow.module import FlowAttackModule, FlowVariant
from penpine.attack.types import AttackType


def test_flow_variant_defaults():
    v = FlowVariant(flow="F", target="drop:login")
    assert v.flow == "F"
    assert v.target == "drop:login"
    assert v.meta == {}


def test_flow_attack_module_is_abstract():
    with pytest.raises(TypeError):
        FlowAttackModule()  # abstract mutate/validate


def test_concrete_subclass_instantiates():
    class M(FlowAttackModule):
        attack_type = AttackType.BROKEN_ACCESS
        name = "m"

        def mutate(self, base_flow, baseline_result, targets):
            return []

        def validate(self, variant, variant_result, baseline_result):
            return None

    m = M()
    assert m.attack_type is AttackType.BROKEN_ACCESS
    assert list(m.mutate(None, None, None)) == []
