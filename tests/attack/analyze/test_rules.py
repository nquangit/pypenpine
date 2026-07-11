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


def pt(kind, name, value):
    expr = kind if kind in ("method", "target", "version") else f"{kind}:{name}"
    return InjectionPoint(expr=expr, kind=kind, name=name, value=value)


def test_string_context_rule():
    assert StringContextRule().match(pt("param", "x", "hello")) == {"sqli", "xss"}
    assert StringContextRule().match(pt("param", "x", "12")) == set()
    assert StringContextRule().match(pt("header", "x", "hello")) == set()


def test_numeric_value_rule():
    assert NumericValueRule().match(pt("param", "x", "12")) == {"sqli", "idor"}
    assert NumericValueRule().match(pt("param", "x", "hello")) == set()


def test_identifier_name_rule():
    assert IdentifierNameRule().match(pt("param", "id", "1")) == {"idor", "sqli"}
    assert IdentifierNameRule().match(pt("param", "user_id", "1")) == {"idor", "sqli"}
    assert IdentifierNameRule().match(pt("param", "valid", "1")) == set()


def test_url_and_redirect_rules():
    assert UrlValueRule().match(pt("param", "x", "http://e.com")) == {"ssrf", "open-redirect"}
    assert UrlValueRule().match(pt("param", "x", "plain")) == set()
    assert RedirectNameRule().match(pt("param", "next", "x")) == {"open-redirect", "ssrf"}
    assert RedirectNameRule().match(pt("param", "other", "x")) == set()


def test_file_path_and_segment_rules():
    assert FileNameOrPathRule().match(pt("param", "x", "../e")) == {"path-traversal", "lfi"}
    assert FileNameOrPathRule().match(pt("param", "file", "x")) == {"path-traversal", "lfi"}
    assert FileNameOrPathRule().match(pt("param", "x", "plain")) == set()
    assert PathSegmentRule().match(pt("path-seg", "1", "1")) == {"path-traversal", "idor"}
    assert PathSegmentRule().match(pt("param", "x", "1")) == set()


def test_header_rules():
    assert HostHeaderRule().match(pt("header", "Host", "h")) == {"host-header", "ssrf"}
    assert HostHeaderRule().match(pt("header", "Accept", "x")) == set()
    assert ProxyHeaderRule().match(pt("header", "User-Agent", "x")) == {"ssrf", "header-injection"}
    assert ProxyHeaderRule().match(pt("header", "Accept", "x")) == set()


def test_search_name_rule():
    assert SearchNameRule().match(pt("param", "q", "x")) == {"xss", "sqli"}
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

    assert FileNameOrPathRule().match(pt("param", "x", "../e")) == {"path-traversal", "lfi"}
    assert FileNameOrPathRule().match(pt("json", "doc", "anything")) == {"path-traversal", "lfi"}
    assert FileNameOrPathRule().match(pt("form", "x", "a/b")) == {"path-traversal", "lfi"}
