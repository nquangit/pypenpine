"""Flow run results: per-step StepResult and the aggregate FlowResult."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field


@dataclass
class StepResult:
    step: str
    actor: object
    status: str  # "ok" | "skipped" | "recovered" | "failed"
    request: object | None = None
    response: object | None = None
    captured: list = field(default_factory=list)
    recovery_ran: bool = False
    error: Exception | None = None
    elapsed_ms: float | None = None


@dataclass
class FlowResult:
    steps: list
    context: dict

    @property
    def ok(self) -> bool:
        return all(s.status != "failed" for s in self.steps)

    @property
    def failed_step(self):
        return next((s for s in self.steps if s.status == "failed"), None)

    def step(self, name: str):
        for s in self.steps:
            if s.step == name:
                return s
        raise KeyError(name)

    def summary(self) -> dict:
        counts = Counter(s.status for s in self.steps)
        return {
            "ran": counts.get("ok", 0) + counts.get("recovered", 0),
            "skipped": counts.get("skipped", 0),
            "recovered": counts.get("recovered", 0),
            "failed": counts.get("failed", 0),
        }

    def __iter__(self):
        return iter(self.steps)
