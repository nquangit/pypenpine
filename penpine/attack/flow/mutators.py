"""Pure flow mutations: return new immutable Flows, never mutate the base."""

from __future__ import annotations

from penpine.data.context import Context
from penpine.flow.flow import Flow
from penpine.flow.step import Step


def _with_actor(step, actor):
    return Step(
        step.name,
        actor=actor,
        request=step.request,
        action=step.action,
        capture=step.capture,
        guard=step.guard,
        recovery=step.recovery,
    )


def drop_step(flow, name_or_index) -> Flow:
    steps = flow.steps
    if isinstance(name_or_index, int):
        steps = [s for i, s in enumerate(steps) if i != name_or_index]
    else:
        steps = [s for s in steps if s.name != name_or_index]
    return Flow(steps=steps, actor=flow.actor, continue_on_error=flow.continue_on_error)


def swap_actor(flow, step_names, actor) -> Flow:
    names = set(step_names)
    steps = [_with_actor(s, actor) if s.name in names else s for s in flow.steps]
    return Flow(steps=steps, actor=flow.actor, continue_on_error=flow.continue_on_error)


def seed_context(flow, values) -> Flow:
    return Flow(
        steps=flow.steps,
        actor=flow.actor,
        context=Context(dict(values)),
        continue_on_error=flow.continue_on_error,
    )
