"""Shared helpers for attack modules."""

from __future__ import annotations

import re
import secrets


def marker(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(4)}"


def body_text(response) -> str:
    try:
        return response.body.text()
    except Exception:
        return ""


def search_signatures(text: str, patterns):
    for pattern in patterns:
        match = pattern.search(text)
        if match:
            return match
    return None


GENERIC_ERROR_SIGNATURES = [
    re.compile(pattern, re.I)
    for pattern in [
        r"Traceback \(most recent call last\)",
        r"Fatal error:",
        r"Stack trace:",
        r"java\.lang\.[A-Za-z.]+(Exception|Error)",
        r"at [\w.$]+\([\w.]+\.java:\d+\)",
        r"System\.[A-Za-z.]+Exception",
        r"Microsoft OLE DB Provider",
        r"Internal Server Error",
        r"(Syntax|Reference|Type)Error:",
        r"undefined method ['`].*['`] for",
        r"ORA-\d{5}",
        r"SQLSTATE\[",
        r"Warning: \w+\(\).* in ",
        r"Uncaught (?:Error|Exception)",
    ]
]


def error_signature(response, baseline, signatures):
    """First signature present in the response but NOT the baseline (or None)."""
    match = search_signatures(body_text(response), signatures)
    if match is None:
        return None
    if baseline is not None and search_signatures(body_text(baseline), signatures):
        return None
    return match
