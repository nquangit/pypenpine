import pytest

from penpine.attack.exceptions import AttackConfigError
from penpine.attack.types import AttackType


def test_members_cover_all_rule_tags_plus_broken_access():
    expected = {
        "sqli",
        "xss",
        "idor",
        "ssrf",
        "open-redirect",
        "path-traversal",
        "lfi",
        "host-header",
        "header-injection",
        "broken-access",
    }
    assert {t.value for t in AttackType} == expected


def test_from_str_roundtrips():
    for t in AttackType:
        assert AttackType.from_str(t.value) is t


def test_from_str_unknown_raises():
    with pytest.raises(AttackConfigError):
        AttackType.from_str("nope")


def test_values_are_sortable_for_deterministic_tagging():
    # analyzer sorts tags by value for stable output
    ordered = sorted(AttackType, key=lambda t: t.value)
    assert [t.value for t in ordered] == sorted(t.value for t in AttackType)
