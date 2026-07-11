"""Opt-in HTTP/1.1 connection pool for the transport Engine."""

from __future__ import annotations

import asyncio
import time
from collections import deque
from dataclasses import dataclass


@dataclass
class PoolConfig:
    max_per_host: int = 8
    idle_timeout: float = 30.0


def _connection_reusable(request, response) -> bool:
    resp_conn = (response.headers.get("Connection") or "").lower()
    req_conn = (request.headers.get("Connection") or "").lower()
    if "close" in resp_conn or "close" in req_conn:
        return False
    if getattr(response, "version", "HTTP/1.1") == "HTTP/1.0" and "keep-alive" not in resp_conn:
        return False
    if response.headers.get("Content-Length") is not None:
        return True
    if "chunked" in (response.headers.get("Transfer-Encoding") or "").lower():
        return True
    return response.status_code in (204, 304) or request.method.upper() == "HEAD"


class ConnectionPool:
    def __init__(self, connection_factory, *, tls, proxy, timeouts, config=None):
        self._factory = connection_factory
        self._tls = tls
        self._proxy = proxy
        self._timeouts = timeouts
        self._config = config or PoolConfig()
        self._idle: dict[tuple, deque] = {}
        self._lock = asyncio.Lock()

    async def _open(self, key):
        host, port, use_tls = key
        conn = self._factory(
            host, port, use_tls=use_tls, tls=self._tls, proxy=self._proxy, timeouts=self._timeouts
        )
        await conn.open()
        return conn

    async def acquire(self, key, *, force_new=False):
        if not force_new:
            stale = []
            winner = None
            async with self._lock:
                dq = self._idle.get(key)
                if dq:
                    now = time.monotonic()
                    while dq:
                        conn, released = dq.popleft()
                        expired = bool(self._config.idle_timeout) and (
                            now - released > self._config.idle_timeout
                        )
                        if conn.closed or expired:
                            stale.append(conn)
                            continue
                        winner = conn
                        break
            for conn in stale:
                await conn.close()
            if winner is not None:
                return winner, True
        return await self._open(key), False

    async def release(self, key, conn, reusable):
        if not reusable or conn.closed:
            await conn.close()
            return
        to_close = None
        async with self._lock:
            dq = self._idle.setdefault(key, deque())
            if len(dq) >= self._config.max_per_host:
                to_close = conn
            else:
                dq.append((conn, time.monotonic()))
        if to_close is not None:
            await to_close.close()

    async def aclose(self):
        async with self._lock:
            conns = [conn for dq in self._idle.values() for (conn, _ts) in dq]
            self._idle.clear()
        for conn in conns:
            await conn.close()
