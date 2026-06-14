# Penpine L4b — Injection-Point Analyzer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build L4b of Penpine — a rule-driven injection-point analyzer that classifies L0 injection candidates into attack-type-tagged `InjectionPoint`s, with a shared `detectors` module, an extensible default rule set, and an `Analysis` wrapper.

**Architecture:** `analyze(request)` enumerates L0 candidates, builds an L4a `InjectionPoint` per candidate, unions attack-type tags from an ordered list of `ClassificationRule`s (default heuristics, user-replaceable), and returns an `Analysis` with `for_attack`/`by_kind` helpers. Value heuristics live in a reusable `detectors` module. Pure, network-free.

**Tech Stack:** Python 3.11+, stdlib `re`/`dataclasses`, `pytest`. Depends on L0 (`injection_candidates`) and L4a (`InjectionPoint`).

---

## File Structure

```
penpine/attack/analyze/
  __init__.py     # public exports
  detectors.py    # value heuristics
  rules.py        # ClassificationRule + default rules + DEFAULT_RULES
  analysis.py     # Analysis
  analyzer.py     # analyze()
tests/attack/analyze/
  ... mirrors the above
```

Build order: scaffolding → detectors → rules → Analysis → analyzer + public API.

---

## Task 0: Scaffolding

**Files:**
- Create: `penpine/attack/analyze/__init__.py`, `tests/attack/analyze/__init__.py`

- [ ] **Step 1: Create empty package inits**

Create empty files: `penpine/attack/analyze/__init__.py`, `tests/attack/analyze/__init__.py`.

- [ ] **Step 2: Verify suite still green**

Run: `python -m pytest -q`
Expected: `225 passed`.

- [ ] **Step 3: Commit**

```bash
git add penpine/attack/analyze tests/attack/analyze
git commit -c commit.gpgsign=false -m "chore: scaffold L4b analyze package"
```

---

## Task 1: Detectors

**Files:**
- Create: `penpine/attack/analyze/detectors.py`
- Test: `tests/attack/analyze/test_detectors.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/attack/analyze/test_detectors.py
from penpine.attack.analyze import detectors as d


def test_is_numeric_and_integer():
    assert d.is_numeric("12") and d.is_numeric(12) and d.is_numeric("1.5") and d.is_numeric(1.5)
    assert not d.is_numeric("ab") and not d.is_numeric("") and not d.is_numeric(None)
    assert not d.is_numeric(True)               # bool is not numeric here
    assert d.is_integer("12") and d.is_integer(-3) and d.is_integer("12")
    assert not d.is_integer("1.5") and not d.is_integer("x")


def test_is_url():
    assert d.is_url("http://x") and d.is_url("https://x/y") and d.is_url("//cdn/x")
    assert not d.is_url("/path") and not d.is_url("x") and not d.is_url(None)


def test_is_path():
    assert d.is_path("../etc/passwd") and d.is_path("a/b") and d.is_path("c\\d")
    assert not d.is_path("abc") and not d.is_path("http://x")   # url is not a path


def test_is_email_uuid_json_bool_empty():
    assert d.is_email("a@b.com") and not d.is_email("a@b")
    assert d.is_uuid("12345678-1234-1234-1234-123456789abc")
    assert not d.is_uuid("nope")
    assert d.looks_like_json('{"a":1}') and d.looks_like_json("[1]")
    assert not d.looks_like_json("plain")
    assert d.is_boolean("true") and d.is_boolean("0") and d.is_boolean(False)
    assert not d.is_boolean("maybe")
    assert d.is_empty(None) and d.is_empty("   ") and not d.is_empty("x")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/attack/analyze/test_detectors.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Write minimal implementation**

```python
# penpine/attack/analyze/detectors.py
"""Reusable value heuristics for classification and payload tailoring."""
from __future__ import annotations

import re

_UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_INT_RE = re.compile(r"^[+-]?\d+$")
_BOOL_VALUES = {"true", "false", "0", "1", "yes", "no"}


def _s(value) -> str:
    if value is None:
        return ""
    return value if isinstance(value, str) else str(value)


def is_integer(value) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return True
    return bool(_INT_RE.match(_s(value).strip()))


def is_numeric(value) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        return True
    s = _s(value).strip()
    if not s:
        return False
    try:
        float(s)
        return True
    except ValueError:
        return False


def is_url(value) -> bool:
    s = _s(value).strip().lower()
    return s.startswith(("http://", "https://", "//"))


def is_path(value) -> bool:
    if is_url(value):
        return False
    s = _s(value)
    return "/" in s or "\\" in s or ".." in s


def is_email(value) -> bool:
    return bool(_EMAIL_RE.match(_s(value).strip()))


