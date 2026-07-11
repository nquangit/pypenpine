import time

import pytest

from penpine.core.message import Request
from penpine.core.parse.http_parser import parse_response
from penpine.transport.pool import ConnectionPool, PoolConfig, _connection_reusable

KEY = ("h", 80, False)


class _PConn:
    def __init__(self):
        self.opened = False
        self._closed = False

    async def open(self):
        self.opened = True
        return self

    async def close(self):
        self._closed = True

    @property
    def closed(self):
        return self._closed


def _factory(created):
    def factory(host, port, **kwargs):
        conn = _PConn()
        created.append(conn)
        return conn

    return factory


def _pool(created, config=None):
    return ConnectionPool(_factory(created), tls=None, proxy=None, timeouts=None, config=config)


def _resp(raw):
    return parse_response(raw)


def test_reusable_content_length():
    req = Request.from_url("http://h/")
    assert _connection_reusable(req, _resp(b"HTTP/1.1 200 OK\r\nContent-Length: 0\r\n\r\n")) is True


def test_reusable_chunked():
    req = Request.from_url("http://h/")
    raw = b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n0\r\n\r\n"
    assert _connection_reusable(req, _resp(raw)) is True


def test_reusable_bodiless_status():
    req = Request.from_url("http://h/")
    assert _connection_reusable(req, _resp(b"HTTP/1.1 204 No Content\r\n\r\n")) is True


def test_not_reusable_connection_close():
    req = Request.from_url("http://h/")
    raw = b"HTTP/1.1 200 OK\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
    assert _connection_reusable(req, _resp(raw)) is False


def test_not_reusable_eof_framed():
    req = Request.from_url("http://h/")
    assert _connection_reusable(req, _resp(b"HTTP/1.1 200 OK\r\n\r\nbody")) is False


def test_not_reusable_http10_without_keepalive():
    req = Request.from_url("http://h/")
    raw = b"HTTP/1.0 200 OK\r\nContent-Length: 0\r\n\r\n"
    assert _connection_reusable(req, _resp(raw)) is False


async def test_acquire_opens_when_empty():
    created = []
    pool = _pool(created)
    conn, reused = await pool.acquire(KEY)
    assert reused is False
    assert conn.opened is True
    assert len(created) == 1


async def test_release_then_acquire_reuses():
    created = []
    pool = _pool(created)
    conn, _ = await pool.acquire(KEY)
    await pool.release(KEY, conn, reusable=True)
    conn2, reused = await pool.acquire(KEY)
    assert conn2 is conn
    assert reused is True
    assert len(created) == 1


async def test_release_non_reusable_closes():
    created = []
    pool = _pool(created)
    conn, _ = await pool.acquire(KEY)
    await pool.release(KEY, conn, reusable=False)
    assert conn.closed is True


async def test_release_over_cap_closes_overflow():
    created = []
    pool = _pool(created, PoolConfig(max_per_host=1))
    a, _ = await pool.acquire(KEY)
    b, _ = await pool.acquire(KEY)
    await pool.release(KEY, a, reusable=True)
    await pool.release(KEY, b, reusable=True)
    assert b.closed is True


async def test_acquire_skips_closed_parked():
    created = []
    pool = _pool(created)
    conn, _ = await pool.acquire(KEY)
    await pool.release(KEY, conn, reusable=True)
    conn._closed = True
    conn2, reused = await pool.acquire(KEY)
    assert reused is False
    assert conn2 is not conn
    assert len(created) == 2


async def test_acquire_evicts_expired():
    created = []
    pool = _pool(created, PoolConfig(idle_timeout=10.0))
    conn, _ = await pool.acquire(KEY)
    await pool.release(KEY, conn, reusable=True)
    dq = pool._idle[KEY]
    parked_conn, _ts = dq[0]
    dq[0] = (parked_conn, time.monotonic() - 100)
    conn2, reused = await pool.acquire(KEY)
    assert reused is False
    assert parked_conn.closed is True
    assert conn2 is not parked_conn


async def test_force_new_ignores_idle():
    created = []
    pool = _pool(created)
    conn, _ = await pool.acquire(KEY)
    await pool.release(KEY, conn, reusable=True)
    conn2, reused = await pool.acquire(KEY, force_new=True)
    assert reused is False
    assert conn2 is not conn
    assert conn.closed is False


async def test_aclose_closes_all_parked():
    created = []
    pool = _pool(created)
    a, _ = await pool.acquire(KEY)
    await pool.release(KEY, a, reusable=True)
    await pool.aclose()
    assert a.closed is True


async def test_open_failure_closes_connection():
    from penpine.transport.exceptions import ConnectError

    class _FailOpen:
        def __init__(self):
            self._closed = False

        async def open(self):
            raise ConnectError("handshake failed")

        async def close(self):
            self._closed = True

        @property
        def closed(self):
            return self._closed

    created = []

    def factory(host, port, **kwargs):
        conn = _FailOpen()
        created.append(conn)
        return conn

    pool = ConnectionPool(factory, tls=None, proxy=None, timeouts=None)
    with pytest.raises(ConnectError):
        await pool.acquire(("h", 80, False))
    assert created[0].closed is True
