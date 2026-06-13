# Penpine — L3: Data & Context (Design Spec)

**Date:** 2026-06-13
**Status:** Approved for implementation planning
**Scope:** This spec covers **L3 only** — data profiles and the runtime data/context bus. L0–L2 are complete and merged. L4 (attack framework) is out of scope and gets its own spec→plan→build cycle.

---

## 1. Context

L3 moves data between requests. It provides static, role-bound fixtures (data profiles) and a runtime "bus" that captures values from responses and feeds them into later requests — including across identities ("user A creates request X, user B uses X"). It binds L2's auth (an identity carries its `SessionManager`) to data and runtime context.

What earlier layers already provide:
- L0: `Response`/`Request`, `body.json` (JSONPath), `cookies.parse_set_cookie`, `Headers`, `Request` mutators (`with_target`/`with_headers`/`with_body`), `RequestBuilder`, `PenpineError`, `get_logger`.
- L1: `Interceptor` seam (`after_receive`).
- L2: `AuthProfile`, `SessionManager` (`async send`/`send_sync`).

**L3 decisions (this round):**
- Injection: programmatic accessors **plus** a custom `{{ }}` template renderer.
- Context: a single shared, thread-safe `Context` (flat, namespaced by key convention).
- Capture: manual `capture()` (strict) **plus** an optional best-effort `CaptureInterceptor`.
- Bundling: an `Identity` (auth/manager + `DataProfile` + `Context`).

## 2. Goals & Non-Goals

**Goals**
- A thread-safe `Context` key/value bus, shareable across identities.
- `DataProfile`: named static fixtures for a role/department.
- Declarative `Extract` rules (json/header/cookie/regex/status) and helpers to run them.
- A custom `{{ }}` template renderer over a `Request` (target/headers/body), with strict-miss errors and automatic Content-Length recompute.
- A `CaptureInterceptor` (L1 seam) for automatic best-effort capture.
- An `Identity` bundle tying auth, data, and context into one per-actor handle, working authenticated or not.
- Typed errors, shared logging, fully unit-testable with no sockets.

**Non-Goals (deferred)**
- Hierarchical/scoped contexts (flat + namespace convention only).
- Persistence of context/data across process runs.
- The attack framework (L4): injection analysis, payload generation, runner, validation.

## 3. Module Layout

```
penpine/data/
  __init__.py     # public exports
  exceptions.py   # DataError hierarchy
  context.py      # Context + NamespacedView
  profile.py      # DataProfile
  extract.py      # Extract + extract_value + run_extractors
  capture.py      # capture() + CaptureInterceptor
  template.py     # render() + build_mapping()
  identity.py     # Identity
```

## 4. Errors

```
DataError(PenpineError)
├── ExtractError    # a required extraction target was absent / unparseable
└── TemplateError   # an unknown placeholder in strict render
```

## 5. Context

