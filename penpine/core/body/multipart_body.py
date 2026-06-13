"""multipart/form-data body view (raw-preserving per-part content)."""
from __future__ import annotations

import re
from dataclasses import dataclass

from penpine.exceptions import BodyParseError

_NAME_RE = re.compile(rb'name="([^"]*)"')


@dataclass(frozen=True)
class Part:
    name: str
    headers: bytes
    content: bytes


class MultipartBody:
    def __init__(self, boundary: str, parts: list[Part]):
        self._boundary = boundary
        self._parts = parts

    @staticmethod
    def _boundary_from_ct(content_type: str | None) -> str:
        if not content_type or "boundary=" not in content_type:
            raise BodyParseError("multipart content-type without boundary")
        return content_type.split("boundary=", 1)[1].strip().strip('"')

    @classmethod
    def from_bytes(cls, raw: bytes, content_type: str | None) -> "MultipartBody":
        boundary = cls._boundary_from_ct(content_type)
        delim = b"--" + boundary.encode()
        parts: list[Part] = []
        for chunk in raw.split(delim):
            chunk = chunk.strip(b"\r\n")
            if not chunk or chunk == b"--":
                continue
            head, _, content = chunk.partition(b"\r\n\r\n")
            m = _NAME_RE.search(head)
            name = m.group(1).decode() if m else ""
            parts.append(Part(name=name, headers=head, content=content))
        return cls(boundary, parts)

    def names(self) -> list[str]:
        return [p.name for p in self._parts]

    def get(self, name: str, default=None):
        for p in self._parts:
            if p.name == name:
                return p.content
        return default

    def set(self, name: str, content: bytes) -> "MultipartBody":
        out = [
            Part(p.name, p.headers, content) if p.name == name else p
            for p in self._parts
        ]
        return MultipartBody(self._boundary, out)

    def to_bytes(self) -> bytes:
        delim = b"--" + self._boundary.encode()
        out = b""
        for p in self._parts:
            out += delim + b"\r\n" + p.headers + b"\r\n\r\n" + p.content + b"\r\n"
        out += delim + b"--\r\n"
        return out
