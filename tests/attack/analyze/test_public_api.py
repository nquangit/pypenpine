import penpine.attack as attack
from penpine.attack.analyze import (
    DEFAULT_RULES,
    Analysis,
    ClassificationRule,
    analyze,
    detectors,
)


def test_analyze_package_exports():
    assert callable(analyze)
    assert Analysis and ClassificationRule and DEFAULT_RULES
    assert hasattr(detectors, "is_url")


def test_attack_reexports_analyze():
    assert attack.analyze is analyze
    assert attack.Analysis is Analysis
