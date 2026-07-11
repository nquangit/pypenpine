from penpine.transport.connection import Connection
from penpine.transport.proxy import ProxyConfig
from penpine.transport.stream import FakeByteStream
from penpine.transport.tls import TLSConfig


def make_opener(stream):
    async def opener(host, port, timeouts=None):
        opener.calls.append((host, port))
        return stream

    opener.calls = []
    return opener


async def test_direct_open_send_read():
    stream = FakeByteStream(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nok")
    opener = make_opener(stream)
    conn = Connection("h", 80, stream_opener=opener)
    await conn.open()
    await conn.send_bytes(b"GET / HTTP/1.1\r\nHost: h\r\n\r\n")
    resp = await conn.read_response("GET")
    assert resp.status_code == 200
    assert stream.sent.startswith(b"GET /")
    assert opener.calls == [("h", 80)]
    await conn.close()
    assert conn.closed


async def test_tls_upgrade_called_with_sni():
    stream = FakeByteStream(b"HTTP/1.1 200 OK\r\nContent-Length: 0\r\n\r\n")
    conn = Connection(
        "secure.test", 443, use_tls=True, tls=TLSConfig(), stream_opener=make_opener(stream)
    )
    await conn.open()
    assert stream.tls_calls == ["secure.test"]


async def test_proxy_tunnels_to_target():
    stream = FakeByteStream(b"HTTP/1.1 200 Connection Established\r\n\r\n")
    opener = make_opener(stream)
    proxy = ProxyConfig.from_url("http://127.0.0.1:8080")
    conn = Connection("target.com", 443, use_tls=True, proxy=proxy, stream_opener=opener)
    await conn.open()
    assert opener.calls == [("127.0.0.1", 8080)]
    assert bytes(stream.sent).startswith(b"CONNECT target.com:443")
    assert stream.tls_calls == ["target.com"]
