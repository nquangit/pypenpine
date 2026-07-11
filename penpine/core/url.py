"""URL/target parsing helpers. Pure string operations, no network."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import quote, unquote

_DEFAULT_PORTS = {"http": 80, "https": 443}


@dataclass(frozen=True)
class ParsedUrl:
    scheme: str
    host: str
    port: int
    path: str
    query: str


def parse_url(url: str) -> ParsedUrl:
    scheme, _, rest = url.partition("://")
    scheme = scheme.lower()
    authority, slash, tail = rest.partition("/")
    path_and_query = (slash + tail) if slash else "/"
    host, _, port_s = authority.partition(":")
    port = int(port_s) if port_s else _DEFAULT_PORTS.get(scheme, 80)
    path, _, query = path_and_query.partition("?")
    return ParsedUrl(scheme, host, port, path or "/", query)


def parse_query(query: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    if not query:
        return out
    for pair in query.split("&"):
        if not pair:
            continue
        k, sep, v = pair.partition("=")
        out.append((unquote(k), unquote(v) if sep else ""))
    return out


def build_query(pairs: list[tuple[str, str]]) -> str:
    return "&".join(f"{quote(k, safe='')}={quote(v, safe='')}" for k, v in pairs)


def split_target(target: str) -> tuple[str, str]:
    """Split an origin-form target into (path, query)."""
    path, _, query = target.partition("?")
    return path, query


def set_query_param(target: str, name: str, value: str) -> str:
    path, query = split_target(target)
    pairs = parse_query(query)
    replaced = False
    new_pairs: list[tuple[str, str]] = []
    for k, v in pairs:
        if k == name and not replaced:
            new_pairs.append((k, value))
            replaced = True
        else:
            new_pairs.append((k, v))
    if not replaced:
        new_pairs.append((name, value))
    q = build_query(new_pairs)
    return f"{path}?{q}" if q else path
