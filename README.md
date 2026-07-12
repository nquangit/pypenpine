# penpine

A layered, production-grade Python pentesting framework — built entirely on raw
sockets and the standard library, with **no third-party HTTP client** (no
`requests`, `httpx`, or `urllib`). penpine parses and serializes HTTP itself,
byte-for-byte, so you have total control over every request you send.

penpine is a **library you write code against**, not a numeric-menu CLI. You
load or build a request, pick an attack type, and let the framework analyze the
request, generate the right payloads, insert them, send them concurrently, and
validate the responses into findings.

```python
from penpine import Runner, Request
from penpine.attack.modules import register_builtins

register_builtins()
report = Runner().run_sync(
    Request.from_url("http://target/item?id=7&q=hello"),
    attack="sqli",
)
for f in report.findings:
    print(f.confidence.name, f.point.expr, "→", f.evidence)
```

---

## Why penpine

- **No HTTP library.** A hand-written HTTP/1.1 parser and serializer over raw
  `socket` + stdlib `ssl`. Requests round-trip byte-exactly; you can craft
  malformed requests on purpose.
- **Concurrent by design.** An `asyncio` core for both transport and the attack
  runner, each with a synchronous facade (`*_sync`) so you never have to touch
  `await` if you don't want to.
- **Fully customizable requests.** Build from a URL, a raw byte string, a `.http`
  file, or a fluent builder. Mutate any part and re-serialize.
- **Injection-point intelligence.** penpine enumerates every injectable location
  in a request (query params, form fields, JSON values, cookies, path segments,
  headers) and tags each with the attack types it's a candidate for.
- **Extensible attacks.** Built-in modules for error-based SQLi, reflected XSS,
  path traversal/LFI, and open redirect — or bring your own payloads, your own
  test cases, or your own `AttackModule`.
- **Auth, sessions, and identities.** Login providers, automatic 401 re-login,
  a proactive token-refresh scheduler that suspends in-flight sends during
  refresh, and per-role identities that can share captured data at runtime.
- **Clean throughout.** A typed exception hierarchy, a configurable logger, and
  OOP seams (interceptors, schemes, providers, rules, modules) everywhere you'd
  want to extend it.

## Install

Requires **Python 3.11+**. The only runtime dependency is `jsonpath-ng` (for
JSON-body locators).

```bash
pip install -e .            # from a checkout
pip install -e ".[dev]"     # with pytest + pytest-asyncio for the test suite
```

## Architecture

penpine is built in layers; each is independently usable and tested.

| Layer | Package | Responsibility |
|------|---------|----------------|
| **L0** | `penpine.core` | Byte-faithful `Request`/`Response`, HTTP parser/serializer, headers, body views, the locator DSL, builders/loaders |
| **L1** | `penpine.transport` | `Engine` — raw-socket async send, TLS, HTTP/SOCKS5 proxy, interceptors |
| **L2** | `penpine.auth` | Sessions, auth schemes, login providers, refresh gate/scheduler, `SessionManager`, `AuthProfile` |
| **L3** | `penpine.data` | Thread-safe `Context` bus, extractors/capture, `{{ }}` templating, cross-role `Identity` |
| **L4a–b** | `penpine.attack`, `penpine.attack.analyze` | Attack contracts + registry; the injection-point analyzer |
| **L4c** | `penpine.attack.runner` | `Runner` — analyze → generate → send → validate → `Report` |
| **L4d** | `penpine.attack.modules` | Concrete SQLi / XSS / path-traversal / open-redirect modules |

---

## L0 — Crafting requests

Load a request however you have it:

```python
from penpine import Request, RequestBuilder

# From a URL
req = Request.from_url("https://target/api/users?id=7")

# From a raw HTTP byte string (round-trips byte-for-byte)
req = Request.from_raw(
    b"POST /login HTTP/1.1\r\n"
    b"Host: target\r\n"
    b"Content-Type: application/json\r\n"
    b"Content-Length: 26\r\n\r\n"
    b'{"user":"ann","pw":"hunter"}'
)

# From a saved .http file
req = Request.from_file("requests/login.http")

# With the fluent builder
req = (RequestBuilder()
       .method("POST").url("https://target/search")
       .header("X-Test", "1")
       .json({"q": "hello"})
       .build())
```

Every request is immutable; mutators return a copy:

