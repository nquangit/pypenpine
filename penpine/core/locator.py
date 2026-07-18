"""Locator DSL: address and replace sub-parts of a Request."""

from __future__ import annotations

from dataclasses import dataclass

from penpine.core.cookies import parse_cookie_header
from penpine.core.url import parse_query, split_target
from penpine.exceptions import LocatorError


@dataclass(frozen=True)
class ResolvedLocator:
    request: object
    kind: str
    name: str
    value: object
    exists: bool = True

    def replace(self, new_value):
        return _replace(self.request, self.kind, self.name, new_value)


def parse_expr(expr: str) -> tuple[str, str]:
    if expr in ("method", "target", "version", "body"):
        return expr, ""
    kind, sep, name = expr.partition(":")
    if not sep:
        raise LocatorError(f"invalid locator expression: {expr!r}")
    return kind, name


def locate(request, expr: str) -> ResolvedLocator:
    kind, name = parse_expr(expr)
    value = _read(request, kind, name)
    return ResolvedLocator(request=request, kind=kind, name=name, value=value)


def _read(request, kind: str, name: str):
    if kind in ("method", "target", "version"):
        return getattr(request, kind)
    if kind == "param":
        _, query = split_target(request.target)
        for k, v in parse_query(query):
            if k == name:
                return v
        raise LocatorError(f"query param not found: {name}")
    if kind == "header":
        if name not in request.headers:
            raise LocatorError(f"header not found: {name}")
        return request.headers[name]
    if kind == "cookie":
        for k, v in parse_cookie_header(request.headers.get("Cookie", "")):
            if k == name:
                return v
        raise LocatorError(f"cookie not found: {name}")
    if kind == "json":
        return request.body.json.get(name)
    if kind == "form":
        v = request.body.form.get(name, _MISSING)
        if v is _MISSING:
            raise LocatorError(f"form field not found: {name}")
        return v
    if kind == "multipart":
        v = request.body.multipart.get(name)
        if v is None:
            raise LocatorError(f"multipart field not found: {name}")
        return v
    if kind == "path-seg":
        path, _ = split_target(request.target)
        segs = [s for s in path.split("/") if s]
        try:
            return segs[int(name)]
        except (ValueError, IndexError) as exc:
            raise LocatorError(f"path segment not found: {name}") from exc
    if kind == "body":
        return request.body.text()
    raise LocatorError(f"unknown locator kind: {kind}")


def _replace(request, kind: str, name: str, value):
    if kind == "method":
        return request.with_method(value)
    if kind == "target":
        return request.with_target(value)
    if kind == "version":
        return request.with_version(value)
    if kind == "param":
        return request.set_param(name, value)
    if kind == "header":
        return request.set_header(name, value)
    if kind == "cookie":
        pairs = parse_cookie_header(request.headers.get("Cookie", ""))
        new = "; ".join(f"{k}={value if k == name else v}" for k, v in pairs)
        return request.set_header("Cookie", new)
    if kind == "json":
        return request.set_json(name, value)
    if kind == "form":
        return request.set_form_field(name, value)
    if kind == "multipart":
        data = value if isinstance(value, bytes) else str(value).encode()
        return request.with_body(request.body.multipart.set(name, data).to_bytes())
    if kind == "path-seg":
        path, query = split_target(request.target)
        segs = path.split("/")
        non_empty = [i for i, s in enumerate(segs) if s]
        segs[non_empty[int(name)]] = value
        new_path = "/".join(segs)
        return request.with_target(f"{new_path}?{query}" if query else new_path)
    if kind == "body":
        return request.with_body(value.encode("utf-8") if isinstance(value, str) else value)
    raise LocatorError(f"cannot replace kind: {kind}")


_MISSING = object()


def _json_leaf_paths(data, prefix="$"):
    paths = []
    if isinstance(data, dict):
        for k, v in data.items():
            paths += _json_leaf_paths(v, f"{prefix}.{k}")
    elif isinstance(data, list):
        for i, v in enumerate(data):
            paths += _json_leaf_paths(v, f"{prefix}[{i}]")
    else:
        paths.append(prefix)
    return paths


def enumerate_candidates(request, kinds=None) -> list[ResolvedLocator]:
    out: list[ResolvedLocator] = []

    def emit(kind, name, value):
        if kinds is None or kind in kinds:
            out.append(ResolvedLocator(request, kind, name, value))

    _, query = split_target(request.target)
    for k, v in parse_query(query):
        emit("param", k, v)
    for name, value in request.headers.items():
        if name.lower() == "cookie":
            for ck, cv in parse_cookie_header(value):
                emit("cookie", ck, cv)
        else:
            emit("header", name, value)
    ctype = request.headers.get("Content-Type", "")
    if "application/json" in ctype and request.body.raw:
        try:
            for path in _json_leaf_paths(request.body.json.data):
                emit("json", path, request.body.json.get(path))
        except Exception:
            pass
    elif "application/x-www-form-urlencoded" in ctype:
        for k, v in request.body.form.fields:
            emit("form", k, v)
    elif "multipart/form-data" in ctype and request.body.raw:
        try:
            mp = request.body.multipart
            for nm in mp.names():
                emit("multipart", nm, mp.get(nm))
        except Exception:
            pass
    path, _ = split_target(request.target)
    for i, seg in enumerate([s for s in path.split("/") if s]):
        emit("path-seg", str(i), seg)
    return out
