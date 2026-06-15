# Penpine — L4d: Concrete Attack Modules (Design Spec)

**Date:** 2026-06-13
**Status:** Approved for implementation planning
**Scope:** This spec covers **L4d only** — the built-in attack modules. Fourth and final L4 sub-project; completes the framework.

---

## 1. Context

L4d ships real attack modules (a `PayloadGenerator` + `Validator` + `AttackModule` each) on the L4a contracts, named to match L4b's analyzer tags, so `Runner.run(request, attack="sqli")` fires real payloads end-to-end (L4c).

Depends on:
- L4a: `PayloadGenerator`, `Validator`, `AttackModule`, `TestCase`, `Payload`, `Finding`, `Confidence`, `registry.register`.
- L4b: `penpine.attack.analyze.detectors` (numeric/string tailoring).
- L0: `Response.body.text()`, `Response.headers`, `Response.status_code`.

**Design constraint:** the L4c runner validates each test case **independently** against a baseline (one response + baseline). So v1 modules are **single-response signature detections**; differential attacks (boolean/time SQLi) are deferred (they need a runner extension).

**L4d decisions (this round):**
- Ship four modules: error-based SQLi, reflected XSS, path-traversal/LFI, open-redirect.
- Built-ins via explicit `register_builtins()` (no import-time side effects) + exported instances.
- Payloads and signatures are constructor-injectable with importable defaults.
- Detection is high-confidence with a baseline false-positive guard for signature modules.

## 2. Goals & Non-Goals

**Goals**
- Four working, registered attack modules whose names match analyzer tags (`sqli`, `xss`, `path-traversal`, `open-redirect`).
- Point-aware generators with extensible default payloads; validators with extensible default signatures.
- `register_builtins()` + exported module instances.
- Fully unit-testable with synthetic responses (no network).
- An end-to-end test driving a real finding through the runner.

**Non-Goals (documented follow-ups)**
- Differential SQLi (boolean/time-based) — needs an L4c runner extension (cross-response comparison / latency threading).
- Blind/OOB SSRF (needs out-of-band infrastructure).
- Command injection, SSTI, XXE, etc.

## 3. Module Layout

```
penpine/attack/modules/
  __init__.py     # BUILTIN_MODULES, register_builtins(), instance + constant exports
  _common.py      # marker(), search_signatures(), response body text helper
  sqli.py         # SqliGenerator, SqliValidator, SQLI_PAYLOADS, SQL_ERROR_SIGNATURES, SQLI_MODULE
  xss.py          # XssGenerator, XssValidator, XSS_PAYLOAD_TEMPLATES, XSS_MODULE
  traversal.py    # TraversalGenerator, TraversalValidator, TRAVERSAL_PAYLOADS, TRAVERSAL_SIGNATURES, TRAVERSAL_MODULE
  redirect.py     # RedirectGenerator, RedirectValidator, REDIRECT_PAYLOADS, CANARY_HOST, REDIRECT_MODULE
```

## 4. Shared helpers (`_common.py`)

```python
def marker(prefix: str) -> str          # f"{prefix}_{secrets.token_hex(4)}"
def body_text(response) -> str          # response.body.text() (lenient decode); "" if absent
def search_signatures(text, patterns)   # return the first compiled-regex Match, or None
```

## 5. Modules

Each module: a generator yielding `TestCase`s for a point (point-aware), a validator returning a `Finding` or `None`, default constants, and an `AttackModule` instance. The runner sets `test_case.request` to the sent request before validation, so `Finding`s reference it.

### 5.1 `sqli` — error-based
- **`SQLI_PAYLOADS`** (string-context default): `"'"`, `'"'`, `"')"`, `"';"`, `"' OR '1'='1"`, `"' OR 1=1-- -"`, `"\\"`.
- **Numeric-context payloads** (added when `detectors.is_numeric(point.value)`): `" OR 1=1"`, `"1 OR 1=1"`, `"1) OR (1=1"`.
- **`SqliGenerator(payloads=None, numeric_payloads=None)`**: yields a `TestCase(point, Payload(p, technique="error-based"), attack_type="sqli")` for each applicable payload (string set always; numeric set added when the point value is numeric).
- **`SQL_ERROR_SIGNATURES`** (compiled, `re.I`): e.g. `you have an error in your sql syntax`, `warning.*\bmysqli?_`, `valid MySQL result`, `PostgreSQL.*ERROR`, `pg_query\(\)`, `unterminated quoted string`, `Microsoft SQL Server`, `ODBC SQL Server Driver`, `Unclosed quotation mark`, `ORA-\d{5}`, `quoted string not properly terminated`, `SQLite/JDBCDriver`, `sqlite3\.OperationalError`, `SQL syntax.*error`.
- **`SqliValidator(signatures=None)`**: if `search_signatures(body_text(response), signatures)` matches AND the same does NOT match `body_text(baseline)` (when baseline present) → `Finding("sqli", point, payload, Confidence.HIGH, "SQL error signature: <match>", request=test_case.request, response=response)`; else `None`.
- **`SQLI_MODULE = AttackModule("sqli", SqliGenerator(), SqliValidator(), applies_to=("param","form","json","multipart","cookie"), description="error-based SQL injection")`.**

