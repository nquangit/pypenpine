"""JSON body view with JSONPath get/set (jsonpath-ng isolated here)."""

from __future__ import annotations

import copy
import json

from jsonpath_ng.ext import parse as jsonpath_parse

from penpine.exceptions import BodyParseError


class JsonBody:
    def __init__(self, data):
        self._data = data

    @classmethod
    def from_bytes(cls, raw: bytes) -> JsonBody:
        try:
            return cls(json.loads(raw.decode("utf-8")))
        except (ValueError, UnicodeDecodeError) as exc:
            raise BodyParseError(f"invalid JSON body: {exc}") from exc

    @property
    def data(self):
        return self._data

    def get(self, path: str):
        matches = jsonpath_parse(path).find(self._data)
        if not matches:
            raise BodyParseError(f"JSON path not found: {path}")
        return matches[0].value

    def set(self, path: str, value) -> JsonBody:
        new_data = copy.deepcopy(self._data)
        expr = jsonpath_parse(path)
        if not expr.find(new_data):
            raise BodyParseError(f"JSON path not found: {path}")
        expr.update(new_data, value)
        return JsonBody(new_data)

    def to_bytes(self) -> bytes:
        return json.dumps(self._data).encode("utf-8")
