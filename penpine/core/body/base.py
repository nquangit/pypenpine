"""Body: raw bytes plus lazy typed views."""
from __future__ import annotations

from functools import cached_property


class Body:
    def __init__(self, raw: bytes = b"", content_type: str | None = None):
        if isinstance(raw, str):
            raw = raw.encode("utf-8")
        self._raw = raw
        self.content_type = content_type

    @property
    def raw(self) -> bytes:
        return self._raw

    def text(self, encoding: str = "utf-8") -> str:
        return self._raw.decode(encoding, errors="replace")

    def __len__(self) -> int:
        return len(self._raw)

    def __eq__(self, other) -> bool:
        return isinstance(other, Body) and self._raw == other._raw

    def __repr__(self) -> str:
        return f"Body({self._raw[:32]!r}{'...' if len(self._raw) > 32 else ''})"

    @cached_property
    def json(self):
        from penpine.core.body.json_body import JsonBody
        return JsonBody.from_bytes(self._raw)

    @cached_property
    def form(self):
        from penpine.core.body.form_body import FormBody
        return FormBody.from_bytes(self._raw)

    @cached_property
    def multipart(self):
        from penpine.core.body.multipart_body import MultipartBody
        return MultipartBody.from_bytes(self._raw, self.content_type)
