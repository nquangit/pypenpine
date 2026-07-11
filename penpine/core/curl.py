"""Parse a curl command string into a Request."""

from __future__ import annotations

import base64
import re
import shlex
from typing import TYPE_CHECKING
from urllib.parse import quote

from penpine.exceptions import BuildError
from penpine.logging import get_logger

if TYPE_CHECKING:
    from penpine.core.message import Request

log = get_logger(__name__)

# Flags we model that consume an argument.
_VALUE_FLAGS = {
    "-X",
    "--request",
    "-H",
    "--header",
    "-d",
    "--data",
    "--data-ascii",
    "--data-raw",
    "--data-binary",
    "--data-urlencode",
    "--json",
    "-b",
    "--cookie",
    "-A",
    "--user-agent",
    "-e",
    "--referer",
    "-u",
    "--user",
    "--url",
}
# Flags we accept but ignore, which still consume their argument.
_IGNORED_VALUE_FLAGS = {
    "-x",
    "--proxy",
    "--max-time",
    "--connect-timeout",
    "-m",
    "-o",
    "--output",
    "-E",
    "--cert",
    "--key",
    "--cacert",
    "--resolve",
    "--retry",
    "-w",
    "--write-out",
    "--limit-rate",
    "-r",
    "--range",
    "-T",
    "--upload-file",
    "--proxy-user",
}
# Boolean flags we model.
_BOOL_FLAGS = {"-G", "--get", "--compressed"}
# Boolean flags we accept but ignore.
_IGNORED_BOOL_FLAGS = {
    "-k",
    "--insecure",
    "-L",
    "--location",
    "-s",
    "--silent",
    "-S",
    "--show-error",
    "-v",
    "--verbose",
    "-i",
    "--include",
    "-f",
    "--fail",
    "-#",
    "--progress-bar",
    "--http1.1",
    "--http2",
    "-N",
    "--no-buffer",
}
_FORM_FLAGS = {"-F", "--form", "--form-string"}

_ANSI_C_RE = re.compile(r"\$'((?:[^'\\]|\\.)*)'")
_ANSI_C_SIMPLE = {
    "n": "\n",
    "t": "\t",
    "r": "\r",
    "\\": "\\",
    "'": "'",
    '"': '"',
    "a": "\a",
    "b": "\b",
    "f": "\f",
    "v": "\v",
}


def _decode_ansi_c(s: str) -> str:
    out: list[str] = []
    i = 0
    while i < len(s):
        ch = s[i]
        if ch == "\\" and i + 1 < len(s):
            nxt = s[i + 1]
            if nxt in _ANSI_C_SIMPLE:
                out.append(_ANSI_C_SIMPLE[nxt])
                i += 2
                continue
            if nxt == "x":
                m = re.match(r"[0-9a-fA-F]{1,2}", s[i + 2 : i + 4])
                if m:
                    out.append(chr(int(m.group(0), 16)))
                    i += 2 + len(m.group(0))
                    continue
            if nxt == "u":
                m = re.match(r"[0-9a-fA-F]{4}", s[i + 2 : i + 6])
                if m:
                    out.append(chr(int(m.group(0), 16)))
                    i += 6
                    continue
            out.append(ch)
            i += 1
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def _preprocess(command: str) -> str:
    command = re.sub(r"\\\r?\n", " ", command)

    def _repl(match: re.Match) -> str:
        decoded = _decode_ansi_c(match.group(1))
        # Re-wrap as a POSIX single-quoted token (escape embedded single quotes).
        return "'" + decoded.replace("'", "'\"'\"'") + "'"

    return _ANSI_C_RE.sub(_repl, command)


def _tokenize(command: str) -> list[str]:
    try:
        tokens = shlex.split(_preprocess(command), posix=True)
    except ValueError as exc:
        raise BuildError(f"could not tokenize curl command: {exc}") from exc
    if tokens and tokens[0] == "curl":
        tokens = tokens[1:]
    return tokens


def _split_header(raw: str) -> tuple[str, str]:
    if ":" in raw:
        name, _, value = raw.partition(":")
        return name.strip(), value.strip()
    if raw.endswith(";"):
        return raw[:-1].strip(), ""
    return raw.strip(), ""


def _assemble_data(entries: list[tuple[str, str]]) -> str:
    parts: list[str] = []
    for kind, value in entries:
        if kind == "urlencode":
            if "=" in value:
                name, _, content = value.partition("=")
                parts.append(f"{name}={quote(content, safe='')}")
            else:
                parts.append(quote(value, safe=""))
        else:
            parts.append(value)
    return "&".join(parts)


