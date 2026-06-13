"""Immutable HTTP message model."""
from __future__ import annotations

from dataclasses import dataclass, field, replace

from penpine.core.body.base import Body
from penpine.core.headers import Headers
from penpine.core.meta import ConnectionMeta
from penpine.core.url import set_query_param


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

    def serialize(self) -> bytes:
        from penpine.core.serialize import serialize_request
        return serialize_request(self)

    def to_bytes(self) -> bytes:
        return self.serialize()

    def with_method(self, method: str) -> "Request":
        return self.clone(method=method, raw=None)

    def with_target(self, target: str) -> "Request":
        return self.clone(target=target, raw=None)

    def with_version(self, version: str) -> "Request":
        return self.clone(version=version, raw=None)

    def with_headers(self, headers: Headers) -> "Request":
        return self.clone(headers=headers, raw=None)

    def set_header(self, name: str, value: str) -> "Request":
        return self.clone(headers=self.headers.set(name, value), raw=None)

    def add_header(self, name: str, value: str) -> "Request":
        return self.clone(headers=self.headers.add(name, value), raw=None)

    def remove_header(self, name: str) -> "Request":
        return self.clone(headers=self.headers.remove(name), raw=None)

    def with_body(self, body) -> "Request":
        new_body = body if isinstance(body, Body) else Body(body, self.body.content_type)
        headers = self.headers
        if not self.preserve_content_length and "Transfer-Encoding" not in headers:
            headers = headers.set("Content-Length", str(len(new_body.raw)))
        return self.clone(body=new_body, headers=headers, raw=None)

    def set_param(self, name: str, value: str) -> "Request":
        return self.with_target(set_query_param(self.target, name, value))

    def set_form_field(self, name: str, value: str) -> "Request":
        return self.with_body(self.body.form.set(name, value).to_bytes())

    def set_json(self, path: str, value) -> "Request":
        return self.with_body(self.body.json.set(path, value).to_bytes())

    def locate(self, expr: str):
        from penpine.core.locator import locate
        return locate(self, expr)

    def replace_at(self, expr_or_locator, value) -> "Request":
        from penpine.core.locator import ResolvedLocator
        if isinstance(expr_or_locator, ResolvedLocator):
            return expr_or_locator.replace(value)
        return self.locate(expr_or_locator).replace(value)

    def injection_candidates(self, kinds=None):
        from penpine.core.locator import enumerate_candidates
        return enumerate_candidates(self, kinds)


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
