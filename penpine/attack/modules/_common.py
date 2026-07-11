"""Shared helpers for attack modules."""

from __future__ import annotations

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
