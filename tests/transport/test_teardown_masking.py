"""A connection-teardown error must never mask a successfully-read response.

Regression: over TLS on OpenSSL 3.x, a peer that closes without a `close_notify`
makes the TLS shutdown read raise `SSLEOFError` during `conn.close()`. That close
runs in `_send`'s `finally`, so the error propagated out and turned every
already-received response into a failure (the operator saw the full request AND
response in their proxy, but penpine reported SSLEOFError for all of them).
"""

import ssl

import pytest

from penpine.core.message import Request
from penpine.core.parse.http_parser import parse_response
from penpine.transport.engine import Engine
from penpine.transport.exceptions import ConnectError

_OK = b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nok"


class _TeardownRaises:
    """Reads a good response, then raises on close (models the TLS shutdown EOF)."""

    def __init__(self, host, port, **kw):
        pass

    async def open(self):
        return self

    async def send_bytes(self, data):
        return None

    async def read_response(self, method="GET"):
        return parse_response(_OK)

    async def close(self):
        raise ssl.SSLEOFError("EOF occurred in violation of protocol (_ssl.c:2580)")


async def test_teardown_error_does_not_mask_a_good_response():
    engine = Engine(connection_factory=_TeardownRaises)
    resp = await engine.send(Request.from_url("http://h/x"))
    assert resp.status_code == 200
    assert resp.body.raw == b"ok"


class _SendFailsAndCloseRaises(_TeardownRaises):
    async def send_bytes(self, data):
        raise ConnectError("connection refused")


async def test_real_error_still_propagates_even_if_close_also_raises():
    # A genuine send/read failure must still surface; the teardown error must not
    # replace it, and suppressing the close must not swallow the real error.
    engine = Engine(connection_factory=_SendFailsAndCloseRaises)
    with pytest.raises(ConnectError):
        await engine.send(Request.from_url("http://h/x"))
