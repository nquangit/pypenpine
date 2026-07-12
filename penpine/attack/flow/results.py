"""Flow-attack results: FlowFinding, per-variant FlowAttempt, aggregate FlowReport."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class FlowFinding:
    attack_type: object  # AttackType
    target: str
    confidence: object  # Confidence
    evidence: str
    baseline_result: object  # FlowResult
    variant_result: object  # FlowResult


@dataclass
class FlowAttempt:
    variant: object
    variant_result: object | None = None
    finding: object | None = None
    error: Exception | None = None

    @property
    def ok(self) -> bool:
        return self.error is None

    @property
    def found(self) -> bool:
        return self.finding is not None


@dataclass
class FlowReport:
    base_flow: object
    attack_type: object | None
    baseline: object
    attempts: list = field(default_factory=list)

    @property
    def findings(self) -> list:
        return [a.finding for a in self.attempts if a.finding is not None]

    @property
    def errors(self) -> list:
        return [a for a in self.attempts if a.error is not None]

    def summary(self) -> dict:
        return {
            "variants": len(self.attempts),
            "failed": len(self.errors),
            "found": len(self.findings),
        }

    def __iter__(self):
        return iter(self.attempts)
