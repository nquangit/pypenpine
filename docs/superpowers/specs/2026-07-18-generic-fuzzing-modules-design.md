# Generic Fuzzing / Injection Modules — Design

**Date:** 2026-07-18
**Status:** Approved (design), pending implementation plan
**Sub-project:** 2 of 2 (the other, WebSocket client core, is merged)

## Problem

penpine ships four signature attack modules (sqli, xss, traversal, redirect) plus
two differential sqli probers. Coverage is narrow. The user wants **many more
generic modules** that spray diverse edge-case values and probe for a broad set
of vulnerability classes, maximizing variety and coverage — each with a real
detection oracle (not noise).

## Decisions (locked during brainstorming)

Build **six** new generic modules, each a `PayloadGenerator` + `Validator` +
`AttackModule` with its own oracle, wired through the existing analyze → generate
→ send → validate → Report pipeline:

1. **fuzz** — edge/type-value fuzzing → error/anomaly detection (max breadth).
2. **ssti** — template injection → arithmetic-eval oracle.
3. **crlf** — CRLF / header injection → response-header reflection oracle.
4. **ssrf** — cloud-metadata / localhost / file:// probes → passive best-effort.
5. **cmdi** — command injection → command-output reflection oracle.
6. **nosqli** — operator injection → NoSQL-error / anomaly oracle.

New `AttackType`s: `FUZZ`, `SSTI`, `CRLF`, `CMDI`, `NOSQLI` (`SSRF` already exists).
All are **opt-in** — they run only when the operator selects that `AttackType`,
consistent with "attacks are explicit, never automatic".

## Architecture

### Files
- `penpine/attack/modules/fuzz.py`, `ssti.py`, `crlf.py`, `ssrf.py`, `cmdi.py`,
  `nosqli.py` — one module each (`<Name>Generator`, `<Name>Validator`,
  `<NAME>_MODULE`, plus their payload/signature constants as module-level lists so
  callers can extend without subclassing — matching the existing modules).
- `penpine/attack/modules/_common.py` — add `GENERIC_ERROR_SIGNATURES` (compiled
  regexes) + a helper `error_signature(response, baseline, signatures)` returning
  the first signature present in the response but not the baseline.
- `penpine/attack/types.py` — add `FUZZ`, `SSTI`, `CRLF`, `CMDI`, `NOSQLI`.
- `penpine/attack/analyze/rules.py` — add classification rules.
- `penpine/attack/modules/__init__.py` — import + append the six to `BUILTIN_MODULES`.

### Module contract (existing, reused)
Generator: `generate(point, request) -> Iterable[TestCase]` yielding
`TestCase(point=, payload=Payload(value, technique=), attack_type=)`. Validator:
`evaluate(test_case, response, baseline) -> Finding | None`. `AttackModule(name,
gen, val, attack_type=, applies_to=, description=)`. Registered into
`BUILTIN_MODULES`; run by the Runner on points the analyzer tagged for that
attack.

## Component 1 — shared error signatures (`_common.py`)

`GENERIC_ERROR_SIGNATURES`: compiled, case-insensitive regexes for common
server-side error/stack-trace fingerprints across stacks — e.g. `Traceback
(most recent call last)`, `Fatal error:` / `Stack trace:` (PHP),
`java\.lang\.[A-Za-z.]+Exception`, `at [\w.$]+\([\w.]+:\d+\)` (Java frames),
`System\.\w+Exception` (.NET), `\bServerError\b`/`Internal Server Error`,
`SyntaxError:`/`ReferenceError:` (Node), `undefined method .* for` (Ruby),
`ORA-\d{5}`, `SQLSTATE\[`. Kept as a plain list (not exhaustive) that callers can
extend.

Helper:
```python
def error_signature(response, baseline, signatures) -> re.Match | None:
    """Return the first signature present in the response but NOT the baseline."""
    text = body_text(response)
    match = search_signatures(text, signatures)
    if match and baseline is not None and search_signatures(body_text(baseline), signatures):
        return None  # same error class already in baseline -> not attributable
    return match
```

## Component 2 — the six modules

Payload/signature constants are module-level lists (extendable). Random markers
use the existing `marker(prefix)` helper. Each validator takes `baseline` and
suppresses signals present in the baseline.

