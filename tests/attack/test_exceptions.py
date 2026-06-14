from penpine.exceptions import PenpineError
from penpine.attack.exceptions import AttackError, AttackConfigError


def test_hierarchy():
    assert issubclass(AttackConfigError, AttackError)
    assert issubclass(AttackError, PenpineError)
