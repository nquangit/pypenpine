# Penpine — L0: HTTP Message Core (Design Spec)

**Date:** 2026-06-13
**Status:** Approved for implementation planning
**Scope:** This spec covers **L0 only** — the HTTP message core. L1–L4 are out of scope and each get their own spec→plan→build cycle.

---

## 1. Context

Penpine is a Python pentesting framework built as a **layered library** (not a CLI). Users write Python code against it. The layers, built bottom-up:

| Layer | Subsystem |
|---|---|
| **L0** | HTTP message core — model, parse, serialize, locate *(this spec)* |
| L1 | Transport engine — raw socket + stdlib `ssl`, proxy, concurrency |
| L2 | Session & Auth — session manager, auth providers/profiles, triggers, refresh scheduler |
| L3 | Data & context — data profiles, runtime shared data bus |
| L4 | Attack framework — injection analyzer, payload generators, attack modules, runner, validation |

**Foundational decisions already made (apply across the project):**
- Transport: raw `socket` + stdlib `ssl` (no requests/httpx/urllib). *(L1)*
- Protocol scope: HTTP/1.1 only for v1.
- Concurrency: async core + synchronous facade. *(L1)*
- Build order: bottom-up from L0.

## 2. Goals & Non-Goals (L0)

**Goals**
- A **byte-faithful**, **immutable** `Request`/`Response` model that preserves header order, casing, duplicates, and exact body bytes.
- Parse a request/response from raw bytes, a string, or a file; build one programmatically.
- Convenient parsed views (`headers`, `json`, `form`, `multipart`, query params, cookies) without sacrificing wire fidelity.
- A **locator DSL** to address and replace any sub-part of a request — the seam L4's injection analysis consumes.
- Round-trip invariant: `parse(raw).serialize() == raw` byte-for-byte for well-formed input.
- Robust error handling (typed exceptions with byte-offset context) and a shared colored logger.
- Zero network code. Fully unit-testable offline.

**Non-Goals (deferred to later layers)**
- Sockets, TLS, proxying, connection handling, concurrency (L1).
- HTTP/2, auth/session, data profiles, attacks (L1–L4).
- Persistence/storage of requests beyond in-memory model + file loaders.

## 3. Package Layout

Import name: `penpine`.

```
penpine/
  __init__.py
  logging.py            # get_logger(), colored leveled console handler
  exceptions.py         # PenpineError hierarchy
  core/
    __init__.py
    message.py          # HttpMessage (base), Request, Response
    headers.py          # Headers: ordered, multi-valued, case-preserving
    url.py              # Target/URL parsing + query params
    cookies.py          # Cookie parsing (request Cookie / response Set-Cookie view)
    body/
      __init__.py
      base.py           # Body: raw bytes + lazy typed views
      json_body.py      # JSON view
      form_body.py      # application/x-www-form-urlencoded view
      multipart_body.py # multipart/form-data view
    parse/
      __init__.py
      http_parser.py    # raw bytes -> Request/Response (request/status line, headers)
      framing.py        # body framing: Content-Length / Transfer-Encoding: chunked
    serialize.py        # Request -> bytes
    builder.py          # RequestBuilder (fluent)
    locator.py          # Locator DSL: resolve / replace / enumerate
    loaders.py          # from_file / from_raw / from_url
```

## 4. Data Model

### 4.1 `HttpMessage` (base)
Common to requests and responses: `version`, `headers: Headers`, `body: Body`, `.raw` (exact original bytes when parsed; `None` if built programmatically until serialized), `.serialize() -> bytes`.

### 4.2 `Request` (immutable)
Fields:
- `method: str`
- `target: str` — raw request-target exactly as on the wire (origin-form `/path?q`, absolute-form, authority-form all preserved).
- `version: str` — e.g. `"HTTP/1.1"`.
- `headers: Headers`
- `body: Body`
- `meta: ConnectionMeta` — `scheme` (`http`/`https`), `host`, `port`. Separate from `target` because the wire target is often origin-form and carries no host. Populated by loaders (`from_url`) or the builder; used by L1 to know where to connect.

Immutability: all mutators return a **new** `Request`. Core mutators:
- `clone() -> Request`
- `with_method(m)`, `with_target(t)`, `with_version(v)`
- `with_headers(headers)`, plus header conveniences `set_header`, `add_header`, `remove_header` (each returns a copy with a new `Headers`)
- `with_body(body_or_bytes)`
- `set_param(name, value)` — query param (returns copy with rebuilt `target`)
- `set_form_field(name, value)`, `set_json(path, value)` — return copies with rebuilt body
- `replace_at(locator, value) -> Request` — generic locator-driven replacement
- `locate(expr) -> ResolvedLocator`
- `injection_candidates() -> list[ResolvedLocator]`

