"""Extractors: pull values out of a Response."""
from __future__ import annotations

import re
from dataclasses import dataclass

from penpine.core.cookies import parse_set_cookie
from penpine.data.exceptions import ExtractError

_MISSING = object()


@dataclass
class Extract:
    key: str
    json: str | None = None
    header: str | None = None
    cookie: str | None = None
    regex: str | None = None
    status: bool = False
    required: bool = True
    default: object = None


def _raw_extract(response, spec: Extract):
    if spec.status:
        return response.status_code
    if spec.json is not None:
        try:
            return response.body.json.get(spec.json)
        except Exception:
            return _MISSING
    if spec.header is not None:
        return response.headers.get(spec.header, _MISSING)
    if spec.cookie is not None:
        for name, value in response.headers.items():
            if name.lower() == "set-cookie":
                parsed = parse_set_cookie(value)
                if parsed.name == spec.cookie:
                    return parsed.value
        return _MISSING
    if spec.regex is not None:
        match = re.search(spec.regex, response.body.text())
        if match is None:
            return _MISSING
        return match.group(1) if match.groups() else match.group(0)
    raise ExtractError(f"Extract({spec.key!r}) has no source set")


def extract_value(response, spec: Extract):
    value = _raw_extract(response, spec)
    if value is _MISSING:
        if spec.required:
            raise ExtractError(f"required value not found for key {spec.key!r}")
        return spec.default
    return value


def run_extractors(response, specs) -> dict:
    return {spec.key: extract_value(response, spec) for spec in specs}
