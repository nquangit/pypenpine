"""Engine: high-level send over one-shot connections, with interceptors + retry."""

from __future__ import annotations

import asyncio
import contextlib
import threading

from penpine._sync import run_on_loop
from penpine.transport.connection import Connection
from penpine.transport.exceptions import (
    ConnectError,
    IncompleteResponseError,
    TotalTimeout,
    TransportError,
)
from penpine.transport.interceptor import RetrySignal
from penpine.transport.pool import ConnectionPool, PoolConfig, _connection_reusable
from penpine.transport.timeouts import Timeouts
from penpine.transport.tls import TLSConfig


class Engine:
    def __init__(
        self,
        *,
        tls=None,
        proxy=None,
        interceptors=(),
        timeouts=None,
        max_concurrency=10,
        max_retries=0,
        connection_factory=Connection,
        reuse_connections=False,
        pool=None,
    ):
        self.tls = tls or TLSConfig()
        self.proxy = proxy
        self.interceptors = list(interceptors)
        self.timeouts = timeouts or Timeouts()
        self.max_concurrency = max_concurrency
        self.max_retries = max_retries
        self._connection_factory = connection_factory
        if pool is not None or reuse_connections:
            self._pool = ConnectionPool(
                connection_factory,
                tls=self.tls,
                proxy=self.proxy,
                timeouts=self.timeouts,
                config=pool or PoolConfig(),
            )
        else:
            self._pool = None
        self._loop = None
        self._loop_thread = None

    async def send(self, request):
        try:
            if self.timeouts.total:
                try:
                    return await asyncio.wait_for(self._send(request), self.timeouts.total)
                except TimeoutError as exc:
                    raise TotalTimeout(
                        f"send exceeded total timeout of {self.timeouts.total}s"
                    ) from exc
            return await self._send(request)
        except Exception as exc:
            for ic in reversed(self.interceptors):
                # an error hook must never mask the original failure
                with contextlib.suppress(Exception):
                    await ic.on_error(request, exc)
            raise

    async def _send(self, request):
        meta = request.meta
        if not meta.host or not meta.port:
            raise TransportError(
                "request.meta missing host/port; build via Request.from_url or set meta"
            )
        use_tls = meta.scheme == "https"
        last_resp = None
        for _ in range(self.max_retries + 1):
            req = request
            for ic in self.interceptors:
                req = await ic.before_send(req)
            if self.proxy is not None and self.proxy.scheme.startswith("http") and not use_tls:
                req = req.with_target(f"http://{meta.host}:{meta.port}{req.target}")
            if self._pool is None:
                conn = self._connection_factory(
                    meta.host,
                    meta.port,
                    use_tls=use_tls,
                    tls=self.tls,
                    proxy=self.proxy,
                    timeouts=self.timeouts,
                )
                try:
                    await conn.open()
                    await conn.send_bytes(req.serialize())
                    resp = await conn.read_response(req.method)
                finally:
                    # Teardown is cleanup: a close error (e.g. an OpenSSL 3.x
                    # SSLEOFError from a peer that skips close_notify) must never
                    # mask an already-read response or a genuine send/read error.
                    with contextlib.suppress(Exception):
                        await conn.close()
            else:
                resp = await self._send_pooled((meta.host, meta.port, use_tls), req)
            last_resp = resp
            try:
                for ic in reversed(self.interceptors):
                    resp = await ic.after_receive(req, resp)
                return resp
            except RetrySignal:
                continue
        return last_resp

    async def _send_pooled(self, key, req):
        conn, reused = await self._pool.acquire(key)
        released = False
        try:
            try:
                await conn.send_bytes(req.serialize())
                resp = await conn.read_response(req.method)
            except (ConnectError, IncompleteResponseError, OSError):
                if not reused:
                    raise
                # stale keep-alive: the server reaped the idle conn -> retry once fresh
                await conn.close()
                conn, _ = await self._pool.acquire(key, force_new=True)
                await conn.send_bytes(req.serialize())
                resp = await conn.read_response(req.method)
            await self._pool.release(key, conn, _connection_reusable(req, resp))
            released = True
            return resp
        finally:
            if not released:
                with contextlib.suppress(Exception):
                    await conn.close()

    async def aclose(self):
        if self._pool is not None:
            await self._pool.aclose()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        await self.aclose()

    async def send_many(self, requests, *, return_exceptions=False):
        sem = asyncio.Semaphore(self.max_concurrency)

        async def one(req):
            async with sem:
                return await self.send(req)

        return await asyncio.gather(
            *(one(r) for r in requests), return_exceptions=return_exceptions
        )

    def _ensure_loop(self):
        if self._loop is None:
            self._loop = asyncio.new_event_loop()
            self._loop_thread = threading.Thread(target=self._loop.run_forever, daemon=True)
            self._loop_thread.start()

    def send_sync(self, request):
        self._ensure_loop()
        return run_on_loop(self._loop, self.send(request))

    def send_many_sync(self, requests, *, return_exceptions=False):
        self._ensure_loop()
        return run_on_loop(
            self._loop, self.send_many(requests, return_exceptions=return_exceptions)
        )

    def close(self):
        if self._loop is not None:
            if self._pool is not None:
                asyncio.run_coroutine_threadsafe(self.aclose(), self._loop).result(timeout=2)
            self._loop.call_soon_threadsafe(self._loop.stop)
            self._loop_thread.join(timeout=2)
            self._loop.close()
            self._loop = None
            self._loop_thread = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
