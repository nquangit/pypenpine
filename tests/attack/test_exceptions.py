from penpine.attack.exceptions import AttackConfigError, AttackError
from penpine.exceptions import PenpineError


def test_hierarchy():
    assert issubclass(AttackConfigError, AttackError)
    assert issubclass(AttackError, PenpineError)
