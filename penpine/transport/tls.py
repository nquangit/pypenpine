"""TLS configuration. Verification is OFF by default (pentest convention)."""

from __future__ import annotations

import ssl
from dataclasses import dataclass


@dataclass
class TLSConfig:
    verify: bool = False
    server_hostname: str | None = None
    min_version: ssl.TLSVersion | None = None
    max_version: ssl.TLSVersion | None = None
    ciphers: str | None = None
    ca_file: str | None = None
    client_cert: tuple[str, str | None] | None = None
    alpn: list[str] | None = None

    def build_ssl_context(self) -> ssl.SSLContext:
        ctx = ssl.create_default_context()
        # Tolerate a peer that closes the TLS connection without a close_notify
        # alert (common through proxies like Burp, via Cloudflare, and with TLS 1.3
        # session tickets left in the pipe). On OpenSSL 3.x the read otherwise
        # raises `SSLEOFError: EOF occurred in violation of protocol`, and asyncio's
        # sslproto drops the already-buffered response bytes with it — so a fully
        # received response is reported as a failure. curl and browsers tolerate
        # this; OP_IGNORE_UNEXPECTED_EOF makes the read return EOF instead of raising.
        if hasattr(ssl, "OP_IGNORE_UNEXPECTED_EOF"):
            ctx.options |= ssl.OP_IGNORE_UNEXPECTED_EOF
        if not self.verify:
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
        elif self.ca_file:
            ctx.load_verify_locations(self.ca_file)
        if self.min_version is not None:
            ctx.minimum_version = self.min_version
        if self.max_version is not None:
            ctx.maximum_version = self.max_version
        if self.ciphers:
            ctx.set_ciphers(self.ciphers)
        if self.client_cert:
            certfile, keyfile = self.client_cert
            ctx.load_cert_chain(certfile, keyfile)
        if self.alpn:
            ctx.set_alpn_protocols(self.alpn)
        return ctx
