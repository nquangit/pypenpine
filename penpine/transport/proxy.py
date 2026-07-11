"""Proxy support: HTTP CONNECT and SOCKS5, hand-rolled over a ByteStream."""

from __future__ import annotations

import base64
import struct
from dataclasses import dataclass

from penpine.transport.exceptions import ProxyError


@dataclass
class ProxyConfig:
    scheme: str
    host: str
    port: int
    username: str | None = None
    password: str | None = None

    @classmethod
    def from_url(cls, url: str) -> ProxyConfig:
        scheme, _, rest = url.partition("://")
        scheme = scheme.lower()
        creds = None
        authority = rest
        if "@" in rest:
            creds, authority = rest.rsplit("@", 1)
        host, _, port_s = authority.partition(":")
        default = 1080 if scheme.startswith("socks") else 8080
        port = int(port_s) if port_s else default
        username = password = None
        if creds:
            username, _, password = creds.partition(":")
        return cls(
            scheme=scheme,
            host=host,
            port=port,
            username=username or None,
            password=password or None,
        )

    async def establish(self, open_stream, target_host: str, target_port: int):
        stream = await open_stream(self.host, self.port)
        try:
            if self.scheme == "socks5":
                await _socks5_connect(
                    stream, target_host, target_port, self.username, self.password
                )
            else:
                await _http_connect(stream, target_host, target_port, self.username, self.password)
        except BaseException:
            await stream.close()
            raise
        return stream


async def _http_connect(stream, host, port, username, password) -> None:
    lines = [f"CONNECT {host}:{port} HTTP/1.1", f"Host: {host}:{port}"]
    if username is not None:
        token = base64.b64encode(f"{username}:{password or ''}".encode()).decode()
        lines.append(f"Proxy-Authorization: Basic {token}")
    stream.write(("\r\n".join(lines) + "\r\n\r\n").encode())
    await stream.drain()
    status_line = await stream.readline()
    parts = status_line.split(b" ")
    if len(parts) < 2 or not parts[1].startswith(b"2"):
        raise ProxyError(f"HTTP CONNECT failed: {status_line!r}")
    while True:
        line = await stream.readline()
        if line in (b"\r\n", b"\n", b""):
            break


async def _socks5_connect(stream, host, port, username, password) -> None:
    if username is not None:
        stream.write(b"\x05\x02\x00\x02")
    else:
        stream.write(b"\x05\x01\x00")
    await stream.drain()
    greeting = await stream.readexactly(2)
    if greeting[0:1] != b"\x05":
        raise ProxyError("SOCKS5: bad version in greeting reply")
    method = greeting[1]
    if method == 0x02:
        if username is None:
            raise ProxyError("SOCKS5: server requires auth but no credentials given")
        u = username.encode()
        p = (password or "").encode()
        stream.write(b"\x01" + bytes([len(u)]) + u + bytes([len(p)]) + p)
        await stream.drain()
        auth = await stream.readexactly(2)
        if auth[1] != 0x00:
            raise ProxyError("SOCKS5: authentication failed")
    elif method != 0x00:
        raise ProxyError(f"SOCKS5: no acceptable auth method ({method:#x})")
    host_b = host.encode()
    stream.write(b"\x05\x01\x00\x03" + bytes([len(host_b)]) + host_b + struct.pack("!H", port))
    await stream.drain()
    reply = await stream.readexactly(4)
    if reply[1] != 0x00:
        raise ProxyError(f"SOCKS5: connect failed (code {reply[1]:#x})")
    atyp = reply[3]
    if atyp == 0x01:
        await stream.readexactly(4 + 2)
    elif atyp == 0x03:
        ln = (await stream.readexactly(1))[0]
        await stream.readexactly(ln + 2)
    elif atyp == 0x04:
        await stream.readexactly(16 + 2)
