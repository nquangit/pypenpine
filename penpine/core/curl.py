"""Parse a curl command string into a Request."""

from __future__ import annotations

import re
import shlex
from urllib.parse import quote

from penpine.exceptions import BuildError
from penpine.logging import get_logger

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
