"""FlowRunner: baseline -> mutate -> run variants -> validate -> FlowReport."""

from __future__ import annotations

import asyncio

from penpine.attack.flow.results import FlowAttempt, FlowReport
from penpine.flow.exceptions import StepError


class FlowRunner:
    """Runs a base flow's baseline, then a module's variants, then validates each.

    Variants share the base flow's actor(s). Concurrent variant runs
    (max_concurrency > 1) interleave every real `await actor.send(...)`, so
    against a STATEFUL actor (a SessionManager/Engine holding cookies,
    tokens, or a live connection) they can clobber each other's session
    state. Use an isolatable/stateless actor, or set max_concurrency=1, for
    stateful actors.
    """

    def __init__(self, *, max_concurrency=10):
        self._max_concurrency = max_concurrency

    async def _run_to_result(self, flow):
        """Run a flow, returning its FlowResult (full, or the partial from a fail-fast)."""
        try:
            return await flow.run()
        except StepError as exc:
            return exc.result

    async def run(self, base_flow, *, module, targets=None) -> FlowReport:
        baseline = await self._run_to_result(base_flow)
        variants = list(module.mutate(base_flow, baseline, targets))
        semaphore = asyncio.Semaphore(self._max_concurrency)

        async def _attempt(variant):
            async with semaphore:
                try:
                    result = await self._run_to_result(variant.flow)
                except Exception as exc:  # noqa: BLE001 - recorded on the attempt, never leaks
                    return FlowAttempt(variant=variant, error=exc)
                try:
                    finding = module.validate(variant, result, baseline)
                except Exception as exc:  # noqa: BLE001
                    return FlowAttempt(variant=variant, variant_result=result, error=exc)
                return FlowAttempt(variant=variant, variant_result=result, finding=finding)

        attempts = list(await asyncio.gather(*(_attempt(v) for v in variants)))
        return FlowReport(
            base_flow=base_flow,
            attack_type=getattr(module, "attack_type", None),
            baseline=baseline,
            attempts=attempts,
        )

    def run_sync(self, base_flow, **kwargs) -> FlowReport:
        return asyncio.run(self.run(base_flow, **kwargs))
