import pytest

from penpine.attack import registry
from penpine.attack.exceptions import AttackConfigError
from penpine.attack.generator import PayloadGenerator
from penpine.attack.module import AttackModule
from penpine.attack.modules import register_builtins
from penpine.attack.types import AttackType
from penpine.attack.validator import Validator


class G(PayloadGenerator):
    def generate(self, point, request):
        return []


class V(Validator):
    def evaluate(self, test_case, response, baseline):
        return None


@pytest.fixture(autouse=True)
def _clean_registry():
    registry.clear()
    yield
    registry.clear()


def module(name):
    return AttackModule(name, G(), V())


def test_register_and_get():
    m = module("sqli")
    registry.register(m)
    assert registry.get("sqli") is m


def test_get_unknown_raises():
    with pytest.raises(AttackConfigError):
        registry.get("nope")


def test_duplicate_raises_unless_replace():
    registry.register(module("sqli"))
    with pytest.raises(AttackConfigError):
        registry.register(module("sqli"))
    replacement = module("sqli")
    registry.register(replacement, replace=True)
    assert registry.get("sqli") is replacement


def test_list_and_unregister_and_clear():
    registry.register(module("a"))
    registry.register(module("b"))
    assert registry.list_modules() == ["a", "b"]
    registry.unregister("a")
    assert registry.list_modules() == ["b"]
    registry.clear()
    assert registry.list_modules() == []


def test_by_type_signature_only_excludes_probe_modules():
    registry.clear()
    register_builtins()
    sig = registry.by_type(AttackType.SQLI, signature_only=True)
    assert [m.name for m in sig] == ["sqli"]  # only the error-based module
    allsqli = {m.name for m in registry.by_type(AttackType.SQLI)}
    assert {"sqli", "sqli-boolean", "sqli-time"} <= allsqli
    registry.clear()
