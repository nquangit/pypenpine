"""Skip-a-step: drop a step and see whether the protected outcome still occurs."""

from __future__ import annotations

from penpine.attack.flow.module import FlowAttackModule, FlowVariant
from penpine.attack.flow.mutators import drop_step
from penpine.attack.flow.results import FlowFinding
from penpine.attack.models import Confidence
from penpine.attack.types import AttackType


def _is_2xx(response) -> bool:
    return response is not None and 200 <= getattr(response, "status_code", 0) < 300


class SkipStepModule(FlowAttackModule):
    attack_type = AttackType.BROKEN_ACCESS
    name = "skip-step"

    def __init__(self, *, goal=None, success=None):
        self._goal = goal
        self._success = success

    def mutate(self, base_flow, baseline_result, targets):
        steps = base_flow.steps
        goal = self._goal or (steps[-1].name if steps else None)
        names = list(targets) if targets is not None else [s.name for s in steps if s.name != goal]
        for name in names:
            yield FlowVariant(
                flow=drop_step(base_flow, name),
                target=name,
                meta={"dropped": name, "goal": goal},
            )

    def validate(self, variant, variant_result, baseline_result):
        goal = variant.meta["goal"]
        if not self._goal_ok(baseline_result, goal):
            return None  # baseline goal didn't succeed -> nothing to compare
        if not self._goal_ok(variant_result, goal):
            return None  # dropping the step broke the goal (secure)
        confidence = (
            Confidence.HIGH
            if self._goal_matches(baseline_result, variant_result, goal)
            else Confidence.MEDIUM
        )
        return FlowFinding(
            attack_type=self.attack_type,
            target=variant.target,
            confidence=confidence,
            evidence=(f"goal step {goal!r} still succeeded with step {variant.target!r} removed"),
            baseline_result=baseline_result,
            variant_result=variant_result,
        )

    def _goal_ok(self, result, goal) -> bool:
        if self._success is not None:
            return bool(self._success(result))
        try:
            sr = result.step(goal)
        except KeyError:
            return False  # goal step never ran
        return sr.status in ("ok", "recovered") and _is_2xx(sr.response)

    def _goal_matches(self, baseline_result, variant_result, goal) -> bool:
        try:
            b = baseline_result.step(goal).response
            v = variant_result.step(goal).response
        except KeyError:
            return False
        if b is None or v is None:
            return False
        return b.status_code == v.status_code and b.body.raw == v.body.raw
