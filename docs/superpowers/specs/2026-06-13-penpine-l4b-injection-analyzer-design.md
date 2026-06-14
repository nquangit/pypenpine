# Penpine — L4b: Injection-Point Analyzer (Design Spec)

**Date:** 2026-06-13
**Status:** Approved for implementation planning
**Scope:** This spec covers **L4b only** — classifying L0 injection candidates into attack-type-tagged injection points. Second of four L4 sub-projects.

---

## 1. Context

L4b consumes L0's `Request.injection_candidates()` and produces L4a `InjectionPoint`s with `attack_types` filled, so the L4c runner can select which points to attack for a chosen attack type ("provide the most appropriate injection point along with the corresponding attack types").

Depends on:
- L0: `Request.injection_candidates(kinds=...)` → `list[ResolvedLocator]` (each with `.kind`/`.name`/`.value`).
- L4a: `InjectionPoint` (frozen dataclass with `expr`/`kind`/`name`/`value`/`attack_types`), `InjectionPoint.from_locator`.

No L1–L3 dependency.

**L4b decisions (this round):**
- **Rule-driven & extensible** classification (not module-driven).
- Rules are **named objects** with `match(point) -> set[str]` (attack-type tags); the analyzer unions tags.
- `analyze()` returns an **`Analysis`** wrapper with query helpers.
- Value heuristics live in a shared **`detectors`** module.
- The default rule set is **opinionated and fully replaceable**; tags are **advisory**.
- `analyze` fills `attack_types` via `dataclasses.replace`.

## 2. Goals & Non-Goals

**Goals**
- A reusable `detectors` module of value heuristics.
- A `ClassificationRule` contract + an ordered, replaceable `DEFAULT_RULES` set.
- `analyze(request, *, rules=None, kinds=None) -> Analysis` that tags each candidate.
- An `Analysis` wrapper with `for_attack`/`by_kind`/`attack_types`/`all` + iteration.
- Fully unit-testable, no network.

**Non-Goals (later sub-projects)**
- The runner that consumes the analysis (L4c).
- Real attack modules / payloads (L4d).
- Module-driven classification (rules only in v1).

## 3. Module Layout

```
penpine/attack/analyze/
  __init__.py     # public exports
  detectors.py    # value heuristics
  rules.py        # ClassificationRule + default rules + DEFAULT_RULES
  analysis.py     # Analysis
  analyzer.py     # analyze()
```
`penpine/attack/__init__.py` additionally re-exports `analyze` and `Analysis`.

## 4. Detectors (`detectors.py`)

Pure functions; each stringifies the value first (`None` → `""`). Heuristic and conservative.

```python
def is_numeric(value) -> bool      # int/float instance, or a string parseable as int/float
def is_integer(value) -> bool      # int instance, or an all-digits (optionally signed) string
def is_url(value) -> bool          # starts with "http://", "https://", or "//"
def is_path(value) -> bool         # contains "/", "\\", or ".." (and is not purely a URL scheme)
def is_email(value) -> bool        # matches ^[^@\s]+@[^@\s]+\.[^@\s]+$
def is_uuid(value) -> bool         # 8-4-4-4-12 hex
def looks_like_json(value) -> bool # stripped string starts with "{" or "["
def is_boolean(value) -> bool      # in {true,false,0,1,yes,no} (case-insensitive)
def is_empty(value) -> bool        # None or empty/whitespace-only string
```

## 5. Rules (`rules.py`)

```python
class ClassificationRule:
    name: str = "rule"
    def match(self, point: InjectionPoint) -> set[str]:
        """Return the attack-type tags this rule contributes for the point (or empty set)."""
        raise NotImplementedError
```

Helpers used by rules: `_value_str(point)` (stringified value), `_name_lower(point)`, and constant name-keyword sets.

**`DEFAULT_RULES`** (ordered; opinionated; replaceable). Each rule's tag contribution:

