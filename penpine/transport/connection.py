"""A persistent transport connection: open (direct/proxy/TLS), send, read."""
from __future__ import annotations

from penpine.transport.reader import ResponseReader
from penpine.transport.stream import open_asyncio_stream
from penpine.transport.timeouts import Timeouts
from penpine.transport.tls import TLSConfig


class Connection:
    def __init__(self, host, port, *, use_tls=False, tls=None, proxy=None,
                 timeouts=None, stream_opener=None):
        self.host = host
        self.port = port
        self.use_tls = use_tls
        self.tls = tls or TLSConfig()
        self.proxy = proxy
        self.timeouts = timeouts or Timeouts()
        self._opener = stream_opener or open_asyncio_stream
        self._stream = None

    async def open(self) -> "Connection":
        if self.proxy is not None and (self.proxy.scheme == "socks5" or self.use_tls):
            async def open_to(host, port):
                return await self._opener(host, port, self.timeouts)
            self._stream = await self.proxy.establish(open_to, self.host, self.port)
        elif self.proxy is not None:
            # plain HTTP via HTTP proxy: connect to the proxy directly (no CONNECT);
            # the Engine sends the request in absolute-form.
            self._stream = await self._opener(self.proxy.host, self.proxy.port, self.timeouts)
        else:
            self._stream = await self._opener(self.host, self.port, self.timeouts)
        if self.use_tls:
            ctx = self.tls.build_ssl_context()
            await self._stream.start_tls(ctx, self.tls.server_hostname or self.host)
        return self

    async def send_bytes(self, data: bytes) -> None:
        self._stream.write(data)
        await self._stream.drain()

    async def read_response(self, method: str = "GET"):
        return await ResponseReader.read(self._stream, request_method=method)

    async def close(self) -> None:
        if self._stream is not None and not self._stream.closed:
            await self._stream.close()

    @property
    def closed(self) -> bool:
        return self._stream is None or self._stream.closed

    async def __aenter__(self):
        return await self.open()

    async def __aexit__(self, *exc):
        await self.close()
