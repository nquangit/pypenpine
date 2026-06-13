"""Session: auth material produced by a login/refresh, plus expiry metadata."""
from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class Session:
    token: str | None = None
    cookies: list[tuple[str, str]] = field(default_factory=list)
    headers: list[tuple[str, str]] = field(default_factory=list)
    data: dict = field(default_factory=dict)
    issued_at: float = field(default_factory=time.time)
    expires_at: float | None = None

    def is_expired(self, skew: float = 0.0) -> bool:
        return self.expires_at is not None and time.time() >= self.expires_at - skew
