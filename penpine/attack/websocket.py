"""Run the attack pipeline over WebSocket messages.

A WS message is modeled as a Request (JSON body -> json:$.* injection points, or
text -> a single `body` point). `WebSocketSender` is a duck-typed Runner sender:
it opens a WebSocket, sends the (mutated) message as a frame, reads the reply, and
returns a synthetic Response so the existing validators/modules work unchanged.
"""

from __future__ import annotations

import asyncio
from urllib.parse import urlsplit

from penpine.attack.models import InjectionPoint
from penpine.core.body.base import Body
from penpine.core.headers import Headers
from penpine.core.message import Request, Response
from penpine.transport.websocket import ws_connect


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
        replies: list[str] = []
        try:
            for m in self._prelude:
                await ws.send_text(m)
            message = request.body.text()
            if self._binary:
                await ws.send_bytes(message.encode("utf-8"))
            else:
                await ws.send_text(message)
            for _ in range(self._recv_count):
                try:
                    msg = await asyncio.wait_for(ws.recv(), self._recv_timeout)
                except TimeoutError:
                    break
                if msg.kind == "close":
                    break
                replies.append(
                    msg.data if isinstance(msg.data, str) else msg.data.decode("utf-8", "replace")
                )
        finally:
            await ws.close()
        ctype = "application/octet-stream" if self._binary else "application/json"
        return Response(
            status_code=200,
            reason="OK",
            headers=Headers([("Content-Type", ctype)]),
            body=Body("".join(replies).encode("utf-8")),
        )
