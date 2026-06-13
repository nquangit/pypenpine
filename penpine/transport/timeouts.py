"""Timeout configuration for the transport layer."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Timeouts:
    connect: float | None = 10.0
    read: float | None = 30.0
    total: float | None = None