### fuzz (`FUZZ`)
- **Payloads** (`FUZZ_PAYLOADS`, ~35): `"null"`, `"none"`, `""`, `"0"`, `"1"`,
  `"-1"`, `"true"`, `"false"`, `"NaN"`, `"Infinity"`, a UUID, `str(2**63)`,
  `str(-2**63)`, `str(2**63 - 1)`, `"1e308"`, `"-1e308"`, `"1"*33000`, `"%n%n%n"`,
  `"{{}}"`, `"[]"`, `"{}"`, `"$(:)"`, `"\r\n"`, `"\x00"`, `"../"`, `"🌀"`,
  `"' OR ''='"`, `"<x>"`, a very long numeric, mixed-type tokens. Applies to all
  kinds.
- **Oracle** (`FuzzValidator`): HIGH if `response.status_code >= 500`, or an
  `error_signature(...)` hit; MEDIUM if the status class changed vs baseline
  (baseline 2xx → now 4xx/5xx) or `len(body) >= 3 * len(baseline_body)` (or ≤ 1/3).
  Otherwise `None`. Evidence names the trigger (status/signature/size delta).
- **applies_to**: `()` (all kinds).

### ssti (`SSTI`)
- **Payloads** (`SSTI_TEMPLATES`): for each request, pick random ints `a, b`
  (5–9 digits) with product `p = a*b`, render each template around them:
  `"{{%d*%d}}"`, `"${%d*%d}"`, `"#{%d*%d}"`, `"<%%= %d*%d %%>"`, `"${{%d*%d}}"`,
  `"@(%d*%d)"`. The generator embeds `str(p)` in the payload `meta` so the
  validator knows the expected product.
- **Oracle** (`SstiValidator`): HIGH if `str(p)` is in the body **and** the raw
  expression string (e.g. `"{{a*b}}"`) is **not** (i.e. it was evaluated, not
  reflected verbatim). Reads `p`/expression from `test_case.payload.meta`.
- **applies_to**: `("param", "form", "json", "multipart")`.

### crlf (`CRLF`)
- **Payloads** (`CRLF_TEMPLATES`): a fresh `marker("crlfpp")` per request injected
  via `"%0d%0aX-Penpine-Inj: {m}"`, `"\r\nX-Penpine-Inj: {m}"`,
  `"%E5%98%8A%E5%98%8DX-Penpine-Inj: {m}"` (unicode CRLF), and a `Set-Cookie`
  splitting variant. Marker stored in `meta`.
- **Oracle** (`CrlfValidator`): HIGH if the marker appears as an actual response
  **header** (name or value) — i.e. the CRLF split injected a header. (Checks
  `response.headers` values/names for the marker, not just the body.)
- **applies_to**: `("param", "form", "json", "header")`.

### ssrf (`SSRF`) — best-effort, passive
- **Payloads** (`SSRF_PAYLOADS`): `http://169.254.169.254/latest/meta-data/`,
  `http://169.254.169.254/latest/meta-data/iam/security-credentials/`,
  `http://metadata.google.internal/computeMetadata/v1/`, `http://127.0.0.1/`,
  `http://localhost/`, `http://[::1]/`, `file:///etc/passwd`,
  `http://{canary_host}/`. Constructor arg `canary_host="penpine-oob.example"`
  (swap in a Burp Collaborator domain for manual OOB confirmation).
- **Oracle** (`SsrfValidator`): MEDIUM if the body contains metadata/file
  signatures absent from baseline — e.g. `ami-id`, `instance-id`,
  `computeMetadata`, `"AccessKeyId"`, `root:x:0:0:`; LOW if a `GENERIC_ERROR_SIGNATURES`
  hit suggests the fetch failed server-side. **No out-of-band detection** — OOB is
  the operator's job via `canary_host`; documented as a limitation.
- **applies_to**: `("param", "form", "json", "header")`.

### cmdi (`CMDI`)
- **Payloads** (`CMDI_TEMPLATES`): fresh `marker("cmdi")` per request; separators
  wrap `echo <marker>`: `";echo {m}"`, `"$(echo {m})"`, `"`echo {m}`"`,
  `"|echo {m}"`, `"&&echo {m}"`, `"\n echo {m}"`. Marker in `meta`.
- **Oracle** (`CmdiValidator`): HIGH if the marker is reflected in the body
  (command output executed) **and** the marker isn't part of the sent payload
  echoed verbatim with the separator (i.e. the raw `;echo {m}` string is absent
  but `{m}` present); MEDIUM if a `GENERIC_ERROR_SIGNATURES` hit absent from
  baseline. (Timing-based blind cmdi is out of scope for v1 — a later differential
  module.)
