"""Engine: high-level send over one-shot connections, with interceptors + retry."""
from __future__ import annotations

from penpine.transport.connection import Connection
from penpine.transport.exceptions import TransportError
from penpine.transport.interceptor import RetrySignal
from penpine.transport.timeouts import Timeouts
from penpine.transport.tls import TLSConfig


class Engine:
    def __init__(self, *, tls=None, proxy=None, interceptors=(), timeouts=None,
                 max_concurrency=10, max_retries=0, connection_factory=Connection):
        self.tls = tls or TLSConfig()
        self.proxy = proxy
        self.interceptors = list(interceptors)
        self.timeouts = timeouts or Timeouts()
        self.max_concurrency = max_concurrency
        self.max_retries = max_retries
        self._connection_factory = connection_factory

    async def send(self, request):
        meta = request.meta
        if not meta.host or not meta.port:
            raise TransportError(
                "request.meta missing host/port; build via Request.from_url or set meta")
        use_tls = meta.scheme == "https"
        last_resp = None
        for _ in range(self.max_retries + 1):
            req = request
            for ic in self.interceptors:
                req = await ic.before_send(req)
            if (self.proxy is not None
                    and self.proxy.scheme.startswith("http") and not use_tls):
                req = req.with_target(f"http://{meta.host}:{meta.port}{req.target}")
            conn = self._connection_factory(
                meta.host, meta.port, use_tls=use_tls, tls=self.tls,
                proxy=self.proxy, timeouts=self.timeouts)
            await conn.open()
            try:
                await conn.send_bytes(req.serialize())
                resp = await conn.read_response(req.method)
            finally:
                await conn.close()
            last_resp = resp
            try:
                for ic in reversed(self.interceptors):
                    resp = await ic.after_receive(req, resp)
                return resp
            except RetrySignal:
                continue
        return last_resp
