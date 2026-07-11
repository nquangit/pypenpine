from penpine.attack.analyze.analysis import Analysis
from penpine.attack.models import InjectionPoint


def points():
    return (
        InjectionPoint("param:id", "param", "id", "1", attack_types=("idor", "sqli")),
        InjectionPoint("param:q", "param", "q", "x", attack_types=("sqli", "xss")),
        InjectionPoint("header:Host", "header", "Host", "h", attack_types=("host-header",)),
    )


def test_for_attack():
    a = Analysis(request=object(), points=points())
    sqli = a.for_attack("sqli")
    assert len(sqli) == 2
    assert all("sqli" in p.attack_types for p in sqli)


def test_by_kind():
    a = Analysis(request=object(), points=points())
    grouped = a.by_kind()
    assert set(grouped) == {"param", "header"}
    assert len(grouped["param"]) == 2


def test_attack_types_union_all_len_iter():
    a = Analysis(request=object(), points=points())
    assert a.attack_types() == {"idor", "sqli", "xss", "host-header"}
    assert len(a.all()) == 3
    assert len(a) == 3
    assert [p.expr for p in a] == ["param:id", "param:q", "header:Host"]
