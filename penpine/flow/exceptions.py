"""Flow-engine exception hierarchy."""

from __future__ import annotations

from penpine.exceptions import PenpineError


class FlowError(PenpineError):
    """Base class for flow-engine errors."""


class StepError(FlowError):
    """A flow step failed and was not recovered.

    Carries the partial ``FlowResult`` accumulated up to and including the
    failing step so a fail-fast caller still sees the progress made.
    """

    def __init__(self, name, *, index=None, result=None):
        self.name = name
        self.index = index
        self.result = result
        detail = f" (index {index})" if index is not None else ""
        super().__init__(f"flow step {name!r} failed{detail}")
