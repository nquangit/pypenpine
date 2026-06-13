"""Read-only cookie parsing (the stateful jar lives in L2)."""
from __future__ import annotations

from dataclasses import dataclass, field


def parse_cookie_header(value: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for part in value.split(";"):
        part = part.strip()
        if not part:
            continue
        k, _, v = part.partition("=")
        out.append((k.strip(), v.strip()))
    return out


@dataclass
class SetCookie:
    name: str
    value: str
    attributes: dict[str, str] = field(default_factory=dict)
    flags: set[str] = field(default_factory=set)


def parse_set_cookie(value: str) -> SetCookie:
    segments = [s.strip() for s in value.split(";") if s.strip()]
    name, _, val = segments[0].partition("=")
    cookie = SetCookie(name=name.strip(), value=val.strip())
    for seg in segments[1:]:
        if "=" in seg:
            k, _, v = seg.partition("=")
            cookie.attributes[k.strip().lower()] = v.strip()
        else:
            cookie.flags.add(seg.lower())
    return cookie
