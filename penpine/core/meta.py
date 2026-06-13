"""Connection metadata populated by loaders/builder, consumed by L1."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ConnectionMeta:
    scheme: str | None = None
    host: str | None = None
    port: int | None = None