```python
req2 = req.with_method("PUT").with_target("/api/users/8")
raw  = req2.serialize()          # -> bytes, exactly what goes on the wire
```

### The locator DSL

Address any part of a request with a string expression, then read or replace it:

```python
req.locate("param:id")           # query parameter `id`
req.locate("json:$.user")        # JSON body field via JSONPath
req.locate("header:Host")        # a header
req.locate("cookie:session")     # a cookie value
req.locate("path-seg:2")         # the 3rd path segment

attacked = req.replace_at("param:id", "7 OR 1=1")
```

And enumerate every injectable location automatically:

```python
for loc in req.injection_candidates():
    print(loc.kind, loc.name, "=", loc.value)
```

## L1 — Sending over raw sockets

The `Engine` opens its own TCP/TLS connections. TLS verification is **off by
default** (you're testing targets, often with self-signed certs).

```python
from penpine import Engine

engine = Engine()
resp = engine.send_sync(req)         # synchronous
print(resp.status_code, resp.body.text())
engine.close()

# async
async def go():
    engine = Engine()
    try:
        resp = await engine.send(req)
        resps = await engine.send_many([req1, req2, req3])   # bounded concurrency
    finally:
        engine.close()
```

Configure TLS, proxies, timeouts, and interceptors:

```python
from penpine.transport.tls import TLSConfig
from penpine.transport.proxy import ProxyConfig

engine = Engine(
    tls=TLSConfig(verify=False),
    proxy=ProxyConfig.from_url("http://127.0.0.1:8080"),   # route through Burp/ZAP
)
```

## L2 — Auth, sessions, and refresh

Describe how to log in (a **provider**) and how to carry auth on each request
(a **scheme**), and bundle them into an `AuthProfile`.

```python
from penpine import AuthProfile
from penpine.auth import JsonLoginProvider, BearerAuth

profile = AuthProfile(
    name="admin",
    provider=JsonLoginProvider(
        url="https://target/login",
        payload={"user": "admin", "pw": "s3cr3t"},
        token_path="$.access_token",
    ),
    scheme=BearerAuth(),
)

mgr = profile.manager()              # a SessionManager
resp = mgr.send_sync(req)            # logs in lazily, attaches the token
```

The `SessionManager` automatically re-logs in on a `401`, and a
`RefreshScheduler` can proactively refresh a token *before* it expires —
suspending all in-flight sends through a `RefreshGate` barrier while it does,
then resuming them with the new credentials. Schemes cover Bearer, Basic,
Cookie, arbitrary Header, and `MultiScheme` combinations.

## L3 — Identities and runtime data sharing

An `Identity` wraps an auth profile plus a data context. Capture values out of
one identity's responses and template them into another's requests — e.g. user
A creates a resource, user B tries to access it (IDOR testing).

```python
from penpine import Identity

alice = Identity("alice", auth_profile=alice_profile)
bob   = Identity("bob",   auth_profile=bob_profile)

resp = alice.send_sync(create_req)
alice.capture(resp, {"new_id": "json:$.id"})      # extract into context

probe = bob.render(Request.from_url("https://target/doc/{{new_id}}"))
print(bob.send_sync(probe).status_code)           # 200 == IDOR
```

## Flows — multi-step scenarios

Chain requests into an ordered scenario with per-step guards and step-local
recovery. Steps share one flow-scoped context, so one actor's captured data
templates into another's request.

```python
from penpine import Flow, Step, Request
from penpine.data.extract import Extract
from penpine.flow import Recovery

activation = Flow(actor=user, steps=[
    Step("activate", request=activate_req),
])

flow = Flow(actor=user, steps=[
    Step("login", request=login_req,
         capture=[Extract("token", json="$.access_token")],
         recovery=Recovery(
             when=lambda o: o.response is not None and o.response.status_code == 409,
             do=activation, retry=True)),
    Step("transfer", request=Request.from_url("http://bank/xfer?tok={{token}}")),
])

result = flow.run_sync()
print(result.summary())              # {'ran': 2, 'skipped': 0, 'recovered': 0, 'failed': 0}
for step in result:
    print(step.step, step.status)
```

A step may name its own `actor` (any `Identity`/`SessionManager`/`Engine`), so a
flow can drive multiple identities against one shared context — the basis for
cross-user (IDOR) scenarios. By default a flow **fails fast**: the first
unrecovered step raises `StepError` with the partial `FlowResult` attached;
pass `continue_on_error=True` to record errors and keep going. Session-expiry
re-login is handled underneath by the L2 `SessionManager`, not the flow.

## L4 — Analyze, attack, validate

### Inspect what an attack would target

```python
from penpine.attack.analyze import analyze

analysis = analyze(Request.from_url("http://t/p?id=7&q=hi&next=http://e.com"))
for p in analysis:
    print(p.expr, p.attack_types)
# param:id   ('idor', 'sqli')
# param:q    ('sqli', 'xss')
# param:next ('open-redirect', 'sqli', 'ssrf', 'xss')

analysis.for_attack("sqli")          # just the SQLi-candidate points
```

### Run an attack end-to-end

`Runner.run` (async) / `run_sync` analyzes the request, selects the points the
analyzer tagged for the chosen attack, generates payloads, sends everything
concurrently against a captured baseline, and validates each response.

```python
from penpine import Runner
from penpine.attack.modules import register_builtins

register_builtins()                  # registers sqli / xss / path-traversal / open-redirect

report = Runner().run_sync(req, attack="sqli")

print(report.summary())              # {'sent': N, 'failed': 0, 'found': M}
for f in report.findings:
    print(f.confidence.name, f.attack_type, f.point.expr, "→", f.evidence)
```

Send through an authenticated identity by passing it as the `sender` (anything
exposing `async send(request)` works — `Engine`, `SessionManager`, `Identity`):

```python
report = Runner(sender=alice).run_sync(req, attack="xss")
```

### Bring your own payloads, test cases, or module

```python
# Override the points the analyzer chose:
report = Runner().run_sync(req, attack="sqli", points=analyze(req).all())

# Supply explicit test cases with your own validator:
report = Runner().run_sync(req, test_cases=my_cases, validator=my_validator)
```

A full custom attack is a `PayloadGenerator` + `Validator` wrapped in an
`AttackModule` and `register()`-ed — the built-in modules in
`penpine/attack/modules/` are the reference pattern. Both generators (payload
lists) and validators (signature lists) take their defaults as constructor
arguments, so you can extend a built-in without subclassing it.

---

## Logging

```python
from penpine import configure_logging
configure_logging(level="DEBUG")     # structured, namespaced loggers under `penpine.*`
```

## Exceptions

Everything derives from `penpine.exceptions.PenpineError`, with focused
subclasses per layer (`ParseError`, `MalformedRequestError`, `LocatorError`,
transport errors, `AuthError`, `AttackConfigError`, …) so callers can catch
broadly or narrowly. The attack `Runner` never raises out of a batch — every
send/build/validator failure is captured on its own `Attempt.error`, so one bad
test case never aborts the run.

## Testing

```bash
pytest                # ~400 tests (1 opt-in slow), no network required
```

The whole suite runs against synthetic requests/responses and fake senders — no
sockets, no live targets.

## Development

Install the dev toolchain and the pre-commit hooks:

    pip install -e ".[dev]"
    pre-commit install

Run the same checks CI runs:

    ruff check . && ruff format --check .   # lint + format (gating)
    mypy penpine                            # type check (advisory)
    pytest --cov=penpine                    # tests + coverage

## Status & roadmap

All eight layers (L0–L4d) are built, reviewed, and merged, plus these
capabilities:

- **`Request.from_curl(cmd)`** — paste a "Copy as cURL" command and get a
  ready-to-send request (meta populated).
- **Transport timeouts** — `read` (whole-response deadline) and `total`
  (whole-send ceiling) are enforced (`ReadTimeout`/`TotalTimeout`); connect was
  already wired.
- **Connection pooling / keep-alive** — opt-in via `Engine(reuse_connections=True)`
  (default off), keyed by host/port/tls with per-host idle cap + eviction.
- **Differential (blind) SQLi** — boolean-based (`Runner.run(attack="sqli-boolean")`)
  and time-based (`"sqli-time"`) via an active-prober Runner extension; registered
  by name, kept out of the default signature module set.

Documented follow-ups not yet implemented:

- **Attacks:** blind/OOB SSRF and command-injection modules (signature pattern);
  boolean data-exfiltration and Oracle/SQLite time payloads (extend the
  differential prober).
- **Transport:** global connection cap / LRU eviction (per-host cap ships today).

## Legal

penpine is for **authorized** security testing, CTFs, and education only. Only
test systems you own or have explicit written permission to assess.