def is_uuid(value) -> bool:
    return bool(_UUID_RE.match(_s(value).strip()))


def looks_like_json(value) -> bool:
    s = _s(value).strip()
    return s.startswith("{") or s.startswith("[")


def is_boolean(value) -> bool:
    if isinstance(value, bool):
        return True
    return _s(value).strip().lower() in _BOOL_VALUES


def is_empty(value) -> bool:
    if value is None:
        return True
    return _s(value).strip() == ""
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/attack/analyze/test_detectors.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add penpine/attack/analyze/detectors.py tests/attack/analyze/test_detectors.py
git commit -c commit.gpgsign=false -m "feat: add value detectors for classification"
```

---

## Task 2: Classification rules

**Files:**
- Create: `penpine/attack/analyze/rules.py`
- Test: `tests/attack/analyze/test_rules.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/attack/analyze/test_rules.py
from penpine.attack.models import InjectionPoint
from penpine.attack.analyze.rules import (
    ClassificationRule, StringContextRule, NumericValueRule, IdentifierNameRule,
    UrlValueRule, RedirectNameRule, FileNameOrPathRule, PathSegmentRule,
    HostHeaderRule, ProxyHeaderRule, SearchNameRule, DEFAULT_RULES,
)


def pt(kind, name, value):
    expr = kind if kind in ("method", "target", "version") else f"{kind}:{name}"
    return InjectionPoint(expr=expr, kind=kind, name=name, value=value)


def test_string_context_rule():
    assert StringContextRule().match(pt("param", "x", "hello")) == {"sqli", "xss"}
    assert StringContextRule().match(pt("param", "x", "12")) == set()      # numeric excluded
    assert StringContextRule().match(pt("header", "x", "hello")) == set()  # wrong kind


def test_numeric_value_rule():
    assert NumericValueRule().match(pt("param", "x", "12")) == {"sqli", "idor"}
    assert NumericValueRule().match(pt("param", "x", "hello")) == set()


def test_identifier_name_rule():
    assert IdentifierNameRule().match(pt("param", "id", "1")) == {"idor", "sqli"}
    assert IdentifierNameRule().match(pt("param", "user_id", "1")) == {"idor", "sqli"}
    assert IdentifierNameRule().match(pt("param", "valid", "1")) == set()   # not id-like


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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/attack/analyze/test_rules.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Write minimal implementation**

```python
# penpine/attack/analyze/rules.py
"""Classification rules mapping injection points to attack-type tags."""
from __future__ import annotations

from penpine.attack.analyze.detectors import is_empty, is_numeric, is_path, is_url

_BODY_KINDS = {"param", "form", "json", "multipart"}
_ID_NAMES = {"id", "uid", "user", "userid", "account", "order", "pid"}
_REDIRECT_NAMES = {"url", "redirect", "redirect_uri", "next", "return",
                   "returnurl", "dest", "destination", "callback"}
_FILE_NAMES = {"file", "path", "page", "template", "include", "doc",
               "document", "filename"}
_PROXY_HEADERS = {"x-forwarded-for", "x-forwarded-host", "forwarded", "referer",
                  "user-agent", "x-real-ip", "true-client-ip"}
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
        if point.kind in _BODY_KINDS and not is_empty(point.value) \
                and not is_numeric(point.value):
            return {"sqli", "xss"}
        return set()


class NumericValueRule(ClassificationRule):
    name = "numeric-value"

    def match(self, point) -> set:
        if point.kind in _BODY_KINDS | {"cookie"} and is_numeric(point.value):
            return {"sqli", "idor"}
        return set()


class IdentifierNameRule(ClassificationRule):
    name = "identifier-name"

    def match(self, point) -> set:
        n = _name(point)
        if n in _ID_NAMES or n.endswith("_id"):
            return {"idor", "sqli"}
        return set()


class UrlValueRule(ClassificationRule):
    name = "url-value"

    def match(self, point) -> set:
        return {"ssrf", "open-redirect"} if is_url(point.value) else set()


class RedirectNameRule(ClassificationRule):
    name = "redirect-name"

    def match(self, point) -> set:
        return {"open-redirect", "ssrf"} if _name(point) in _REDIRECT_NAMES else set()


class FileNameOrPathRule(ClassificationRule):
    name = "file-or-path"

    def match(self, point) -> set:
        if is_path(point.value) or _name(point) in _FILE_NAMES:
            return {"path-traversal", "lfi"}
        return set()


class PathSegmentRule(ClassificationRule):
    name = "path-segment"

    def match(self, point) -> set:
        return {"path-traversal", "idor"} if point.kind == "path-seg" else set()


class HostHeaderRule(ClassificationRule):
    name = "host-header"

    def match(self, point) -> set:
        if point.kind == "header" and _name(point) == "host":
            return {"host-header", "ssrf"}
        return set()


class ProxyHeaderRule(ClassificationRule):
    name = "proxy-header"

    def match(self, point) -> set:
        if point.kind == "header" and _name(point) in _PROXY_HEADERS:
            return {"ssrf", "header-injection"}
        return set()


class SearchNameRule(ClassificationRule):
    name = "search-name"

    def match(self, point) -> set:
        return {"xss", "sqli"} if _name(point) in _SEARCH_NAMES else set()


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
]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/attack/analyze/test_rules.py -v`
Expected: PASS (8 passed).

