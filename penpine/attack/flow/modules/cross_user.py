"""Cross-user IDOR: replay a flow's access steps as a different identity."""

from __future__ import annotations

from penpine.attack.flow.module import FlowAttackModule, FlowVariant
from penpine.attack.flow.mutators import seed_context, swap_actor
from penpine.attack.flow.results import FlowFinding
from penpine.attack.models import Confidence
from penpine.attack.types import AttackType


def _is_2xx(response) -> bool:
    return response is not None and 200 <= getattr(response, "status_code", 0) < 300


class CrossUserModule(FlowAttackModule):
    attack_type = AttackType.IDOR
    name = "cross-user"

    def __init__(self, *, owner, attacker, access_steps=None):
        self._owner = owner
        self._attacker = attacker
        self._access_steps = access_steps

    def mutate(self, base_flow, baseline_result, targets):
        access = (
            list(targets)
            if targets is not None
            else (self._access_steps or self._infer_access_steps(base_flow, baseline_result))
        )
        variant_flow = swap_actor(base_flow, access, self._attacker)
        variant_flow = seed_context(variant_flow, baseline_result.context)
        yield FlowVariant(
            flow=variant_flow,
            target=f"{self._actor_name(self._attacker)} accesses {access}",
            meta={"access_steps": access},
        )

    def validate(self, variant, variant_result, baseline_result):
        for name in variant.meta["access_steps"]:
            try:
                sr = variant_result.step(name)
            except KeyError:
                continue
            if sr.status in ("ok", "recovered") and _is_2xx(sr.response):
                confidence = (
                    Confidence.HIGH
                    if self._body_matches(baseline_result, sr, name)
                    else Confidence.MEDIUM
                )
                return FlowFinding(
                    attack_type=self.attack_type,
                    target=variant.target,
                    confidence=confidence,
                    evidence=(
                        f"{self._actor_name(self._attacker)} reached step {name!r} "
                        f"(status {sr.response.status_code}) that should be owner-only"
                    ),
                    baseline_result=baseline_result,
                    variant_result=variant_result,
                )
        return None

    def _infer_access_steps(self, base_flow, baseline_result) -> list:
        names = [s.name for s in base_flow.steps]
        first_capture_idx = None
        for i, name in enumerate(names):
            try:
                sr = baseline_result.step(name)
            except KeyError:
                continue
            if sr.captured:
                first_capture_idx = i
                break
        if first_capture_idx is None:
            return names[-1:]  # no capture -> just the last step
        return names[first_capture_idx + 1 :]

    def _body_matches(self, baseline_result, variant_sr, name) -> bool:
        try:
            b = baseline_result.step(name).response
        except KeyError:
            return False
        v = variant_sr.response
        if b is None or v is None:
            return False
        return b.body.raw == v.body.raw

    @staticmethod
    def _actor_name(actor) -> str:
        return getattr(actor, "name", repr(actor))
