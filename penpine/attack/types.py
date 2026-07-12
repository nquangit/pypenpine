"""AttackType: the canonical, typed attack-category vocabulary."""

from __future__ import annotations

from enum import Enum

from penpine.attack.exceptions import AttackConfigError


class AttackType(Enum):
    SQLI = "sqli"
    XSS = "xss"
    IDOR = "idor"
    SSRF = "ssrf"
    OPEN_REDIRECT = "open-redirect"
    PATH_TRAVERSAL = "path-traversal"
    LFI = "lfi"
    HOST_HEADER = "host-header"
    HEADER_INJECTION = "header-injection"
    BROKEN_ACCESS = "broken-access"

    @classmethod
    def from_str(cls, value: str) -> AttackType:
        """Coerce a serialized string to an AttackType (CLI/config/report edge only)."""
        try:
            return cls(value)
        except ValueError:
            raise AttackConfigError(f"unknown attack type: {value!r}") from None