- **applies_to**: `("param", "form", "json", "multipart")`.

### nosqli (`NOSQLI`)
- **Payloads** (`NOSQLI_PAYLOADS`): `"[$ne]="`, `"[$gt]="`, `'{"$ne":null}'`,
  `'{"$gt":""}'`, `"';return true;var x='"`, `"' || '1'=='1"`, `'", $where: "1==1'`.
- **Oracle** (`NosqliValidator`): HIGH if a NoSQL error signature (Mongo/`MongoError`,
  `\$where`, `E11000`, `BSON`) is present and absent from baseline; MEDIUM if the
  status class changed or size delta vs baseline (auth-bypass/behavioral change).
- **applies_to**: `("param", "form", "json")`.

## Component 3 — analyzer rules (`rules.py`)

New `ClassificationRule`s appended to `DEFAULT_RULES`:
- `FuzzRule` → `{FUZZ}` for every point (`match` always returns `{FUZZ}`).
- `TemplateInjectionRule` → `{SSTI}` and `CommandInjectionRule` → `{CMDI}` for
  string-context body points (`param/form/json/multipart` with a non-empty,
  non-numeric value) and search-name points.
- `CrlfRule` → `{CRLF}` for `param/form/json/header` and redirect-name points.
- `NoSqlRule` → `{NOSQLI}` for `param/form/json` (any value; boosted for
  id/user/pass-ish names).
- `SSRF` needs no new rule — the existing `UrlValueRule`, `RedirectNameRule`,
  `HostHeaderRule`, `ProxyHeaderRule` already tag SSRF-relevant points; the new
  `SSRF_MODULE` runs on those.

## Component 4 — registration (`modules/__init__.py`)

Import the six modules and their public constants; append
`FUZZ_MODULE, SSTI_MODULE, CRLF_MODULE, SSRF_MODULE, CMDI_MODULE, NOSQLI_MODULE`
to `BUILTIN_MODULES` (so `register_builtins()` registers them). They are NOT
differential modules, so they stay out of `DIFFERENTIAL_MODULES`.

## Data flow (unchanged)

```
analyze(request) -> points tagged with candidate attack_types (incl. new rules)
Runner(attack=AttackType.FUZZ) -> select FUZZ-tagged points -> FuzzGenerator ->
  send each vs a captured baseline -> FuzzValidator.evaluate(tc, resp, baseline) -> Finding -> Report
```

## Error handling / false positives
- Every validator receives `baseline` and suppresses a signal that also appears
  in the baseline (error signature already present, same status, etc.).
- ssti/cmdi/crlf use a fresh random marker/number per test case, so a positive is
  unambiguous (no baseline needed for those oracles, though baseline is still
  passed).
- The Runner already captures per-attempt errors without aborting the batch
  (unchanged) — a payload that fails to build/send is recorded, not fatal.

## Testing
Per module (`tests/attack/modules/test_<name>.py`):
- Generator yields the expected payloads with the right `attack_type` and (for
  ssti/cmdi/crlf) the marker/product in `meta`.
- Validator: returns a `Finding` (correct confidence) on a crafted true-positive
  response (error sig / eval product / reflected marker / metadata signature);
  returns `None` on a benign response; returns `None` when the same signal is in
  the baseline (false-positive suppression).
Plus:
- `tests/attack/test_types.py` (or existing): the five new `AttackType`s exist and
  round-trip via `AttackType.from_str`.
- `tests/attack/analyze/`: the new rules tag the expected points (e.g. a string
  `param` gets `FUZZ, SSTI, CMDI`; a `header` gets `CRLF`).
- `tests/attack/modules/test_registration.py` (or existing): `register_builtins()`
  registers all six by name.
- One end-to-end `Runner` test per module against a `_FakeSender` returning the
  crafted response → a `Finding` in the `Report`.

## Non-goals / YAGNI
- No timing/blind detection (blind cmdi/ssrf) in v1 — a later differential-module cycle.
- No out-of-band (collaborator) listener — `canary_host` payloads only; OOB
  confirmation is manual.
- No XXE / LDAP / SSJI modules in this cycle (can be added later with the same pattern).
- No change to the Runner, analyzer engine, or Report — additive modules + rules + types only.

## Backward-compatibility notes
- Additive: new modules, new `AttackType`s, new analyzer rules. `register_builtins()`
  now registers more modules (opt-in to run). No existing behavior changes.