**Content-Length policy:** when a mutation changes the body, `Content-Length` is **auto-recomputed**, UNLESS the request was created/flagged with `preserve_content_length=True` (deliberate mismatch for smuggling). `Transfer-Encoding: chunked` bodies are never auto-length'd.

### 4.3 `Response` (immutable)
- `status_code: int`, `reason: str`, `version`, `headers`, `body`.
- Convenience: `.cookies` (parsed `Set-Cookie` view), `.json`/`.form` via `body`.

### 4.4 `Headers`
- Backed by an ordered list of `(name: str, value: str)` pairs. Preserves **insertion order, original casing, and duplicates** for serialization.
- Case-insensitive lookup API: `__getitem__(name)` (first match), `get(name, default)`, `get_all(name) -> list[str]`, `__contains__`, `items()`, `names()`.
- Mutators return new `Headers`: `set(name, value)` (replace all of that name with one), `add(name, value)` (append, keep duplicates), `remove(name)`.
- Lenient parse may yield malformed pairs (e.g. missing colon) preserved as raw lines flagged in warnings; serialization re-emits them verbatim.

### 4.5 `Body`
- Always stores `raw: bytes`.
- Lazy typed views, parsed on first access from `raw`, cached:
  - `.json` → `JsonBody` (parsed object; supports JSONPath get/set; re-serializes to bytes)
  - `.form` → `FormBody` (ordered multidict of urlencoded fields; re-serializes)
  - `.multipart` → `MultipartBody` (ordered parts with headers + content; re-serializes with boundary)
  - `.text(encoding)` → decoded string
- Content type is sniffed from the owning message's `Content-Type` header when available; a view can also be requested explicitly.
- Rebuilding a body from a mutated view produces new `raw` bytes; the original `raw` is never mutated in place.

### 4.6 `url.py` / `cookies.py`
- `url.py`: parse a target/URL into scheme/host/port/path/query; ordered query multidict; rebuild target string. Used by `from_url`, `set_param`, and `meta` population.
- `cookies.py`: parse request `Cookie:` header into an ordered name/value view; parse response `Set-Cookie` headers into structured cookies (name, value, attributes). Read-oriented in L0; L2 owns the cookie jar.

## 5. Locator System

The seam between L0 and L4. A locator is a string expression naming a sub-part of a request.

**Grammar (v1):**
```
param:<name>            # query string parameter
header:<name>           # header value (first match)
header:<name>[<i>]      # i-th duplicate header
cookie:<name>           # request cookie value
json:<jsonpath>         # body JSON node (full JSONPath, via jsonpath-ng)
form:<name>             # urlencoded form field
multipart:<name>        # multipart field (by name)
path-seg:<i>            # i-th path segment of the target
raw:<start>-<end>       # raw byte range of the full serialized request
method | target | version   # request-line components
```

**API:**
- `req.locate(expr) -> ResolvedLocator` — resolves expr against `req`; raises `LocatorError` if not present.
- `ResolvedLocator`: `.kind`, `.name`, `.value` (current value), `.exists`, `.replace(new_value) -> Request` (returns a new request with that spot replaced).
- `req.replace_at(expr_or_locator, value) -> Request` — convenience.
- `req.injection_candidates(kinds=None) -> list[ResolvedLocator]` — enumerates every addressable point (all params, headers, cookies, json leaves, form fields, multipart fields, path segments). L4 filters these into injection points + candidate attack types.

**JSONPath isolation:** `jsonpath-ng` is the *only* third-party dependency and is used *only* inside `locator.py` / `json_body.py`. Everything else stays dependency-free, preserving the "self-contained parsers" goal across the rest of the library.

## 6. Parsing & Serialization

### 6.1 Parsing modes
- **Lenient (default):** preserve whatever bytes arrive — malformed headers, LF-only line endings, odd casing/whitespace, duplicate headers. Anomalies are recorded as warnings on the parsed object (`req.parse_warnings`) rather than raised. This is the default because pentest workflows routinely load intercepted/hand-crafted requests.
- **Strict (opt-in):** `from_raw(x, strict=True)` raises `ParseError`/`MalformedRequestError` on any RFC violation.