- [ ] **Step 5: Commit**

```bash
git add penpine/attack/analyze/rules.py tests/attack/analyze/test_rules.py
git commit -c commit.gpgsign=false -m "feat: add classification rules + default rule set"
```

---

## Task 3: Analysis wrapper

**Files:**
- Create: `penpine/attack/analyze/analysis.py`
- Test: `tests/attack/analyze/test_analysis.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/attack/analyze/test_analysis.py
from penpine.attack.models import InjectionPoint
from penpine.attack.analyze.analysis import Analysis


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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/attack/analyze/test_analysis.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Write minimal implementation**

```python
# penpine/attack/analyze/analysis.py
"""Analysis: the tagged-injection-point result of analyze()."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Analysis:
    request: object
    points: tuple

    def for_attack(self, attack_type: str) -> list:
        return [p for p in self.points if attack_type in p.attack_types]

    def by_kind(self) -> dict:
        grouped: dict = {}
        for point in self.points:
            grouped.setdefault(point.kind, []).append(point)
        return grouped

    def attack_types(self) -> set:
        return {tag for point in self.points for tag in point.attack_types}

    def all(self) -> list:
        return list(self.points)

    def __iter__(self):
        return iter(self.points)

    def __len__(self) -> int:
        return len(self.points)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/attack/analyze/test_analysis.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add penpine/attack/analyze/analysis.py tests/attack/analyze/test_analysis.py
git commit -c commit.gpgsign=false -m "feat: add Analysis result wrapper"
```

---

## Task 4: analyzer + public API

**Files:**
- Create: `penpine/attack/analyze/analyzer.py`
- Modify: `penpine/attack/analyze/__init__.py`, `penpine/attack/__init__.py`
- Test: `tests/attack/analyze/test_analyzer.py`, `tests/attack/analyze/test_public_api.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/attack/analyze/test_analyzer.py
from penpine.core.message import Request
from penpine.attack.analyze.analyzer import analyze
from penpine.attack.analyze.rules import ClassificationRule


CRAFTED = (
    b"POST /files/1?id=7&q=hello&next=http://e.com HTTP/1.1\r\n"
    b"Host: t.com\r\nUser-Agent: x\r\n"
    b"Content-Type: application/json\r\nContent-Length: 14\r\n\r\n"
    b'{"name":"ann"}')


def _find(analysis, expr):
    return next(p for p in analysis.points if p.expr == expr)


def test_analyze_tags_points_by_kind_name_and_value():
    a = analyze(Request.from_raw(CRAFTED))
    assert {"idor", "sqli"} <= set(_find(a, "param:id").attack_types)
    assert "xss" in _find(a, "param:q").attack_types
    assert {"open-redirect", "ssrf"} <= set(_find(a, "param:next").attack_types)
    assert "host-header" in _find(a, "header:Host").attack_types
    assert "header-injection" in _find(a, "header:User-Agent").attack_types
    assert "path-traversal" in _find(a, "path-seg:1").attack_types
    assert {"sqli", "xss"} <= set(_find(a, "json:$.name").attack_types)


def test_for_attack_selects_points():
    a = analyze(Request.from_raw(CRAFTED))
    sqli_exprs = {p.expr for p in a.for_attack("sqli")}
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
            return {"custom"} if point.kind == "param" else set()

    a = analyze(Request.from_url("http://h/?a=1"), rules=[Tagger()])
    assert "custom" in next(p for p in a.points if p.expr == "param:a").attack_types


def test_attack_types_sorted_for_determinism():
    a = analyze(Request.from_url("http://h/?id=1"))
    tags = _find(a, "param:id").attack_types
    assert list(tags) == sorted(tags)
```

```python
# tests/attack/analyze/test_public_api.py
import penpine.attack as attack
from penpine.attack.analyze import (
    analyze, Analysis, ClassificationRule, DEFAULT_RULES, detectors,
)


def test_analyze_package_exports():
    assert callable(analyze)
    assert Analysis and ClassificationRule and DEFAULT_RULES
    assert hasattr(detectors, "is_url")


def test_attack_reexports_analyze():
    assert attack.analyze is analyze
    assert attack.Analysis is Analysis
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/attack/analyze/test_analyzer.py tests/attack/analyze/test_public_api.py -v`
Expected: FAIL — analyzer/exports missing.

- [ ] **Step 3: Write minimal implementation**

```python
# penpine/attack/analyze/analyzer.py
"""analyze(): classify a request's injection candidates into tagged points."""
from __future__ import annotations

