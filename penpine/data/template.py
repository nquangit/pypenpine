"""Custom {{ }} template renderer over a Request, and mapping builder."""
from __future__ import annotations

import re

from penpine.core.headers import Headers
from penpine.data.context import Context
from penpine.data.exceptions import TemplateError
from penpine.data.profile import DataProfile

_PLACEHOLDER = re.compile(r"\{\{\s*([^}\s]+)\s*\}\}")


def build_mapping(context=None, data=None, extra=None) -> dict:
    """Merge sources with precedence data < context < extra."""
    mapping: dict = {}
    if data is not None:
        mapping.update(data.values if isinstance(data, DataProfile) else dict(data))
    if context is not None:
        mapping.update(context.to_dict() if isinstance(context, Context) else dict(context))
    if extra is not None:
        mapping.update(dict(extra))
    return mapping


def render(request, mapping, *, strict=True):
    def _replace(text: str) -> str:
        def _sub(match):
            key = match.group(1)
            if key in mapping:
                return str(mapping[key])
            if strict:
                raise TemplateError(f"unknown placeholder: {{{{{key}}}}}")
            return match.group(0)
        return _PLACEHOLDER.sub(_sub, text)

    new = request.with_target(_replace(request.target))
    new = new.with_headers(
        Headers([(name, _replace(value)) for name, value in new.headers.items()]))
    if request.body.raw:
        new = new.with_body(_replace(request.body.text()).encode())
    return new
