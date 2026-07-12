"""Penpine L4-flow: flow-structural attacks (skip-a-step, cross-user IDOR)."""

from penpine.attack.flow.module import FlowAttackModule, FlowVariant
from penpine.attack.flow.modules.cross_user import CrossUserModule
from penpine.attack.flow.modules.skip_step import SkipStepModule
from penpine.attack.flow.mutators import drop_step, seed_context, swap_actor
from penpine.attack.flow.results import FlowAttempt, FlowFinding, FlowReport
from penpine.attack.flow.runner import FlowRunner

__all__ = [
    "FlowRunner",
    "FlowAttackModule",
    "FlowVariant",
    "FlowFinding",
    "FlowAttempt",
    "FlowReport",
    "SkipStepModule",
    "CrossUserModule",
    "drop_step",
    "swap_actor",
    "seed_context",
]
