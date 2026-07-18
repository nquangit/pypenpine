"""Run the attack pipeline over WebSocket messages.

A WS message is modeled as a Request (JSON body -> json:$.* injection points, or
text -> a single `body` point). `WebSocketSender` is a duck-typed Runner sender:
it opens a WebSocket, sends the (mutated) message as a frame, reads the reply, and
returns a synthetic Response so the existing validators/modules work unchanged.
"""

from __future__ import annotations

from urllib.parse import urlsplit

from penpine.attack.models import InjectionPoint
from penpine.core.message import Request
from penpine.transport.websocket import recv_reply, ws_connect


def ws_message_request(url: str, message: str, *, json: bool = True) -> Request:
    parts = urlsplit(url)
    host = parts.hostname or "ws-target"
    port = parts.port or (443 if parts.scheme == "wss" else 80)
    target = (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
    ctype = "application/json" if json else "text/plain"
    body = message.encode("utf-8")
    raw = (
        f"POST {target} HTTP/1.1\r\nHost: {host}:{port}\r\n"
        f"Content-Type: {ctype}\r\nContent-Length: {len(body)}\r\n\r\n"
    ).encode("latin-1") + body
    scheme = "https" if parts.scheme == "wss" else "http"
    return Request.from_raw(raw, scheme=scheme, host=host, port=port)


def ws_injection_points(request) -> list[InjectionPoint]:
    cands = request.injection_candidates(kinds=("json",))
    if cands:
        return [InjectionPoint.from_locator(c) for c in cands]
    return [InjectionPoint(expr="body", kind="body", name="", value=request.body.text())]


class WebSocketSender:
    """Duck-typed Runner sender that delivers each (mutated) message over a fresh
    WebSocket connection and returns the reply as a synthetic Response."""

    def __init__(
        self,
        url,
        *,
        headers=None,
        subprotocols=None,
        tls=None,
        proxy=None,
        timeouts=None,
        prelude=(),
        recv_count=1,
        recv_timeout=5.0,
        binary=False,
    ):
        self._url = url
        self._connect_kw = {
            "headers": headers,
            "subprotocols": subprotocols,
            "tls": tls,
            "proxy": proxy,
            "timeouts": timeouts,
        }
        self._prelude = list(prelude)
        self._recv_count = recv_count
        self._recv_timeout = recv_timeout
        self._binary = binary

    async def send(self, request):
        ws = await ws_connect(self._url, **self._connect_kw)
        try:
            for m in self._prelude:
                await ws.send_text(m)
            message = request.body.text()
            if self._binary:
                await ws.send_bytes(message.encode("utf-8"))
            else:
                await ws.send_text(message)
            ctype = "application/octet-stream" if self._binary else "application/json"
            return await recv_reply(
                ws, recv_count=self._recv_count, recv_timeout=self._recv_timeout, content_type=ctype
            )
        finally:
            await ws.close()


def _ws_run(url, message, attack, json, points, sender, max_concurrency, sender_kw, *, sync):
    from penpine.attack.modules import register_builtins
    from penpine.attack.runner import Runner

    register_builtins()  # idempotent; ensures the chosen attack resolves to a module
    request = ws_message_request(url, message, json=json)
    pts = points if points is not None else ws_injection_points(request)
    active = sender if sender is not None else WebSocketSender(url, **sender_kw)
    runner = Runner(sender=active, max_concurrency=max_concurrency)
    if sync:
        return runner.run_sync(request, attack=attack, points=pts)
    return runner.run(request, attack=attack, points=pts)


async def run_ws_attack(
    url, message, attack, *, json=True, points=None, sender=None, max_concurrency=10, **sender_kw
):
    """Run `attack` (an AttackType or list) over a WebSocket `message`, returning a Report.

    JSON messages are fuzzed per field (`json:$.*`); pass `json=False` to fuzz the
    whole message via the `body` locator. Calls `register_builtins()` (idempotent,
    replaces builtins by name — a builtin you intentionally unregistered will be
    restored). Extra kwargs go to `WebSocketSender` (`headers`, `proxy`, `prelude`,
    `recv_count`, `recv_timeout`, `binary`); bump `recv_count` when the server sends
    an ack frame before the real reply, or the reply may collapse to the ack.
    """
    return await _ws_run(
        url, message, attack, json, points, sender, max_concurrency, sender_kw, sync=False
    )


def run_ws_attack_sync(
    url, message, attack, *, json=True, points=None, sender=None, max_concurrency=10, **sender_kw
):
    return _ws_run(
        url, message, attack, json, points, sender, max_concurrency, sender_kw, sync=True
    )
