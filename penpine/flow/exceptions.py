"""Flow-engine exception hierarchy."""

from __future__ import annotations

from penpine.exceptions import PenpineError


class FlowError(PenpineError):
    """Base class for flow-engine errors."""


class StepError(FlowError):
    """A flow step failed and was not recovered.

    Carries the partial ``FlowResult`` accumulated up to and including the
    failing step (``result``) so a fail-fast caller still sees the progress
    made, the underlying exception that failed the step (``cause``), and the
    failing step's HTTP status if it got a response (``status``). The message
    spells out the cause and status so a bare traceback is already legible; the
    exception is also chained (``raise ... from cause``) so the real traceback
    is shown too.
    """

    def __init__(self, name, *, index=None, result=None, cause=None, status=None):
        self.name = name
        self.index = index
        self.result = result
        self.cause = cause
        self.status = status
        detail = f" (index {index})" if index is not None else ""
        reasons = []
        if status is not None:
            reasons.append(f"HTTP {status}")
        if cause is not None:
            reasons.append(f"{type(cause).__name__}: {cause}")
        reason = f" — {'; '.join(reasons)}" if reasons else ""
        super().__init__(f"flow step {name!r} failed{detail}{reason}")
