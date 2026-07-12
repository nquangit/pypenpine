"""FlowAttackModule contract + FlowVariant."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable
from dataclasses import dataclass, field


@dataclass
class FlowVariant:
    flow: object
    target: str
    meta: dict = field(default_factory=dict)


class FlowAttackModule(ABC):
    attack_type = None
    name = ""

    @abstractmethod
    def mutate(self, base_flow, baseline_result, targets) -> Iterable[FlowVariant]:
        """Yield variant flows (mutations of base_flow) tagged with what changed."""
        raise NotImplementedError

    @abstractmethod
    def validate(self, variant, variant_result, baseline_result):
        """Return a FlowFinding if the variant reveals a vulnerability, else None."""
        raise NotImplementedError
