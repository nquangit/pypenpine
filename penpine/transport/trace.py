"""Cross-layer trace context: the attack Runner publishes the current injection
(locator + value) here so a transport interceptor can display it. Stdlib only."""

from __future__ import annotations

import contextvars
from dataclasses import dataclass


@dataclass(frozen=True)
class InjectionInfo:
    locator: str  # e.g. "json:$.user", "param:q", "header:Host"
    value: str  # the payload value being injected


current_injection: contextvars.ContextVar[InjectionInfo | None] = contextvars.ContextVar(
    "penpine_injection", default=None
)