def _next_value(tokens: list[str], i: int, inline: str | None, key: str) -> tuple[str, int]:
    if inline is not None:
        return inline, i
    if i + 1 >= len(tokens):
        raise BuildError(f"curl flag {key} expects a value")
    return tokens[i + 1], i + 1


def parse_curl(command: str) -> Request:
    from penpine.core.body.base import Body
    from penpine.core.headers import Headers
    from penpine.core.message import Request
    from penpine.core.meta import ConnectionMeta
    from penpine.core.url import parse_url

    tokens = _tokenize(command)

    url: str | None = None
    method: str | None = None
    header_items: list[tuple[str, str]] = []
    data_entries: list[tuple[str, str]] = []
    is_get = False
    is_json = False
    user: str | None = None

    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if not tok.startswith("-"):
            if url is None:
                url = tok
            else:
                log.debug("ignoring extra positional argument: %r", tok)
            i += 1
            continue

        if tok.startswith("--") and "=" in tok:
            key, _, inline = tok.partition("=")
        else:
            key, inline = tok, None

        if key in _FORM_FLAGS:
            raise BuildError(
                "multipart -F/--form is not supported by from_curl; "
                "use RequestBuilder for multipart bodies"
            )
        elif key in ("-X", "--request"):
            method, i = _next_value(tokens, i, inline, key)
        elif key in ("-H", "--header"):
            value, i = _next_value(tokens, i, inline, key)
            header_items.append(_split_header(value))
        elif key in ("-A", "--user-agent"):
            value, i = _next_value(tokens, i, inline, key)
            header_items.append(("User-Agent", value))
        elif key in ("-e", "--referer"):
            value, i = _next_value(tokens, i, inline, key)
            header_items.append(("Referer", value))
        elif key in ("-b", "--cookie"):
            value, i = _next_value(tokens, i, inline, key)
            header_items.append(("Cookie", value))
        elif key in ("-u", "--user"):
            user, i = _next_value(tokens, i, inline, key)
        elif key == "--url":
            url, i = _next_value(tokens, i, inline, key)
        elif key in ("-d", "--data", "--data-ascii"):
            value, i = _next_value(tokens, i, inline, key)
            data_entries.append(("data", value))
        elif key == "--data-raw":
            value, i = _next_value(tokens, i, inline, key)
            data_entries.append(("raw", value))
        elif key == "--data-binary":
            value, i = _next_value(tokens, i, inline, key)
            data_entries.append(("binary", value))
        elif key == "--data-urlencode":
            value, i = _next_value(tokens, i, inline, key)
            data_entries.append(("urlencode", value))
        elif key == "--json":
            value, i = _next_value(tokens, i, inline, key)
            data_entries.append(("raw", value))
            is_json = True
        elif key in ("-G", "--get"):
            is_get = True
        elif key == "--compressed":
            pass
        elif key in _IGNORED_VALUE_FLAGS:
            _, i = _next_value(tokens, i, inline, key)
            log.debug("ignoring curl flag with value: %s", key)
        else:
            log.debug("ignoring curl flag: %s", key)
        i += 1

    if url is None:
        raise BuildError("no URL found in curl command")

    parsed = parse_url(url)
    data_str = _assemble_data(data_entries)

    if method is None:
        method = "GET" if (is_get or not data_entries) else "POST"
    method = method.upper()

    query = parsed.query
    body = data_str.encode("utf-8")
    if is_get and data_entries:
        query = f"{query}&{data_str}" if query else data_str
        body = b""

    target = parsed.path + (f"?{query}" if query else "")
    host_header = parsed.host if parsed.port in (80, 443) else f"{parsed.host}:{parsed.port}"
    items: list[tuple[str, str]] = [("Host", host_header), *header_items]

    def _has(name: str) -> bool:
        return any(existing.lower() == name.lower() for existing, _ in items)

    if user is not None:
        if ":" not in user:
            user = user + ":"
        token = base64.b64encode(user.encode("utf-8")).decode("ascii")
        if not _has("Authorization"):
            items.append(("Authorization", f"Basic {token}"))

    if body and not _has("Content-Type"):
        items.append(
            (
                "Content-Type",
                "application/json" if is_json else "application/x-www-form-urlencoded",
            )
        )
    if is_json and not _has("Accept"):
        items.append(("Accept", "application/json"))
    if body and not _has("Content-Length"):
        items.append(("Content-Length", str(len(body))))

    return Request(
        method=method,
        target=target,
        version="HTTP/1.1",
        headers=Headers(items),
        body=Body(body),
        meta=ConnectionMeta(scheme=parsed.scheme, host=parsed.host, port=parsed.port),
    )
