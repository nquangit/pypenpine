"""Flow: an ordered, conditional, recoverable sequence of requests."""

from __future__ import annotations

import asyncio
import inspect
import time

from penpine.data.capture import capture
from penpine.data.context import Context
from penpine.data.template import build_mapping, render
from penpine.flow.exceptions import FlowError, StepError
from penpine.flow.results import FlowResult, StepResult
from penpine.flow.step import StepOutcome


class FlowContext:
    """Passed to an escape-hatch step's `action` callable."""

    def __init__(self, ctx, actor):
        self.ctx = ctx
        self.actor = actor

    async def send(self, request, *, actor=None):
        target = actor or self.actor
        rendered = render(
            request, build_mapping(context=self.ctx, data=getattr(target, "data", None))
        )
        return await target.send(rendered)


class Flow:
    def __init__(self, steps, *, actor=None, context=None, continue_on_error=False):
        self._steps = list(steps)
        self._actor = actor
        self._ctx = context if context is not None else Context()
        self._continue_on_error = continue_on_error

    @property
    def steps(self):
        return list(self._steps)

    def step(self, name):
        for s in self._steps:
            if s.name == name:
                return s
        raise KeyError(name)

    async def run(self) -> FlowResult:
        return await self._execute(self._ctx, self._actor)

    def run_sync(self) -> FlowResult:
        return asyncio.run(self.run())

    async def _execute(self, ctx, default_actor) -> FlowResult:
        results = []
        for i, step in enumerate(self._steps):
            result = await self._run_step(step, ctx, default_actor)
            results.append(result)
            if result.status == "failed" and not self._continue_on_error:
                partial = FlowResult(steps=results, context=ctx.to_dict())
                raise StepError(step.name, index=i, result=partial)
        return FlowResult(steps=results, context=ctx.to_dict())

    async def _attempt(self, step, ctx, actor):
        start = time.perf_counter()
        request = response = error = None
        captured = []
        try:
            if step.action is not None:
                maybe = step.action(FlowContext(ctx, actor))
                response = await maybe if inspect.isawaitable(maybe) else maybe
            else:
                raw = step.request(ctx) if callable(step.request) else step.request
                request = render(raw, build_mapping(context=ctx, data=getattr(actor, "data", None)))
                response = await actor.send(request)
            if step.capture and response is not None:
                captured = list(capture(ctx, response, step.capture).keys())
        except Exception as exc:  # noqa: BLE001 - recorded on the StepResult, never leaked mid-step
            error = exc
        elapsed_ms = (time.perf_counter() - start) * 1000
        return request, response, error, captured, elapsed_ms

    async def _run_step(self, step, ctx, default_actor, *, allow_recovery=True):
        actor = step.actor or default_actor
        if actor is None and step.action is None:
            raise FlowError(f"step {step.name!r} has no actor to send with")

        if step.guard is not None:
            try:
                should_run = step.guard(ctx)
            except Exception as exc:  # noqa: BLE001 - a raising guard fails the step, never leaks
                return StepResult(step=step.name, actor=actor, status="failed", error=exc)
            if not should_run:
                return StepResult(step=step.name, actor=actor, status="skipped")

        request, response, error, captured, elapsed_ms = await self._attempt(step, ctx, actor)
        outcome = StepOutcome(ctx=ctx, actor=actor, response=response, error=error)

        if step.recovery is not None:
            try:
                triggered = step.recovery.when(outcome)
            except Exception as exc:  # noqa: BLE001 - a raising recovery predicate fails the step, never leaks
                return StepResult(
                    step=step.name,
                    actor=actor,
                    status="failed",
                    request=request,
                    response=response,
                    captured=captured,
                    recovery_ran=False,
                    error=error if error is not None else exc,
                    elapsed_ms=elapsed_ms,
                )
        else:
            triggered = False

        if not triggered:
            status = "failed" if error is not None else "ok"
            return StepResult(
                step=step.name,
                actor=actor,
                status=status,
                request=request,
                response=response,
                captured=captured,
                recovery_ran=False,
                error=error,
                elapsed_ms=elapsed_ms,
            )

        # A recovery condition fired.
        if not allow_recovery:
            # Already inside a retry — cannot recover again.
            return StepResult(
                step=step.name,
                actor=actor,
                status="failed",
                request=request,
                response=response,
                captured=captured,
                recovery_ran=True,
                error=error,
                elapsed_ms=elapsed_ms,
            )

        try:
            # Run the recovery sub-flow with ITS OWN default actor (falling back to
            # the parent's), while sharing the parent's context.
            await step.recovery.do._execute(ctx, step.recovery.do._actor or default_actor)
        except FlowError:
            return StepResult(
                step=step.name,
                actor=actor,
                status="failed",
                request=request,
                response=response,
                captured=captured,
                recovery_ran=True,
                error=error,
                elapsed_ms=elapsed_ms,
            )

        if step.recovery.retry:
            retry = await self._run_step(step, ctx, default_actor, allow_recovery=False)
            retry.recovery_ran = True
            if retry.status == "ok":
                retry.status = "recovered"
            return retry

        return StepResult(
            step=step.name,
            actor=actor,
            status="recovered",
            request=request,
            response=response,
            captured=captured,
            recovery_ran=True,
            error=error,
            elapsed_ms=elapsed_ms,
        )
