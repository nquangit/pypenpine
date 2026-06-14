"""Run results: per-test-case Attempt and the aggregate Report."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Attempt:
    test_case: object
    request: object | None = None
    response: object | None = None
    finding: object | None = None
    error: Exception | None = None
    elapsed_ms: float | None = None

    @property
    def ok(self) -> bool:
        return self.error is None

    @property
    def found(self) -> bool:
        return self.finding is not None


@dataclass
class Report:
    request: object
    attack_type: str | None
    baseline: object | None
    attempts: list = field(default_factory=list)

    @property
    def findings(self) -> list:
        return [a.finding for a in self.attempts if a.finding is not None]

    @property
    def errors(self) -> list:
        return [a for a in self.attempts if a.error is not None]

    def summary(self) -> dict:
        return {
            "sent": len(self.attempts),
            "failed": len(self.errors),
            "found": len(self.findings),
        }

    def __iter__(self):
        return iter(self.attempts)

    def __len__(self) -> int:
        return len(self.attempts)
