"""Transport-layer exceptions."""
from __future__ import annotations

from penpine.exceptions import PenpineError


class TransportError(PenpineError):
    """Base class for transport failures."""


class ConnectError(TransportError):
    """TCP connection could not be established."""


class TLSError(TransportError):
    """TLS handshake or verification failed."""


class ProxyError(TransportError):
    """Proxy negotiation (HTTP CONNECT / SOCKS5) failed."""


class ReadTimeout(TransportError):
    """A read exceeded its timeout."""


class IncompleteResponseError(TransportError):
    """Connection ended before a complete response was read."""
