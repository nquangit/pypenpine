"""WebSocket integration for the flow engine: authed connect + flow steps."""

from __future__ import annotations

from penpine.core.message import Request
from penpine.transport.websocket import _parse_ws_url, ws_connect


async def ws_connect_authed(
    url, *, identity=None, session=None, scheme=None, headers=None, **connect_kw
):
    """`ws_connect` with an auth session applied to the handshake. Lifts any
    header a scheme adds (Authorization/Cookie/custom) onto the WS handshake;
    explicit `headers` win over lifted ones."""
    ws_scheme, host, port, target = _parse_ws_url(url)
    http = "https" if ws_scheme == "wss" else "http"
    dummy = Request.from_url(f"{http}://{host}:{port}{target}")

    authed = dummy
    if identity is not None:
        manager = identity.manager
        await manager.ensure_fresh()
        authed = manager.apply(dummy)
    elif session is not None and scheme is not None:
        authed = scheme.apply(dummy, session)

    explicit = {n.lower() for n, _ in (headers or [])}
    before = {(n.lower(), v) for n, v in dummy.headers.items()}
    lifted = [
        (n, v)
        for n, v in authed.headers.items()
        if (n.lower(), v) not in before and n.lower() not in explicit
    ]
    merged = list(headers or []) + lifted
    return await ws_connect(url, headers=merged or None, **connect_kw)
