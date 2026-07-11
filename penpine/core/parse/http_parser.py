"""Parse raw bytes into Request/Response. Lenient by default."""

from __future__ import annotations

from penpine.core.body.base import Body
from penpine.core.headers import Headers
from penpine.core.message import Request, Response
from penpine.core.parse.framing import body_length, decode_chunked
from penpine.exceptions import MalformedRequestError


def _split_head_body(data: bytes, strict: bool) -> tuple[bytes, bytes, list[str]]:
    warnings: list[str] = []
    idx = data.find(b"\r\n\r\n")
    crlf = True
    if idx == -1:
        idx = data.find(b"\n\n")
        crlf = False
        if idx == -1:
            raise MalformedRequestError("no header/body separator found")
    if not crlf:
        if strict:
            raise MalformedRequestError("LF-only line endings")
        warnings.append("LF-only line endings normalized")
    head = data[:idx]
    body = data[idx + (4 if crlf else 2) :]
    if not crlf:
        head = head.replace(b"\n", b"\r\n")
    return head, body, warnings


def _parse_headers(head_lines: list[bytes], strict: bool, warnings: list[str]) -> Headers:
    items: list[tuple[str, str]] = []
    for line in head_lines:
        text = line.decode("latin-1")
        if ":" not in text:
            if strict:
                raise MalformedRequestError(f"header without colon: {text!r}")
            warnings.append(f"malformed header line preserved: {text!r}")
            items.append((text, ""))
            continue
        name, _, value = text.partition(":")
        items.append((name, value.strip()))
    return Headers(items)


def _content_type(headers: Headers) -> str | None:
    return headers.get("Content-Type")


def _extract_body(headers: Headers, body: bytes) -> bytes:
    kind, length = body_length(headers)
    if kind == "length":
        return body[:length]
    if kind == "chunked":
        decoded, _ = decode_chunked(body)
        return decoded
    return body if body else b""


def parse_request(data: bytes, *, strict: bool = False) -> Request:
    head, body, warnings = _split_head_body(data, strict)
    lines = head.split(b"\r\n")
    start = lines[0].decode("latin-1")
    parts = start.split(" ")
    if len(parts) != 3:
        raise MalformedRequestError(f"invalid request line: {start!r}")
    method, target, version = parts
    headers = _parse_headers(lines[1:], strict, warnings)
    body_bytes = _extract_body(headers, body)
    return Request(
        method=method,
        target=target,
        version=version,
        headers=headers,
        body=Body(body_bytes, _content_type(headers)),
        parse_warnings=tuple(warnings),
        raw=data,
    )


def parse_response(data: bytes, *, strict: bool = False) -> Response:
    head, body, warnings = _split_head_body(data, strict)
    lines = head.split(b"\r\n")
    start = lines[0].decode("latin-1")
    version, _, rest = start.partition(" ")
    code_s, _, reason = rest.partition(" ")
    try:
        code = int(code_s)
    except ValueError as exc:
        raise MalformedRequestError(f"invalid status line: {start!r}") from exc
    headers = _parse_headers(lines[1:], strict, warnings)
    body_bytes = _extract_body(headers, body)
    return Response(
        status_code=code,
        reason=reason,
        version=version,
        headers=headers,
        body=Body(body_bytes, _content_type(headers)),
        parse_warnings=tuple(warnings),
        raw=data,
    )