| Rule | Condition | Tags |
|---|---|---|
| `StringContextRule` | kind in {param, form, json, multipart} AND value is non-numeric/non-empty string | `{sqli, xss}` |
| `NumericValueRule` | value `is_numeric` AND kind in {param, form, json, multipart, cookie} | `{sqli, idor}` |
| `IdentifierNameRule` | name matches id-like (`id`,`uid`,`user`,`account`,`order`,`pid`, or `*_id`/`*id`) | `{idor, sqli}` |
| `UrlValueRule` | value `is_url` | `{ssrf, open-redirect}` |
| `RedirectNameRule` | name in {`url`,`redirect`,`redirect_uri`,`next`,`return`,`returnurl`,`dest`,`destination`,`callback`} | `{open-redirect, ssrf}` |
| `FileNameOrPathRule` | kind in {param,form,json,multipart,cookie} AND (value `is_path` OR name in {`file`,`path`,`page`,`template`,`include`,`doc`,`document`,`filename`}) | `{path-traversal, lfi}` |
| `PathSegmentRule` | kind == `path-seg` | `{path-traversal, idor}` |
| `HostHeaderRule` | kind == `header` AND name.lower() == `host` | `{host-header, ssrf}` |
| `ProxyHeaderRule` | kind == `header` AND name.lower() in {`x-forwarded-for`,`x-forwarded-host`,`forwarded`,`referer`,`user-agent`,`x-real-ip`,`true-client-ip`} | `{ssrf, header-injection}` |
| `SearchNameRule` | name.lower() in {`q`,`query`,`search`,`s`,`keyword`,`term`} | `{xss, sqli}` |

The analyzer unions tags across all rules for each point. Name matching is case-insensitive. Users construct their own list (subset, superset, or custom `ClassificationRule` subclasses) and pass it to `analyze(rules=...)`.

## 6. Analysis (`analysis.py`)

```python
@dataclass(frozen=True)
class Analysis:
    request: object
    points: tuple                                   # tuple[InjectionPoint, ...]

    def for_attack(self, attack_type: str) -> list   # points whose attack_types include it
    def by_kind(self) -> dict                         # kind -> [points], insertion-ordered
    def attack_types(self) -> set                     # union of all points' attack_types
    def all(self) -> list                             # list(points)
    def __iter__(self)                                # iterate points
    def __len__(self)
```

## 7. Analyzer (`analyzer.py`)

```python
def analyze(request, *, rules=None, kinds=None) -> Analysis:
    active = DEFAULT_RULES if rules is None else list(rules)
    points = []
    for loc in request.injection_candidates(kinds=kinds):
        base = InjectionPoint.from_locator(loc)
        tags: set[str] = set()
        for rule in active:
            tags |= rule.match(base)
        points.append(dataclasses.replace(base, attack_types=tuple(sorted(tags))))
    return Analysis(request=request, points=tuple(points))
```
- `rules=None` → `DEFAULT_RULES`; `rules=[]` → points with empty `attack_types`.
- `kinds` passes through to L0's `injection_candidates` to restrict point kinds.
- `attack_types` is stored sorted for determinism.

## 8. Public API (`penpine/attack/analyze/__init__.py`)

Exports: `analyze`, `Analysis`, `ClassificationRule`, all default rule classes, `DEFAULT_RULES`, and the `detectors` module (and individual detector functions). `penpine/attack/__init__.py` re-exports `analyze` and `Analysis`.

## 9. Testing Strategy (TDD)

All unit-level, no network.

- **detectors:** each function over representative true/false inputs (`is_numeric("12")`/`is_numeric("ab")`, `is_url("http://x")`/`is_url("/p")`, `is_path("../x")`/`is_path("abc")`, `is_email`, `is_uuid`, `looks_like_json`, `is_boolean`, `is_empty(None)`).
- **rules:** each default rule emits the expected tags for a matching `InjectionPoint` and an empty set for a non-matching one (constructed `InjectionPoint`s, no request needed).
- **Analysis:** `for_attack`/`by_kind`/`attack_types`/`all`/`len`/iter on a hand-built `Analysis`.
- **analyzer:** `analyze` over a crafted request exercising multiple kinds —
  `Request.from_raw` of a POST with query `?id=7&q=hello&next=http://e.com`, a JSON body `{"name":"a"}`, headers `Host`, `User-Agent`, and a path `/files/1` — assert per-point `attack_types` (e.g. `param:id` → contains `idor`,`sqli`; `param:q` → `xss`,`sqli`; `param:next` → `open-redirect`,`ssrf`; `header:Host` → `host-header`; `path-seg:1` → `path-traversal`); `for_attack("sqli")` returns the sqli-tagged points; `kinds={"param"}` restricts; `rules=[]` → all empty; a custom rule adds a tag.

## 10. Dependencies

- Runtime: none beyond L0 + L4a (stdlib `re`, `dataclasses`). Python 3.11+.
- Dev/test: `pytest`.

## 11. Forward Hooks

- L4c's runner calls `analyze(request)` then `analysis.for_attack(chosen_type)` to choose points, and reuses `detectors` so generators can tailor payloads to value type.
- L4d modules name their attacks to match the tag vocabulary (`sqli`, `xss`, `ssrf`, `open-redirect`, `path-traversal`, `lfi`, `idor`, `host-header`, `header-injection`).
