from penpine.attack.analyze.analyzer import analyze
from penpine.attack.analyze.rules import ClassificationRule
from penpine.attack.types import AttackType
from penpine.core.message import Request

CRAFTED = (
    b"POST /files/1?id=7&q=hello&next=http://e.com HTTP/1.1\r\n"
    b"Host: t.com\r\nUser-Agent: x\r\n"
    b"Content-Type: application/json\r\nContent-Length: 14\r\n\r\n"
    b'{"name":"ann"}'
)


def _find(analysis, expr):
    return next(p for p in analysis.points if p.expr == expr)


def test_analyze_tags_points_by_kind_name_and_value():
    a = analyze(Request.from_raw(CRAFTED))
    assert {AttackType.IDOR, AttackType.SQLI} <= set(_find(a, "param:id").attack_types)
    assert AttackType.XSS in _find(a, "param:q").attack_types
    assert {AttackType.OPEN_REDIRECT, AttackType.SSRF} <= set(_find(a, "param:next").attack_types)
    assert AttackType.HOST_HEADER in _find(a, "header:Host").attack_types
    assert AttackType.HEADER_INJECTION in _find(a, "header:User-Agent").attack_types
    assert AttackType.PATH_TRAVERSAL in _find(a, "path-seg:1").attack_types
    assert {AttackType.SQLI, AttackType.XSS} <= set(_find(a, "json:$.name").attack_types)


def test_for_attack_selects_points():
    a = analyze(Request.from_raw(CRAFTED))
    sqli_exprs = {p.expr for p in a.for_attack(AttackType.SQLI)}
    assert "param:id" in sqli_exprs and "json:$.name" in sqli_exprs
    assert "header:Host" not in sqli_exprs


def test_kinds_filter_passes_through():
    a = analyze(Request.from_url("http://h/?a=1"), kinds={"param"})
    assert {p.kind for p in a.points} == {"param"}


def test_empty_rules_yields_no_tags():
    a = analyze(Request.from_url("http://h/?id=1"), rules=[])
    assert a.points
    assert all(p.attack_types == () for p in a.points)


def test_custom_rule_applied():
    class Tagger(ClassificationRule):
        name = "tagger"

        def match(self, point):
            return {AttackType.BROKEN_ACCESS} if point.kind == "param" else set()

    a = analyze(Request.from_url("http://h/?a=1"), rules=[Tagger()])
    assert AttackType.BROKEN_ACCESS in next(p for p in a.points if p.expr == "param:a").attack_types


def test_attack_types_sorted_for_determinism():
    a = analyze(Request.from_url("http://h/?id=1"))
    tags = _find(a, "param:id").attack_types
    assert list(tags) == sorted(tags, key=lambda t: t.value)


def test_analyze_tags_points_with_attacktype_enum():
    analysis = analyze(Request.from_url("http://t/p?id=7&q=hi&next=http://e.com"))
    tags = analysis.attack_types()
    assert AttackType.SQLI in tags
    assert all(isinstance(t, AttackType) for p in analysis for t in p.attack_types)
    ids = analysis.for_attack(AttackType.SQLI)
    assert any(p.name == "id" for p in ids)
