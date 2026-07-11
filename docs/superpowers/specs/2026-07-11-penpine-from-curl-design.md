# Penpine — `Request.from_curl` (Design Spec)

**Date:** 2026-07-11
**Status:** Approved for implementation planning
**Scope:** Parse a `curl` command string into a `Request`. Sub-project C of Tier 3 (value-first order). HAR import is explicitly deferred to a later cycle.

---

## 1. Context

penpine builds requests from raw bytes, a URL, a `.http` file, or the fluent builder. The one on-ramp missing is the highest-frequency real workflow: **paste a "Copy as cURL" command** from browser devtools or Burp and get a ready-to-send `Request`. This spec adds `Request.from_curl(command)`.

Depends on (all existing):
- L0: `Request`, `Headers`, `Body`, `ConnectionMeta`, `parse_url` (`penpine/core/url.py`), `BuildError` (`penpine/exceptions.py`).
- Loader pattern: `Request.from_raw`/`from_url` are classmethods delegating to `penpine/core/loaders.py`.

**Decisions (this round):**
- `from_curl` only; **HAR import deferred**.
- **Full "Copy as cURL" flag coverage**; multipart `-F/--form` is a documented non-goal.
- **Lenient** parsing: unrecognized flags are ignored (debug-logged), never fatal; transport-only flags are deliberately ignored (they are `Engine` config, not part of a `Request`).
- The result carries **`ConnectionMeta`** (scheme/host/port) so it is immediately sendable.

## 2. Goals & Non-Goals

**Goals**
- `Request.from_curl(command: str) -> Request` handling the flags browsers/Burp emit.
- Robust tokenizing of real output: `$'…'` ANSI-C quoting, `\`-newline continuations, single/double quotes, `--flag=value` and `--flag value`.
- Correct method inference, header/body/cookie/basic-auth construction mirroring curl's defaults.
- `ConnectionMeta` populated from the URL.
- Fully unit-testable; no network.

**Non-Goals (documented follow-ups)**
- HAR import (`load_har`) — next cycle.
- Multipart `-F/--form` bodies — raises a clear `BuildError`.
- Applying transport flags (`-k`, `-x`, `--max-time`, …) to an `Engine` — from_curl produces a `Request` only.
- Windows `cmd.exe` "Copy as cURL (cmd)" quoting (`^` continuations, `"` doubling) — v1 targets the bash form browsers default to.

## 3. Module Layout

```
penpine/core/curl.py     # new — the parser: tokenizer + flag table + parse_curl()
penpine/core/loaders.py  # modified — add thin from_curl(command) delegator
penpine/core/message.py  # modified — add Request.from_curl classmethod
```
All curl-specific logic lives in `curl.py`; `loaders.py` stays thin (matching `from_raw`/`from_url`).

## 4. Public API

```python
# penpine/core/curl.py
def parse_curl(command: str) -> Request: ...

# penpine/core/loaders.py
def from_curl(command: str) -> Request:      # delegates to curl.parse_curl
    from penpine.core.curl import parse_curl
    return parse_curl(command)

# penpine/core/message.py (classmethod on Request)
@classmethod
def from_curl(cls, command: str) -> "Request":
    from penpine.core.loaders import from_curl
    return from_curl(command)
```
No new top-level export beyond the `Request.from_curl` classmethod (consistent with `from_raw`/`from_url`, which are not separately exported).

## 5. Tokenizing (`curl.py`)

`_tokenize(command: str) -> list[str]`:
1. **Line continuations:** remove `\` immediately followed by a newline (join wrapped lines).
2. **ANSI-C `$'…'`:** replace each `$'…'` segment with a plain single-quoted string whose contents have these escapes decoded: `\n \t \r \\ \' \" \xHH \uHHHH` (and `\a \b \f \v`). Other `\x` sequences pass through literally.
3. **shlex:** `shlex.split(preprocessed, posix=True)`.
4. Drop a leading `curl` token if present (tolerated if absent, e.g. a bare copied argument line).

A tokenization failure (`ValueError` from shlex, e.g. unbalanced quotes) raises `BuildError`.

## 6. Flag table & walk

`parse_curl` walks tokens against a classification:

**Value flags (consume an argument; also accept `--long=value`):**
- Modeled: `-X/--request`, `-H/--header`, `-d/--data`, `--data-raw`, `--data-ascii`, `--data-binary`, `--data-urlencode`, `--json` (consumes a value: the JSON body — curl shorthand for `--data <val>` + JSON content-type/accept), `-b/--cookie`, `-A/--user-agent`, `-e/--referer`, `-u/--user`, `--url`.
- Known-ignored (arity tracked so their argument is consumed, not mistaken for the URL): `-x/--proxy`, `--max-time`, `--connect-timeout`, `-m`, `-o/--output`, `-E/--cert`, `--key`, `--cacert`, `--resolve`, `--retry`, `-w/--write-out`, `--limit-rate`, `-r/--range`, `-T/--upload-file`, `--proxy-user`.

**Boolean flags (no argument):**
- Modeled: `-G/--get`, `--compressed`.
- Known-ignored: `-k/--insecure`, `-L/--location`, `-s/--silent`, `-S/--show-error`, `-v/--verbose`, `-i/--include`, `-f/--fail`, `-#/--progress-bar`, `--http1.1`, `--http2`, `-N/--no-buffer`.

**Positional (no leading `-`):** the URL. If more than one positional appears, the first is the URL and the rest are ignored (debug-logged).

**`-F/--form` / `--form-string`:** raise `BuildError("multipart -F/--form is not supported by from_curl; use RequestBuilder.form/multipart")`.

