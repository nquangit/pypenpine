"""Immutable HTTP message model."""
from __future__ import annotations

from dataclasses import dataclass, field, replace

from penpine.core.body.base import Body
from penpine.core.headers import Headers
from penpine.core.meta import ConnectionMeta


def _coerce_body(body) -> Body:
    if isinstance(body, Body):
        return body
    if body is None:
        return Body(b"")
    return Body(body)


@dataclass(frozen=True)
class Request:
    method: str
    target: str
    version: str = "HTTP/1.1"
    headers: Headers = field(default_factory=Headers)
    body: Body = field(default_factory=lambda: Body(b""))
    meta: ConnectionMeta = field(default_factory=ConnectionMeta)
    preserve_content_length: bool = False
    parse_warnings: tuple[str, ...] = ()
    raw: bytes | None = None

    def __post_init__(self):
        object.__setattr__(self, "body", _coerce_body(self.body))

    def clone(self, **changes) -> "Request":
        return replace(self, **changes)


@dataclass(frozen=True)
class Response:
    status_code: int
    reason: str = ""
    version: str = "HTTP/1.1"
    headers: Headers = field(default_factory=Headers)
    body: Body = field(default_factory=lambda: Body(b""))
    parse_warnings: tuple[str, ...] = ()
    raw: bytes | None = None

    def __post_init__(self):
        object.__setattr__(self, "body", _coerce_body(self.body))
