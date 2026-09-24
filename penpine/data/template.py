"""Custom {{ }} template renderer over a Request, and mapping builder."""

from __future__ import annotations

import re

from penpine.core.headers import Headers
from penpine.core.url import build_query, parse_query
from penpine.data.context import Context
from penpine.data.exceptions import TemplateError
from penpine.data.profile import DataProfile

_PLACEHOLDER = re.compile(r"\{\{\s*([^}\s]+)\s*\}\}")


def render_text(text: str, mapping, *, strict: bool = True) -> str:
    def _sub(match):
        key = match.group(1)
        if key in mapping:
            return str(mapping[key])
        if strict:
            raise TemplateError(f"unknown placeholder: {{{{{key}}}}}")
        return match.group(0)

    return _PLACEHOLDER.sub(_sub, text)


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


def _has_placeholder(text: str) -> bool:
    return bool(_PLACEHOLDER.search(text))


def _pairs_have_placeholder(pairs) -> bool:
    return any(_has_placeholder(k) or _has_placeholder(v) for k, v in pairs)


def _render_target(target: str, replace) -> str:
    """Render the target, substituting into *decoded* query params.

    A value set via ``set_param`` is percent-encoded (``{{x}}`` -> ``%7B%7Bx%7D%7D``),
    so a text-only substitution would never see the placeholder. We parse the query
    into decoded pairs, substitute there, then re-encode so the resolved value lands
    on the wire correctly encoded. The path is rendered as text (it is never passed
    through the query encoder). When the query holds no placeholder we leave its raw
    bytes untouched, keeping deliberately-malformed queries byte-faithful.
    """
    path, sep, query = target.partition("?")
    new_path = replace(path)
    if not sep:
        return new_path
    pairs = parse_query(query)
    if _pairs_have_placeholder(pairs):
        new_pairs = [(replace(k), replace(v)) for k, v in pairs]
        return f"{new_path}?{build_query(new_pairs)}"
    # No decoded placeholder: `replace` is a no-op here, preserving the raw query.
    return f"{new_path}?{replace(query)}"


def render(request, mapping, *, strict=True):
    def _replace(text: str) -> str:
        return render_text(text, mapping, strict=strict)

    new = request.with_target(_render_target(request.target, _replace))
    new = new.with_headers(
        Headers([(name, _replace(value)) for name, value in new.headers.items()])
    )
    if request.body.raw:
        ctype = request.headers.get("Content-Type", "")
        fields = request.body.form.fields if "application/x-www-form-urlencoded" in ctype else None
        if fields is not None and _pairs_have_placeholder(fields):
            # Same story as the query string: placeholders were percent-encoded by
            # `set_form_field`. Substitute into the decoded fields, then re-encode.
            new_fields = [(_replace(k), _replace(v)) for k, v in fields]
            new = new.with_body(build_query(new_fields).encode())
        else:
            new = new.with_body(_replace(request.body.text()).encode())
    return new
