"""AsyncioByteStream.close() must abort a TLS transport rather than close it
gracefully.

A graceful close() drives asyncio's SSL shutdown *flush that reads* (sslproto
`_do_flush` -> `_do_read`), which raises `SSLEOFError` on OpenSSL 3.x when the
peer skips `close_notify` (common through proxies like Burp / with TLS 1.3
tickets in the pipe). That teardown error then masked every already-received
response. Aborting skips the shutdown read entirely; a one-shot connection we
never reuse gains nothing from a graceful close_notify handshake.
"""

from penpine.transport.stream import AsyncioByteStream


class _FakeTransport:
    def __init__(self, *, tls: bool):
        self._tls = tls
        self.aborted = False

    def get_extra_info(self, key):
        if key == "ssl_object":
            return object() if self._tls else None
        return None

    def abort(self):
        self.aborted = True


class _FakeWriter:
    def __init__(self, transport):
        self.transport = transport
        self.close_called = False

    def close(self):
        self.close_called = True

    async def wait_closed(self):
        return None


async def test_tls_stream_close_aborts_and_skips_graceful_close():
    transport = _FakeTransport(tls=True)
    writer = _FakeWriter(transport)
    stream = AsyncioByteStream(reader=None, writer=writer)  # type: ignore[arg-type]
    await stream.close()
    assert transport.aborted is True  # aborted -> no reading TLS shutdown
    assert writer.close_called is False
    assert stream.closed is True


async def test_plain_stream_close_uses_graceful_close():
    transport = _FakeTransport(tls=False)
    writer = _FakeWriter(transport)
    stream = AsyncioByteStream(reader=None, writer=writer)  # type: ignore[arg-type]
    await stream.close()
    assert transport.aborted is False
    assert writer.close_called is True  # plain HTTP keeps a graceful close


async def test_close_is_resilient_when_transport_missing():
    writer = _FakeWriter(None)
    stream = AsyncioByteStream(reader=None, writer=writer)  # type: ignore[arg-type]
    await stream.close()  # must not raise even with no transport
    assert writer.close_called is True
    assert stream.closed is True