### 6.2 `http_parser.py`
- Splits start-line, header block (to `CRLF CRLF`, lenient also accepts `LF LF`), and body.
- Parses request-line (`METHOD SP target SP version`) or status-line (`version SP code SP reason`).
- Emits `Headers` preserving order/casing/duplicates.
- Records exact byte offsets for each component (used by `raw:` locator and error context).

### 6.3 `framing.py`
- Determines body length: `Content-Length`, or `Transfer-Encoding: chunked` (decodes chunks; preserves the raw chunked bytes too), or none.
- Chunked decoder yields both the decoded body and original framing so serialization can round-trip.

### 6.4 `serialize.py`
- Rebuilds bytes: start-line + headers (verbatim pairs) + `CRLF CRLF` + body bytes.
- **Invariant:** for well-formed input parsed in lenient mode with no mutations, `serialize()` returns the original bytes exactly.
- Applies the Content-Length policy from §4.2 when the body was mutated.

## 7. Loaders & Builder

- `Request.from_raw(data: str | bytes, *, strict=False, scheme=None, host=None, port=None) -> Request`
- `Request.from_file(path, *, strict=False, ...) -> Request` — reads a saved raw request (e.g. Burp export).
- `Request.from_url(url, *, method="GET", headers=None, body=None) -> Request` — convenience constructor; populates `meta`.
- `RequestBuilder` — fluent: `.method().url().header().json().form().multipart().version().build()`. Validates required pieces, populates `meta`, computes `Content-Length` unless told otherwise.

## 8. Errors & Logging

**Exception hierarchy (`exceptions.py`):**
```
PenpineError
├── ParseError              # generic parse failure (carries byte offset + snippet)
│   ├── MalformedRequestError
│   └── BodyParseError      # json/form/multipart view parse failures
├── LocatorError            # bad expr or target not present
└── BuildError              # invalid RequestBuilder usage
```
Each carries human-readable context and, where applicable, a byte offset into the source.

**Logging (`logging.py`):**
- `get_logger(name) -> logging.Logger` wrapping stdlib `logging`.
- Colored, leveled console handler (DEBUG→ERROR), concise single-line format with logger name.
- Library never configures the root logger on import; a `configure_logging(level=...)` helper is provided for users. No logging side effects at import time.
- Every module obtains its logger via `get_logger(__name__)`.

## 9. Data Flow

```
            from_raw / from_file / from_url / RequestBuilder
                              │
                              ▼
                       Request (immutable, raw-preserving)
                              │
         ┌────────────────────┼─────────────────────┐
         ▼                    ▼                     ▼
  locate()/candidates   parsed views          serialize() -> bytes
  (L4 injection)      (.headers/.json/...)     (handed to L1 transport)

  socket bytes (L1) ──► http_parser ──► Response (immutable)
```

## 10. Testing Strategy (TDD)

Tests are written first, per task. Core suites:

- **Round-trip fidelity:** `parse(raw).serialize() == raw` across a corpus (simple GET, POST form, POST json, multipart, chunked, duplicate headers, mixed-case headers, LF-only line endings, absolute-form target).
- **Headers:** order/casing/duplicate preservation; case-insensitive lookup; `get_all`; mutators return copies.
- **Body views:** json/form/multipart parse + mutate + re-serialize; lazy + cached; raw never mutated.
- **Locator:** resolve every grammar form; `replace` correctness; `injection_candidates` enumeration completeness; `LocatorError` on missing targets; JSONPath get/set.
- **Content-Length policy:** auto-recompute on mutation; `preserve_content_length` keeps a deliberate mismatch; chunked untouched.
- **Parsing modes:** lenient preserves+warns on malformed input; strict raises with offset context.
- **Loaders/builder:** from_file/from_raw/from_url; builder validation and `meta` population.
- **Immutability:** every mutator returns a new object; original unchanged.
- **Logging:** no import-time side effects; `get_logger` returns configured logger.

## 11. Dependencies

- Runtime: `jsonpath-ng` (isolated to locator/json view) — the only third-party runtime dependency in L0.
- Dev/test: `pytest`.
- Stdlib only otherwise. Python 3.11+.

## 12. Open Questions / Forward Hooks

- `meta`/`ConnectionMeta` is defined here but consumed by L1; L0 only populates it.
- `cookies.py` is read-only in L0; the stateful cookie jar belongs to L2.
- `injection_candidates()` returns raw locator handles; L4 layers attack-type classification on top — no attack knowledge leaks into L0.
```
