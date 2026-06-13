"""application/x-www-form-urlencoded body view."""
from __future__ import annotations

from penpine.core.url import build_query, parse_query


class FormBody:
    def __init__(self, fields: list[tuple[str, str]]):
        self._fields = list(fields)

    @classmethod
    def from_bytes(cls, raw: bytes) -> "FormBody":
        return cls(parse_query(raw.decode("utf-8", errors="replace")))

    @property
    def fields(self) -> list[tuple[str, str]]:
        return list(self._fields)

    def get(self, name: str, default=None):
        for k, v in self._fields:
            if k == name:
                return v
        return default

    def set(self, name: str, value: str) -> "FormBody":
        replaced = False
        out: list[tuple[str, str]] = []
        for k, v in self._fields:
            if k == name and not replaced:
                out.append((k, value))
                replaced = True
            else:
                out.append((k, v))
        if not replaced:
            out.append((name, value))
        return FormBody(out)

    def to_bytes(self) -> bytes:
        return build_query(self._fields).encode("utf-8")
