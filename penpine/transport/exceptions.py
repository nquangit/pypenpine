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


class TransportTimeout(TransportError):
    """Base class for transport timeouts."""


class ReadTimeout(TransportTimeout):
    """A read exceeded its timeout."""


class TotalTimeout(TransportTimeout):
    """A send exceeded its total timeout."""


class IncompleteResponseError(TransportError):
    """Connection ended before a complete response was read."""


class WebSocketError(TransportError):
    """WebSocket protocol error."""


class WebSocketHandshakeError(WebSocketError):
    """The WebSocket upgrade handshake was rejected or invalid."""

    def __init__(self, message: str, response=None):
        super().__init__(message)
        self.response = response