`Context` is a thread-safe key/value store (a `dict` guarded by a `threading.Lock`, safe from both async tasks and L2's sync-facade loop thread).

```
Context(initial: dict | None = None)
  get(key, default=None)
  set(key, value)
  has(key) -> bool
  require(key)            # raises DataError if absent
  update(mapping)
  keys() -> list[str]
  to_dict() -> dict       # snapshot copy
  namespace(prefix) -> NamespacedView
```

`NamespacedView(context, prefix)` — a thin view whose `get/set/has/require` operate on `f"{prefix}.{key}"`. No fallback/hierarchy; pure key-prefix convenience.

Simple `get`/`set` are atomic; compound operations (`update`, `to_dict`) hold the lock. Lock hold time is negligible.

## 6. DataProfile

```
@dataclass
class DataProfile:
    name: str
    values: dict = field(default_factory=dict)

    def get(self, key, default=None)
    def require(self, key)          # raises DataError if absent
```
Named static fixtures (a role's known account IDs, etc.). Values may be nested; lookups are by top-level key.

## 7. Extractors

```
@dataclass
class Extract:
    key: str
    json: str | None = None      # JSONPath on response body
    header: str | None = None    # header value (first match)
    cookie: str | None = None    # value from a Set-Cookie header
    regex: str | None = None     # re.search on response body text
    status: bool = False         # store the status code
    required: bool = True
    default: object = None
```
Exactly one source (`json`/`header`/`cookie`/`regex`/`status`) should be set per `Extract`; if none is set it is a config error (`ExtractError`).

`extract_value(response, spec) -> value`:
- `json`: `response.body.json.get(spec.json)` (L0 JSONPath). Missing path → not found.
- `header`: `response.headers.get(spec.header)`.
- `cookie`: scan `Set-Cookie` headers via `parse_set_cookie`, return the value whose name matches `spec.cookie`.
- `regex`: `re.search(spec.regex, response.body.text())`; return group(1) if the pattern has groups, else group(0).
- `status`: `response.status_code`.
- Not found: return `spec.default` if `required` is False, else raise `ExtractError`.

`run_extractors(response, specs) -> dict[str, value]` — maps each spec's `key` to its extracted value.

## 8. Capture

- `capture(context, response, specs) -> dict` — runs `run_extractors` (strict: a missing required value raises `ExtractError`) and writes results into `context`; returns the captured dict.
- `CaptureInterceptor(context, specs)` — implements L1 `Interceptor`:
  - `before_send(request)` → returns the request unchanged.
  - `after_receive(request, response)` → runs the specs **best-effort**: each extraction is attempted; misses/errors are logged via `get_logger` and skipped (never raises, never raises `RetrySignal`); successful values are written to `context`. Returns the response unchanged.

Rationale: automatic per-response capture must not crash unrelated traffic; explicit `capture()` is the strict path.

## 9. Template renderer

`render(request, mapping, *, strict=True) -> Request`:
- Placeholder grammar: `{{ key }}` — regex `\{\{\s*([^}\s]+)\s*\}\}`; surrounding whitespace ignored; `key` is a literal lookup (dotted keys like `userA.order_id` are single keys, not paths).
- Substitutes in: the request **target**, every **header value**, and the **body** (decoded as text, substituted, re-encoded).
- Body changes go through `Request.with_body`, so **Content-Length auto-recomputes**.
- `strict=True`: an unknown placeholder raises `TemplateError`. `strict=False`: unknown placeholders are left verbatim.
- Values are stringified (`str(value)`) for substitution.

`build_mapping(context=None, data=None, extra=None) -> dict` — merges sources into one dict in precedence order **data < context < extra** (runtime context overrides static data; explicit `extra` overrides both). Accepts a `Context`, a `DataProfile`, and/or plain dicts.

## 10. Identity

```
Identity(name, *, auth_profile=None, manager=None, data=None, context=None, **manager_kw)
```
- `manager`: the supplied `manager` (a `SessionManager` or an `Engine` — both expose `async send`); else `auth_profile.manager(**manager_kw)`; else `None`. If `send` is called with no manager, raises `DataError`.
- `data`: a `DataProfile` (defaults to an empty one named `name`).
- `ctx`: a `Context` (defaults to a fresh one; pass a shared instance to link actors).

API:
- `async send(request, **kw)` → `manager.send(request, **kw)`.
- `send_sync(request, **kw)` → `manager.send_sync(...)` when the manager supports it (`SessionManager`/`Engine` do).
- `render(request, *, strict=True)` → `render(request, build_mapping(context=self.ctx, data=self.data), strict=strict)`.
- `capture(response, specs)` → `capture(self.ctx, response, specs)`.

Authenticated or unauthenticated actors both work (auth via the manager; none if an `Engine` is supplied).

## 11. Data Flow

```
        DataProfile (static)            Context (runtime, shared)
               │                               │  ▲
               └──────────┐        ┌───────────┘  │ capture()/CaptureInterceptor
                          ▼        ▼              │
   load/build Request → render({{...}}) → Request │
                                   │              │
                                   ▼              │
                       Identity.send (L2/L1) → Response ── extract ──┘
```

## 12. Testing Strategy (TDD)

All unit-level, no sockets. Reuse `FakeEngine`-style stubs where a manager is needed.

- **Context:** get/set/has/require (raises)/update/to_dict snapshot independence; `NamespacedView` prefixing; a concurrent-write smoke test (multiple threads set distinct keys → all present, no corruption).
- **DataProfile:** get/default/require.
- **Extract:** each source (json/header/cookie/regex with and without a group/status); required-miss → `ExtractError`; default on optional miss; no-source spec → `ExtractError`.
- **Capture:** manual `capture` writes to context and is strict; `CaptureInterceptor.after_receive` captures present values, swallows+logs misses, returns response unchanged.
- **Template:** substitution in target/header/body; Content-Length recompute after body change; strict miss → `TemplateError`; `strict=False` leaves unknowns; dotted keys; `build_mapping` precedence (data < context < extra).
- **Identity:** `send` delegates to the manager (stub); `render` merges data+ctx with ctx overriding; `capture` writes to `.ctx`; no-manager `send` raises `DataError`.
- **Integration (the headline):** two `Identity` objects sharing one `Context`; A sends (stub manager) → `capture` order_id → B `render`s a `{{order_id}}` request → the rendered request carries the captured value; assert end-to-end.

## 13. Dependencies

- Runtime: none beyond L0–L2 (stdlib `re`, `threading`). Python 3.11+.
- Dev/test: `pytest`, `pytest-asyncio` (already configured).

## 14. Forward Hooks

- L4's attack runner consumes `Identity` (to send authenticated, role-aware requests) and `Context` (to thread captured values between attack steps), and `Extract` to validate/observe responses.
- `CaptureInterceptor` composes with L2's `AuthInterceptor` on the same `Engine` (capture + auth as independent interceptors).
