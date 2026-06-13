"""Serialize a Request back to raw bytes."""
from __future__ import annotations

from penpine.core.message import Request


def serialize_request(req: Request) -> bytes:
    if req.raw is not None:
        return req.raw
    start = f"{req.method} {req.target} {req.version}".encode("latin-1")
    lines = [start]
    for name, value in req.headers.items():
        lines.append(f"{name}: {value}".encode("latin-1"))
    head = b"\r\n".join(lines)
    return head + b"\r\n\r\n" + req.body.raw
