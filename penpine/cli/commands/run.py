"""The `penpine run` command: fire attacks at a request from the CLI."""

from __future__ import annotations

import sys

from penpine.cli.exceptions import CliError

_AUTHORIZED_REMINDER = "penpine run: for authorized targets only."


def _build_request(curl=None, request_file=None, url=None, target=None):
    from penpine.core.message import Request
    from penpine.core.url import parse_url
    from penpine.exceptions import BuildError

    provided = [
        flag for flag, val in (("--curl", curl), ("--request", request_file), ("--url", url)) if val
    ]
    if len(provided) != 1:
        raise CliError("provide exactly one of --curl, --request, --url")

    try:
        if curl:
            req = Request.from_curl(curl)
        elif url:
            req = Request.from_url(url)
        else:
            if not target:
                raise CliError("--request requires --target for connection info")
            u = parse_url(target)
            req = Request.from_file(request_file, scheme=u.scheme, host=u.host, port=u.port)
    except CliError:
        raise
    except FileNotFoundError as exc:
        raise CliError(f"request file not found: {request_file}") from exc
    except BuildError as exc:
        raise CliError(f"could not build request: {exc}") from exc

    if not (req.meta.host and req.meta.port):
        raise CliError("request has no connection target; use --target or a full URL")
    return req


def _resolve_attacks(attacks="all"):
    from penpine.attack import registry
    from penpine.attack.exceptions import AttackConfigError
    from penpine.attack.modules import BUILTIN_MODULES, register_builtins

    register_builtins()
    known = [m.name for m in BUILTIN_MODULES]
    if attacks == "all":
        return list(known)

    names = [n.strip() for n in attacks.split(",") if n.strip()]
    if not names:
        raise CliError("no attacks selected")
    for name in names:
        try:
            registry.get(name)
        except AttackConfigError as exc:
            raise CliError(f"unknown attack {name!r}; registered: {', '.join(known)}") from exc
    return names


def _format_report(name, report):
    summary = report.summary()
    lines = [
        f"== {name} ==  sent {summary['sent']}  "
        f"failed {summary['failed']}  found {summary['found']}"
    ]
    for finding in report.findings:
        lines.append(f"  [{finding.confidence.name}] {finding.point.expr} -> {finding.evidence}")
    return "\n".join(lines)


def _dry_run(request, names):
    from penpine.attack import registry
    from penpine.attack.analyze import analyze

    analysis = analyze(request)
    for name in names:
        module = registry.get(name)
        points = [p for p in analysis.for_attack(name) if module.applies(p.kind)]
        print(f"would attack ({name}):")
        if not points:
            print("  (no applicable injection points)")
            continue
        for point in points:
            count = len(list(module.generate(point, request)))
            print(f"  {point.expr}   {count} payloads")
    print("(dry-run: nothing sent)")
    return 0


def _parse_proxy(proxy):
    if not proxy:
        return None
    from penpine.transport.proxy import ProxyConfig

    try:
        return ProxyConfig.from_url(proxy)
    except ValueError as exc:
        raise CliError(f"invalid --proxy {proxy!r}: {exc}") from exc


def _execute(request, names, *, fail_on_findings, proxy_config, insecure, concurrency, sender):
    from penpine.attack.runner import Runner

    print(_AUTHORIZED_REMINDER, file=sys.stderr)

    own_engine = None
    if sender is None:
        from penpine.transport.engine import Engine
        from penpine.transport.tls import TLSConfig

        own_engine = Engine(
            tls=TLSConfig(verify=not insecure),
            proxy=proxy_config,
            max_concurrency=concurrency,
        )
        sender = own_engine

    runner = Runner(sender=sender, max_concurrency=concurrency)
    total_found = 0
    try:
        for name in names:
            report = runner.run_sync(request, attack=name)
            total_found += len(report.findings)
            print(_format_report(name, report))
    finally:
        runner.close()
        if own_engine is not None:
            own_engine.close()

    return 1 if (fail_on_findings and total_found > 0) else 0


def run(
    *,
    curl=None,
    request_file=None,
    url=None,
    target=None,
    attacks="all",
    dry_run=False,
    fail_on_findings=False,
    proxy=None,
    insecure=False,
    concurrency=10,
    sender=None,
):
    request = _build_request(curl=curl, request_file=request_file, url=url, target=target)
    names = _resolve_attacks(attacks)
    if concurrency < 1:
        raise CliError("--concurrency must be a positive integer")
    if dry_run:
        return _dry_run(request, names)
    proxy_config = _parse_proxy(proxy)
    return _execute(
        request,
        names,
        fail_on_findings=fail_on_findings,
        proxy_config=proxy_config,
        insecure=insecure,
        concurrency=concurrency,
        sender=sender,
    )
