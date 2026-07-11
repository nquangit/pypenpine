"""Construct Request objects from raw bytes, files, or URLs."""

from __future__ import annotations

from penpine.core.body.base import Body
from penpine.core.headers import Headers
from penpine.core.meta import ConnectionMeta
from penpine.core.parse.http_parser import parse_request
from penpine.core.url import parse_url


def from_raw(data, *, strict=False, scheme=None, host=None, port=None):
    if isinstance(data, str):
        data = data.encode("utf-8")
    req = parse_request(data, strict=strict)
    if scheme or host or port:
        req = req.clone(meta=ConnectionMeta(scheme=scheme, host=host, port=port))
    return req


def from_file(path, *, strict=False, scheme=None, host=None, port=None):
    with open(path, "rb") as fh:
        return from_raw(fh.read(), strict=strict, scheme=scheme, host=host, port=port)


def from_url(url, *, method="GET", headers=None, body=None, version="HTTP/1.1"):
    from penpine.core.message import Request

    u = parse_url(url)
    host_header = u.host if u.port in (80, 443) else f"{u.host}:{u.port}"
    items = [("Host", host_header)]
    if headers:
        items += list(headers)
    target = u.path + (f"?{u.query}" if u.query else "")
    return Request(
        method=method,
        target=target,
        version=version,
        headers=Headers(items),
        body=Body(body or b""),
        meta=ConnectionMeta(scheme=u.scheme, host=u.host, port=u.port),
    )
