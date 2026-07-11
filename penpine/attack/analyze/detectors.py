"""Reusable value heuristics for classification and payload tailoring."""

from __future__ import annotations

import re

_UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_INT_RE = re.compile(r"^[+-]?\d+$")
_BOOL_VALUES = {"true", "false", "0", "1", "yes", "no"}


def _s(value) -> str:
    if value is None:
        return ""
    return value if isinstance(value, str) else str(value)


def is_integer(value) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return True
    return bool(_INT_RE.match(_s(value).strip()))


def is_numeric(value) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        return True
    s = _s(value).strip()
    if not s:
        return False
    try:
        float(s)
        return True
    except ValueError:
        return False


def is_url(value) -> bool:
    s = _s(value).strip().lower()
    return s.startswith(("http://", "https://", "//"))


def is_path(value) -> bool:
    if is_url(value):
        return False
    s = _s(value)
    return "/" in s or "\\" in s or ".." in s


def is_email(value) -> bool:
    return bool(_EMAIL_RE.match(_s(value).strip()))


def is_uuid(value) -> bool:
    return bool(_UUID_RE.match(_s(value).strip()))


def looks_like_json(value) -> bool:
    s = _s(value).strip()
    return s.startswith("{") or s.startswith("[")


def is_boolean(value) -> bool:
    if isinstance(value, bool):
        return True
    return _s(value).strip().lower() in _BOOL_VALUES


def is_empty(value) -> bool:
    if value is None:
        return True
    return _s(value).strip() == ""