import dataclasses

from penpine.attack.models import InjectionPoint
from penpine.attack.analyze.analysis import Analysis
from penpine.attack.analyze.rules import DEFAULT_RULES


def analyze(request, *, rules=None, kinds=None) -> Analysis:
    active = DEFAULT_RULES if rules is None else list(rules)
    points = []
    for loc in request.injection_candidates(kinds=kinds):
        base = InjectionPoint.from_locator(loc)
        tags: set = set()
        for rule in active:
            tags |= rule.match(base)
        points.append(dataclasses.replace(base, attack_types=tuple(sorted(tags))))
    return Analysis(request=request, points=tuple(points))
```

```python
# penpine/attack/analyze/__init__.py
"""Penpine L4b injection-point analyzer."""
from penpine.attack.analyze import detectors
from penpine.attack.analyze.analysis import Analysis
from penpine.attack.analyze.rules import (
    ClassificationRule, StringContextRule, NumericValueRule, IdentifierNameRule,
    UrlValueRule, RedirectNameRule, FileNameOrPathRule, PathSegmentRule,
    HostHeaderRule, ProxyHeaderRule, SearchNameRule, DEFAULT_RULES,
)
from penpine.attack.analyze.analyzer import analyze

__all__ = [
    "detectors", "analyze", "Analysis", "ClassificationRule",
    "StringContextRule", "NumericValueRule", "IdentifierNameRule",
    "UrlValueRule", "RedirectNameRule", "FileNameOrPathRule", "PathSegmentRule",
    "HostHeaderRule", "ProxyHeaderRule", "SearchNameRule", "DEFAULT_RULES",
]
```

Then add to the END of `penpine/attack/__init__.py` (after the existing L4a imports), and extend its `__all__`:

```python
from penpine.attack.analyze import analyze, Analysis
```

Add `"analyze", "Analysis"` to the `__all__` list in `penpine/attack/__init__.py`.

- [ ] **Step 4: Run the FULL suite**

Run: `python -m pytest -q`
Expected: PASS — all prior + L4b tests green (no failures, no errors).

- [ ] **Step 5: Commit**

```bash
git add penpine/attack/analyze/analyzer.py penpine/attack/analyze/__init__.py penpine/attack/__init__.py tests/attack/analyze/test_analyzer.py tests/attack/analyze/test_public_api.py
git commit -c commit.gpgsign=false -m "feat: add analyze() + expose L4b public API"
```

---

## Self-Review Notes (against the spec)

- **§3 module layout** → Tasks 0–4 create every listed module.
- **§4 detectors** → Task 1 (all nine functions tested).
- **§5 rules + DEFAULT_RULES** → Task 2 (all ten rules + the ordered list).
- **§6 Analysis** → Task 3.
- **§7 analyzer** (rules default/empty, kinds passthrough, `dataclasses.replace`, sorted tags) → Task 4.
- **§8 public API** (analyze/Analysis re-exported from `penpine.attack`) → Task 4.
- **§9 testing** → test-first throughout; the crafted multi-kind request is Task 4's `test_analyze_tags_points_by_kind_name_and_value`.

**Intentional tightening vs spec §5:** `IdentifierNameRule` matches the exact id-name set or a `_id` suffix (not a bare `*id` suffix) to avoid false positives like `valid`/`grid`/`uuid`. Functionally covers the real cases (`id`, `user_id`, `account`).

**Deferred (per spec §2):** the runner that consumes the analysis (L4c); real modules (L4d); module-driven classification.

**Import-order note for implementers:** `rules.py` imports detector functions directly (`from penpine.attack.analyze.detectors import ...`), and `penpine/attack/analyze/__init__.py` imports in dependency order (detectors → analysis → rules → analyzer) to avoid any partial-initialization cycle.

**Intentional name overlap:** the `analyze` *function* is re-exported into `penpine.attack`, where there is also an `analyze` *subpackage*. The `from penpine.attack.analyze import analyze` re-export rebinds `penpine.attack.analyze` to the function (so `penpine.attack.analyze(req)` works ergonomically). The subpackage remains fully importable via explicit `import penpine.attack.analyze` / `from penpine.attack.analyze import detectors, Analysis, ...` (which is how L4c will consume it). This is a deliberate, tested choice (`test_attack_reexports_analyze`), not a bug — do not "fix" it by renaming.
```
