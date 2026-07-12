from penpine.attack.analyze.rules import (
    DEFAULT_RULES,
    ClassificationRule,
    FileNameOrPathRule,
    HostHeaderRule,
    IdentifierNameRule,
    NumericValueRule,
    PathSegmentRule,
    ProxyHeaderRule,
    RedirectNameRule,
    SearchNameRule,
    StringContextRule,
    UrlValueRule,
)
from penpine.attack.models import InjectionPoint
from penpine.attack.types import AttackType


def pt(kind, name, value):
    expr = kind if kind in ("method", "target", "version") else f"{kind}:{name}"
    return InjectionPoint(expr=expr, kind=kind, name=name, value=value)


def test_string_context_rule():
    assert StringContextRule().match(pt("param", "x", "hello")) == {
        AttackType.SQLI,
        AttackType.XSS,
    }
    assert StringContextRule().match(pt("param", "x", "12")) == set()
    assert StringContextRule().match(pt("header", "x", "hello")) == set()


def test_numeric_value_rule():
    assert NumericValueRule().match(pt("param", "x", "12")) == {
        AttackType.SQLI,
        AttackType.IDOR,
    }
    assert NumericValueRule().match(pt("param", "x", "hello")) == set()


def test_identifier_name_rule():
    assert IdentifierNameRule().match(pt("param", "id", "1")) == {
        AttackType.IDOR,
        AttackType.SQLI,
    }
    assert IdentifierNameRule().match(pt("param", "user_id", "1")) == {
        AttackType.IDOR,
        AttackType.SQLI,
    }
    assert IdentifierNameRule().match(pt("param", "valid", "1")) == set()


def test_url_and_redirect_rules():
    assert UrlValueRule().match(pt("param", "x", "http://e.com")) == {
        AttackType.SSRF,
        AttackType.OPEN_REDIRECT,
    }
    assert UrlValueRule().match(pt("param", "x", "plain")) == set()
    assert RedirectNameRule().match(pt("param", "next", "x")) == {
        AttackType.OPEN_REDIRECT,
        AttackType.SSRF,
    }
    assert RedirectNameRule().match(pt("param", "other", "x")) == set()


def test_file_path_and_segment_rules():
    assert FileNameOrPathRule().match(pt("param", "x", "../e")) == {
        AttackType.PATH_TRAVERSAL,
        AttackType.LFI,
    }
    assert FileNameOrPathRule().match(pt("param", "file", "x")) == {
        AttackType.PATH_TRAVERSAL,
        AttackType.LFI,
    }
    assert FileNameOrPathRule().match(pt("param", "x", "plain")) == set()
    assert PathSegmentRule().match(pt("path-seg", "1", "1")) == {
        AttackType.PATH_TRAVERSAL,
        AttackType.IDOR,
    }
    assert PathSegmentRule().match(pt("param", "x", "1")) == set()


def test_header_rules():
    assert HostHeaderRule().match(pt("header", "Host", "h")) == {
        AttackType.HOST_HEADER,
        AttackType.SSRF,
    }
    assert HostHeaderRule().match(pt("header", "Accept", "x")) == set()
    assert ProxyHeaderRule().match(pt("header", "User-Agent", "x")) == {
        AttackType.SSRF,
        AttackType.HEADER_INJECTION,
    }
    assert ProxyHeaderRule().match(pt("header", "Accept", "x")) == set()


def test_search_name_rule():
    assert SearchNameRule().match(pt("param", "q", "x")) == {
        AttackType.XSS,
        AttackType.SQLI,
    }
    assert SearchNameRule().match(pt("param", "other", "x")) == set()


def test_default_rules_is_ordered_list_of_rules():
    assert isinstance(DEFAULT_RULES, list) and len(DEFAULT_RULES) == 10
    assert all(isinstance(r, ClassificationRule) for r in DEFAULT_RULES)
    assert all(r.name for r in DEFAULT_RULES)


def test_file_path_rule_ignores_headers():
    from penpine.attack.analyze.rules import FileNameOrPathRule

    # media-type value contains '/' but a header must NOT be tagged path-traversal/lfi
    assert FileNameOrPathRule().match(pt("header", "Content-Type", "application/json")) == set()
    assert FileNameOrPathRule().match(pt("header", "Referer", "http://x/y")) == set()


def test_file_path_rule_still_tags_body_kinds():
    from penpine.attack.analyze.rules import FileNameOrPathRule

    assert FileNameOrPathRule().match(pt("param", "x", "../e")) == {
        AttackType.PATH_TRAVERSAL,
        AttackType.LFI,
    }
    assert FileNameOrPathRule().match(pt("json", "doc", "anything")) == {
        AttackType.PATH_TRAVERSAL,
        AttackType.LFI,
    }
    assert FileNameOrPathRule().match(pt("form", "x", "a/b")) == {
        AttackType.PATH_TRAVERSAL,
        AttackType.LFI,
    }
