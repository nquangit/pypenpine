"""Fluent RequestBuilder."""

from __future__ import annotations

import json as _json

from penpine.core.body.form_body import FormBody
from penpine.core.message import Request
from penpine.exceptions import BuildError


class RequestBuilder:
    def __init__(self):
        self._method = "GET"
        self._url = None
        self._version = "HTTP/1.1"
        self._headers: list[tuple[str, str]] = []
        self._body = b""
        self._content_type = None

    def method(self, m: str) -> RequestBuilder:
        self._method = m
        return self

    def url(self, u: str) -> RequestBuilder:
        self._url = u
        return self

    def version(self, v: str) -> RequestBuilder:
        self._version = v
        return self

    def header(self, name: str, value: str) -> RequestBuilder:
        self._headers.append((name, value))
        return self

    def body(self, data: bytes, content_type: str | None = None) -> RequestBuilder:
        self._body = data if isinstance(data, bytes) else str(data).encode()
        self._content_type = content_type
        return self

    def json(self, obj) -> RequestBuilder:
        self._body = _json.dumps(obj).encode("utf-8")
        self._content_type = "application/json"
        return self

    def form(self, fields: dict) -> RequestBuilder:
        self._body = FormBody(list(fields.items())).to_bytes()
        self._content_type = "application/x-www-form-urlencoded"
        return self

    def build(self) -> Request:
        if not self._url:
            raise BuildError("RequestBuilder requires a url()")
        req = Request.from_url(self._url, method=self._method, version=self._version)
        for name, value in self._headers:
            req = req.add_header(name, value)
        if self._content_type:
            req = req.set_header("Content-Type", self._content_type)
        req = req.with_body(self._body)
        return req
