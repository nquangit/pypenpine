import pytest
from penpine.transport.proxy import ProxyConfig
from penpine.transport.stream import FakeByteStream
from penpine.transport.exceptions import ProxyError


def test_from_url_http_with_creds():
    p = ProxyConfig.from_url("http://user:pass@127.0.0.1:8080")
    assert p.scheme == "http"
    assert p.host == "127.0.0.1"
    assert p.port == 8080
    assert p.username == "user"
    assert p.password == "pass"


def test_from_url_socks5_defaults_port():
    p = ProxyConfig.from_url("socks5://10.0.0.1")
    assert p.scheme == "socks5"
    assert p.port == 1080


async def test_http_connect_success_sends_connect_and_consumes_headers():
    proxy_reply = b"HTTP/1.1 200 Connection Established\r\nX-Proxy: y\r\n\r\n"
    stream = FakeByteStream(proxy_reply)

    async def opener(host, port):
        assert (host, port) == ("127.0.0.1", 8080)
        return stream

    p = ProxyConfig.from_url("http://127.0.0.1:8080")
    out = await p.establish(opener, "target.com", 443)
    assert out is stream
    assert stream.sent.startswith(b"CONNECT target.com:443 HTTP/1.1\r\n")
    assert b"Host: target.com:443\r\n" in bytes(stream.sent)


async def test_http_connect_failure_raises():
    stream = FakeByteStream(b"HTTP/1.1 403 Forbidden\r\n\r\n")

    async def opener(host, port):
        return stream

    p = ProxyConfig.from_url("http://127.0.0.1:8080")
    with pytest.raises(ProxyError):
        await p.establish(opener, "target.com", 443)


async def test_socks5_no_auth_success():
    reply = b"\x05\x00" + b"\x05\x00\x00\x01" + b"\x00\x00\x00\x00\x00\x00"
    stream = FakeByteStream(reply)

    async def opener(host, port):
        return stream

    p = ProxyConfig.from_url("socks5://127.0.0.1:1080")
    out = await p.establish(opener, "target.com", 80)
    assert out is stream
    assert stream.sent.startswith(b"\x05\x01\x00")
    assert b"\x05\x01\x00\x03\x0atarget.com" in bytes(stream.sent)


async def test_socks5_connect_failure_raises():
    reply = b"\x05\x00" + b"\x05\x01\x00\x01" + b"\x00\x00\x00\x00\x00\x00"
    stream = FakeByteStream(reply)

    async def opener(host, port):
        return stream

    p = ProxyConfig.from_url("socks5://127.0.0.1:1080")
    with pytest.raises(ProxyError):
        await p.establish(opener, "target.com", 80)


async def test_establish_closes_stream_on_handshake_failure():
    stream = FakeByteStream(b"HTTP/1.1 403 Forbidden\r\n\r\n")

    async def opener(host, port):
        return stream

    p = ProxyConfig.from_url("http://127.0.0.1:8080")
    with pytest.raises(ProxyError):
        await p.establish(opener, "target.com", 443)
    assert stream.closed
