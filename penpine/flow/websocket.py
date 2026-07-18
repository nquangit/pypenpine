"""WebSocket integration for the flow engine: authed connect + flow steps."""

from __future__ import annotations

from penpine.core.message import Request
from penpine.data.template import build_mapping, render_text
from penpine.flow.exceptions import FlowError
from penpine.flow.step import Step
from penpine.transport.websocket import _parse_ws_url, recv_reply, ws_connect


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
    manager = identity.manager if identity is not None else None
    if manager is not None:
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


def ws_open(
    name, url, *, store="ws", identity=None, headers=None, guard=None, **connect_kw
) -> Step:
    async def _action(fc):
        ws = await ws_connect_authed(url, identity=identity, headers=headers, **connect_kw)
        fc.ctx.set(store, ws)
        return None

    return Step(name, action=_action, guard=guard)


def ws_send(
    name,
    message,
    *,
    store="ws",
    capture=None,
    recv=True,
    recv_timeout=5.0,
    recv_count=1,
    binary=False,
    guard=None,
) -> Step:
    async def _action(fc):
        ws = fc.ctx.get(store)
        if ws is None:
            raise FlowError(
                f"ws step {name!r}: no WebSocket connection in context[{store!r}]"
                " (add ws_open first)"
            )
        mapping = build_mapping(context=fc.ctx, data=getattr(fc.actor, "data", None))
        rendered = render_text(message, mapping, strict=False)
        if binary:
            await ws.send_bytes(rendered.encode("utf-8"))
        else:
            await ws.send_text(rendered)
        if not recv:
            return None
        ctype = "application/octet-stream" if binary else "application/json"
        return await recv_reply(
            ws, recv_count=recv_count, recv_timeout=recv_timeout, content_type=ctype
        )

    return Step(name, action=_action, capture=capture, guard=guard)


def ws_close(name, *, store="ws", guard=None) -> Step:
    async def _action(fc):
        ws = fc.ctx.get(store)
        if ws is not None:
            await ws.close()
            fc.ctx.set(store, None)
        return None

    return Step(name, action=_action, guard=guard)