**Unknown flags:** skipped best-effort and debug-logged. `--foo=bar` is self-contained; a bare `--foo` or `-f` is treated as a boolean (its potential argument is left as a positional and, unless it is the first positional taken as the URL, ignored). This residual ambiguity is documented; the known-ignored table covers the common value-carrying flags to prevent URL corruption.

Short-flag clusters are NOT split (`-sS` is treated as one token); browsers emit long or single short flags, and the known-ignored booleans above cover the common single ones. `-sS`-style clusters, if present, fall through to "unknown → boolean" and are harmlessly ignored.

## 7. Building the Request

Given the collected fields:

- **URL** (required): `parse_url(url)` → `ParsedUrl(scheme, host, port, path, query)`.
  - `target = path + ("?" + query if query else "")`.
  - `Host` header = `host` when `port in (80, 443)` else `host:port` (matching `from_url`).
  - `meta = ConnectionMeta(scheme=scheme, host=host, port=port)`.
  - No URL collected → `BuildError("no URL found in curl command")`.

- **Body assembly:**
  - Collect `-d/--data/--data-ascii` (read `@file` as literal is a non-goal — treat the value verbatim; a leading `@` is kept as-is and debug-logged), `--data-raw` (verbatim, leading `@` NOT special), `--data-binary` (verbatim), `--data-urlencode` (percent-encode per curl: `content` → encoded; `name=content` → `name=` + encoded(content)), and `--json` (its value contributes verbatim to the body and additionally sets `is_json`).
  - Multiple data flags are joined with `&` in order (curl semantics).
  - Final body is UTF-8 bytes.

- **method:**
  - explicit `-X/--request` wins;
  - else if `-G/--get` is present → `GET` and the assembled data is appended to the query string (as `?data` or `&data`), body cleared;
  - else if a body is present → `POST`;
  - else `GET`.

- **headers** (order preserved, case preserved), built in this order:
  - each `-H "Name: Value"` in the order given (a `-H "Name;"` form sets an empty-valued header, per curl);
  - `-A/--user-agent` → `User-Agent`;
  - `-e/--referer` → `Referer`;
  - `-b/--cookie` → `Cookie` (value used as-is; `name=value` pairs);
  - `-u/--user user:pass` → `Authorization: Basic base64(user:pass)`;
  - **curl content-type defaults**, applied ONLY if the user did not supply `Content-Type` via `-H`:
    - any `-d/--data*` present → `Content-Type: application/x-www-form-urlencoded`;
    - `--json` → `Content-Type: application/json` **and** `Accept: application/json` (the latter only if no `Accept` given);
  - `Content-Length` set to the body length when a body is present and `Content-Length` was not supplied via `-H`.
  - Explicit `-H` headers take precedence over the derived ones above (if a user passes `-H 'User-Agent: x'` and `-A y`, the `-H` value wins; document the precedence and implement deterministically — derived headers are only added when absent).

- Construct `Request(method, target, "HTTP/1.1", Headers(items), Body(body), meta)`.

## 8. Errors

All via existing `penpine.exceptions.BuildError`:
- no URL found;
- tokenization failure (unbalanced quotes);
- `-F/--form`/`--form-string` used.
Unknown/known-ignored flags never raise.

## 9. Testing Strategy (TDD)

All unit-level, no network.

- **tokenizer:** single/double quotes; `$'\n\t'` ANSI-C decoding; `\`-newline continuation joining; `--header='a: b'` and `--header 'a: b'`; unbalanced quote → `BuildError`.
- **real samples:** a Chrome "Copy as cURL (bash)" GET (multiple `-H`, `-b`, `--compressed`) and a Firefox/Burp POST with `--data-raw` JSON and `$'…'` — assert method, `target`, header set/order, body bytes, and `meta` (scheme/host/port).
- **method inference:** data present + no `-X` → POST; `-G` with data → GET + data in query, empty body; `-X DELETE` honored.
- **auth/cookies/ua/referer:** `-u a:b` → `Authorization: Basic YTpi`; `-b 'k=v'` → `Cookie`; `-A ua` → `User-Agent`; `-e ref` → `Referer`.
- **data flags:** two `-d` joined by `&`; `--data-urlencode 'q=a b&c'` percent-encoded; `--json '{"a":1}'` sets `Content-Type`/`Accept: application/json`.
- **content-type precedence:** explicit `-H 'Content-Type: text/plain'` with `-d` keeps `text/plain` (no override); `Content-Length` derived when absent, preserved when `-H` supplies it.
- **lenient flags:** `-k`, `--compressed`, `-x http://p:8080` (its argument must NOT become the URL), and an invented `--totally-unknown foo` all ignored while the real URL/method/body parse correctly.
- **errors:** empty/no-URL command → `BuildError`; `-F 'a=b'` → `BuildError`.
- **sendability:** the returned `Request.meta` has host+port+scheme set (regression against the "missing host/port" class of bug).

## 10. Dependencies

Runtime: stdlib only (`shlex`, `base64`, `urllib.parse.quote`, `re`). No new dependencies. Python 3.11+.
Dev/test: `pytest` (existing).

## 11. Forward Hooks

- HAR import (`load_har(path_or_str) -> list[Request]`) reuses the same URL/header/body construction helpers; factor the "fields → Request" builder in `curl.py` so HAR can share it (or lift it to `loaders`), rather than duplicating.
- Applying transport flags (`-k` → `TLSConfig(verify=False)`, `-x` → `ProxyConfig`, `--max-time` → `Timeouts`) could later return an optional companion config alongside the `Request`; out of scope now.
