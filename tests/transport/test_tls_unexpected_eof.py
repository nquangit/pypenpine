"""The TLS context must tolerate an unexpected EOF (peer closes without a
close_notify alert).

On OpenSSL 3.x, `sslobj.read()` raises `SSLEOFError: UNEXPECTED_EOF_WHILE_READING`
when the peer closes mid-stream without close_notify — and asyncio's sslproto
drops the already-buffered response with it, so a fully received response is
reported as a failure. This is exactly what happens through some proxies
(Burp) / CDNs (Cloudflare) / with TLS 1.3 tickets. `OP_IGNORE_UNEXPECTED_EOF`
makes the read return EOF (b'') instead of raising, matching curl/browsers.
"""

import contextlib
import ssl
from pathlib import Path

import pytest

from penpine.transport.tls import TLSConfig


def test_context_sets_ignore_unexpected_eof():
    if not hasattr(ssl, "OP_IGNORE_UNEXPECTED_EOF"):
        pytest.skip("OP_IGNORE_UNEXPECTED_EOF not available in this Python/OpenSSL")
    ctx = TLSConfig(verify=False).build_ssl_context()
    assert ctx.options & ssl.OP_IGNORE_UNEXPECTED_EOF


def _self_signed(tmp_path: Path):
    # generate a throwaway cert/key with the stdlib-available openssl
    import subprocess

    cert, key = tmp_path / "c.pem", tmp_path / "k.pem"
    subprocess.run(
        [
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-keyout",
            str(key),
            "-out",
            str(cert),
            "-days",
            "1",
            "-nodes",
            "-subj",
            "/CN=t",
        ],
        check=True,
        capture_output=True,
    )
    return cert, key


def _handshake(client, server, cin, cout, sin, sout):
    for _ in range(30):
        for obj in (client, server):
            with contextlib.suppress(ssl.SSLWantReadError):
                obj.do_handshake()
        if d := cout.read():
            sin.write(d)
        if d := sout.read():
            cin.write(d)
        try:
            client.do_handshake()
            server.do_handshake()
            return
        except ssl.SSLWantReadError:
            continue
    raise AssertionError("handshake did not complete")


def test_ignore_unexpected_eof_returns_eof_instead_of_raising(tmp_path):
    if not hasattr(ssl, "OP_IGNORE_UNEXPECTED_EOF"):
        pytest.skip("OP_IGNORE_UNEXPECTED_EOF not available")
    cert, key = _self_signed(tmp_path)
    sctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    sctx.load_cert_chain(str(cert), str(key))
    cctx = TLSConfig(verify=False).build_ssl_context()  # framework context (has the option)

    sin, sout = ssl.MemoryBIO(), ssl.MemoryBIO()
    cin, cout = ssl.MemoryBIO(), ssl.MemoryBIO()
    server = sctx.wrap_bio(sin, sout, server_side=True)
    client = cctx.wrap_bio(cin, cout, server_hostname="t")
    _handshake(client, server, cin, cout, sin, sout)

    server.write(b"HTTP/1.1 404 Not Found\r\nContent-Length: 0\r\n\r\n")
    rec = sout.read()
    cin.write(rec[: len(rec) // 2])  # feed only HALF the record (truncated)
    cin.write_eof()  # peer closed without close_notify

    # With OP_IGNORE_UNEXPECTED_EOF this returns b'' (clean EOF) instead of raising.
    assert client.read(4096) == b""
