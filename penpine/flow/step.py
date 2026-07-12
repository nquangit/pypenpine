"""Step, Recovery, and StepOutcome — the flow's declarative units."""

from __future__ import annotations

from dataclasses import dataclass

from penpine.flow.exceptions import FlowError


@dataclass
class StepOutcome:
    """Read-only view passed to Recovery.when after a step is attempted."""

    ctx: object
    actor: object
    response: object | None = None
    error: object | None = None


@dataclass
class Recovery:
    when: object  # Callable[[StepOutcome], bool]
    do: object  # a Flow, run with the parent's shared context
    retry: bool = True


class Step:
    def __init__(
        self,
        name,
        *,
        actor=None,
        request=None,
        action=None,
        capture=None,
        guard=None,
        recovery=None,
    ):
        if (request is None) == (action is None):
            raise FlowError(f"step {name!r} requires exactly one of `request` or `action`")
        self.name = name
        self.actor = actor
        self.request = request
        self.action = action
        self.capture = capture
        self.guard = guard
        self.recovery = recovery
