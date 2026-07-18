"""Classification rules mapping injection points to attack-type tags."""

from __future__ import annotations

from penpine.attack.analyze.detectors import is_empty, is_numeric, is_path, is_url
from penpine.attack.types import AttackType

_BODY_KINDS = {"param", "form", "json", "multipart"}
_PATH_KINDS = {"param", "form", "json", "multipart", "cookie"}
_ID_NAMES = {"id", "uid", "user", "userid", "account", "order", "pid"}
_REDIRECT_NAMES = {
    "url",
    "redirect",
    "redirect_uri",
    "next",
    "return",
    "returnurl",
    "dest",
    "destination",
    "callback",
}
_FILE_NAMES = {"file", "path", "page", "template", "include", "doc", "document", "filename"}
_PROXY_HEADERS = {
    "x-forwarded-for",
    "x-forwarded-host",
    "forwarded",
    "referer",
    "user-agent",
    "x-real-ip",
    "true-client-ip",
}
_SEARCH_NAMES = {"q", "query", "search", "s", "keyword", "term"}


def _name(point) -> str:
    return (point.name or "").lower()


class ClassificationRule:
    name = "rule"

    def match(self, point) -> set:
        """Return attack-type tags this rule contributes for the point (or empty)."""
        raise NotImplementedError


class StringContextRule(ClassificationRule):
    name = "string-context"

    def match(self, point) -> set:
        if point.kind in _BODY_KINDS and not is_empty(point.value) and not is_numeric(point.value):
            return {AttackType.SQLI, AttackType.XSS}
        return set()


class NumericValueRule(ClassificationRule):
    name = "numeric-value"

    def match(self, point) -> set:
        if point.kind in _BODY_KINDS | {"cookie"} and is_numeric(point.value):
            return {AttackType.SQLI, AttackType.IDOR}
        return set()


class IdentifierNameRule(ClassificationRule):
    name = "identifier-name"

    def match(self, point) -> set:
        n = _name(point)
        if n in _ID_NAMES or n.endswith("_id"):
            return {AttackType.IDOR, AttackType.SQLI}
        return set()


class UrlValueRule(ClassificationRule):
    name = "url-value"

    def match(self, point) -> set:
        return {AttackType.SSRF, AttackType.OPEN_REDIRECT} if is_url(point.value) else set()


class RedirectNameRule(ClassificationRule):
    name = "redirect-name"

    def match(self, point) -> set:
        return (
            {AttackType.OPEN_REDIRECT, AttackType.SSRF}
            if _name(point) in _REDIRECT_NAMES
            else set()
        )


class FileNameOrPathRule(ClassificationRule):
    name = "file-or-path"

    def match(self, point) -> set:
        if point.kind not in _PATH_KINDS:
            return set()
        if is_path(point.value) or _name(point) in _FILE_NAMES:
            return {AttackType.PATH_TRAVERSAL, AttackType.LFI}
        return set()


class PathSegmentRule(ClassificationRule):
    name = "path-segment"

    def match(self, point) -> set:
        return {AttackType.PATH_TRAVERSAL, AttackType.IDOR} if point.kind == "path-seg" else set()


class HostHeaderRule(ClassificationRule):
    name = "host-header"

    def match(self, point) -> set:
        if point.kind == "header" and _name(point) == "host":
            return {AttackType.HOST_HEADER, AttackType.SSRF}
        return set()


class ProxyHeaderRule(ClassificationRule):
    name = "proxy-header"

    def match(self, point) -> set:
        if point.kind == "header" and _name(point) in _PROXY_HEADERS:
            return {AttackType.SSRF, AttackType.HEADER_INJECTION}
        return set()


class SearchNameRule(ClassificationRule):
    name = "search-name"

    def match(self, point) -> set:
        return {AttackType.XSS, AttackType.SQLI} if _name(point) in _SEARCH_NAMES else set()


class FuzzRule(ClassificationRule):
    name = "fuzz"

    def match(self, point) -> set:
        return {AttackType.FUZZ}


class TemplateInjectionRule(ClassificationRule):
    name = "template-injection"

    def match(self, point) -> set:
        if point.kind in _BODY_KINDS and not is_empty(point.value) and not is_numeric(point.value):
            return {AttackType.SSTI}
        if _name(point) in _SEARCH_NAMES:
            return {AttackType.SSTI}
        return set()


class CrlfRule(ClassificationRule):
    name = "crlf"

    def match(self, point) -> set:
        if point.kind in {"param", "form", "json", "header"}:
            return {AttackType.CRLF}
        if _name(point) in _REDIRECT_NAMES:
            return {AttackType.CRLF}
        return set()


class CommandInjectionRule(ClassificationRule):
    name = "command-injection"

    def match(self, point) -> set:
        if point.kind in _BODY_KINDS and not is_empty(point.value):
            return {AttackType.CMDI}
        return set()


class NoSqlRule(ClassificationRule):
    name = "nosql"

    def match(self, point) -> set:
        return {AttackType.NOSQLI} if point.kind in {"param", "form", "json"} else set()


DEFAULT_RULES = [
    StringContextRule(),
    NumericValueRule(),
    IdentifierNameRule(),
    UrlValueRule(),
    RedirectNameRule(),
    FileNameOrPathRule(),
    PathSegmentRule(),
    HostHeaderRule(),
    ProxyHeaderRule(),
    SearchNameRule(),
    FuzzRule(),
    TemplateInjectionRule(),
    CrlfRule(),
    CommandInjectionRule(),
    NoSqlRule(),
]
