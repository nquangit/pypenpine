"""The `penpine run` command: fire attacks at a request from the CLI."""

from __future__ import annotations

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