### 5.2 `xss` — reflected
- **`XSS_PAYLOAD_TEMPLATES`** (each contains `{m}`): `'"><svg/onload=alert({m})>'`, `"'><script>alert({m})</script>"`, `'{m}"\'><x>'`.
- **`XssGenerator(templates=None)`**: for each template, mint `mk = marker("PXSS")`, build `value = template.format(m=mk)`, yield `TestCase(point, Payload(value, technique="reflected"), attack_type="xss", marker=mk)`.
- **`XssValidator()`**: if `test_case.payload.value` appears **verbatim** in `body_text(response)` → reflected unescaped → `Finding("xss", point, payload, Confidence.HIGH, "payload reflected unescaped in response body", request, response)`; else `None`.
- **`XSS_MODULE = AttackModule("xss", XssGenerator(), XssValidator(), applies_to=("param","form","json","multipart"), description="reflected XSS")`.**

### 5.3 `path-traversal` — traversal/LFI
- **`TRAVERSAL_PAYLOADS`**: `"../../../../../../etc/passwd"`, `"....//....//....//etc/passwd"`, `"..\\..\\..\\..\\windows\\win.ini"`, `"%2e%2e%2f%2e%2e%2f%2e%2e%2fetc%2fpasswd"`, `"/etc/passwd"`.
- **`TraversalGenerator(payloads=None)`**: a `TestCase(point, Payload(p, technique="lfi"), attack_type="path-traversal")` per payload.
- **`TRAVERSAL_SIGNATURES`** (compiled): `root:.*:0:0:`, `daemon:.*:/usr/sbin`, `\[(?:extensions|fonts|mci extensions)\]`, `for 16-bit app support`.
- **`TraversalValidator(signatures=None)`**: signature match in body AND not in baseline → `Finding("path-traversal", ..., Confidence.HIGH, "file content signature: <match>", ...)`; else `None`.
- **`TRAVERSAL_MODULE = AttackModule("path-traversal", TraversalGenerator(), TraversalValidator(), applies_to=("param","form","json","path-seg","cookie"), description="path traversal / LFI")`.**

### 5.4 `open-redirect`
- **`CANARY_HOST = "penpine-canary.example"`**; **`REDIRECT_PAYLOADS`**: `f"https://{CANARY_HOST}/"`, `f"//{CANARY_HOST}/"`, `f"https:{CANARY_HOST}"`.
- **`RedirectGenerator(payloads=None)`**: a `TestCase(point, Payload(p, technique="redirect"), attack_type="open-redirect")` per payload.
- **`RedirectValidator(host=CANARY_HOST)`**: if `response.status_code in (301,302,303,307,308)` AND `host in response.headers.get("Location", "")` → `Finding("open-redirect", ..., Confidence.HIGH, "redirect Location to canary: <loc>", ...)`; else `None`.
- **`REDIRECT_MODULE = AttackModule("open-redirect", RedirectGenerator(), RedirectValidator(), applies_to=("param","form","json"), description="open redirect")`.**

## 6. Registration & Public API (`__init__.py`)

```python
BUILTIN_MODULES = [SQLI_MODULE, XSS_MODULE, TRAVERSAL_MODULE, REDIRECT_MODULE]

def register_builtins(*, replace=True) -> None:
    for module in BUILTIN_MODULES:
        register(module, replace=replace)
```
- No import-time registration (importing the package does not mutate the registry).
- Exports the four `*_MODULE` instances, `BUILTIN_MODULES`, `register_builtins`, and the default payload/signature constants.
- `penpine/attack/__init__.py` re-exports `register_builtins` and `BUILTIN_MODULES`.

## 7. Testing Strategy (TDD)

All unit-level, no network. Synthetic `Response`s are built with L0 `parse_response`.

- **sqli:** generator yields the string payloads for a string point and ADDS numeric payloads for a numeric point; validator → `HIGH` finding on a MySQL-error body, `None` on a clean body, `None` when the signature is also in the baseline (false-positive guard); custom `signatures=`/`payloads=` honored.
- **xss:** generator mints unique markers and embeds them; validator → `HIGH` when the payload reflects verbatim, `None` when only an HTML-escaped version is present.
- **traversal:** generator yields traversal payloads; validator → `HIGH` on a `root:x:0:0:` body, `None` on clean, baseline guard.
- **redirect:** validator → `HIGH` on `302` + `Location: https://penpine-canary.example/...`, `None` on `200`, `None` on `302` to a different host.
- **registration:** `register_builtins()` registers all four (`registry.get("sqli")` … resolve); idempotent (calling twice does not raise); no registration occurs merely from importing the package.
- **end-to-end:** `register_builtins()`, then `Runner.run(Request.from_url("http://h/?q=hi'"), attack="sqli", sender=fake)` where the fake returns a SQL-error body for the injected request → `report.findings` contains a `sqli` `HIGH` finding referencing the sent request.

## 8. Dependencies

- Runtime: none beyond L4a/L4b/L0 (stdlib `re`, `secrets`). Python 3.11+.
- Dev/test: `pytest`, `pytest-asyncio` (for the end-to-end runner test).

## 9. Forward Hooks

- Differential SQLi (boolean/time) becomes possible once L4c gains cross-response comparison / latency threading; it would add `sqli`-family modules without changing these.
- Additional signature modules (command-injection, SSTI) follow the exact same pattern (generator + signature validator + `register`).
