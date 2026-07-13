"""FlowRunner: baseline -> mutate -> run variants -> validate -> FlowReport."""

from __future__ import annotations

import asyncio
import inspect

from penpine.attack.exceptions import AttackConfigError
from penpine.attack.flow.results import FlowAttempt, FlowReport
from penpine.flow.exceptions import StepError


class FlowRunner:
    """Runs a base flow's baseline, then each module's variants, then validates each.

    Variants share the base flow's actor(s). Concurrent variant runs
    (max_concurrency > 1) interleave every real `await actor.send(...)`, so
    against a STATEFUL actor (a SessionManager/Engine holding cookies,
    tokens, or a live connection) they can clobber each other's session
    state. Use an isolatable/stateless actor, or set max_concurrency=1, for
    stateful actors.
    """

    def __init__(self, *, max_concurrency=10):
        self._max_concurrency = max_concurrency

    def _resolve_modules(self, module):
        items = module if isinstance(module, (list, tuple)) else [module]
        out = []
        for m in items:
            if not isinstance(m, type):
                out.append(m)
                continue
            # Validate no-arg constructability BEFORE instantiating, so a TypeError
            # raised inside the module's own __init__ body propagates unmasked.
            try:
                inspect.signature(m).bind()
            except TypeError as exc:
                raise AttackConfigError(
                    f"module class {m.__name__} needs constructor arguments; "
                    f"pass an instance instead"
                ) from exc
            out.append(m())
        return out

    async def _run_to_result(self, flow):
        """Run a flow, returning its FlowResult (full, or the partial from a fail-fast)."""
        try:
            return await flow.run()
        except StepError as exc:
            return exc.result

    async def _run_variant(self, mod, variant, baseline, semaphore):
        async with semaphore:
            try:
                result = await self._run_to_result(variant.flow)
            except Exception as exc:  # noqa: BLE001 - recorded on the attempt, never leaks
                return FlowAttempt(variant=variant, error=exc)
            try:
                finding = mod.validate(variant, result, baseline)
            except Exception as exc:  # noqa: BLE001
                return FlowAttempt(variant=variant, variant_result=result, error=exc)
            return FlowAttempt(variant=variant, variant_result=result, finding=finding)

    async def run(self, base_flow, *, module, targets=None) -> FlowReport:
        modules = self._resolve_modules(module)
        baseline = await self._run_to_result(base_flow)
        semaphore = asyncio.Semaphore(self._max_concurrency)

        tasks = []
        for mod in modules:
            for variant in mod.mutate(base_flow, baseline, targets):
                tasks.append(self._run_variant(mod, variant, baseline, semaphore))
        attempts = list(await asyncio.gather(*tasks))

        attack_type = modules[0].attack_type if len(modules) == 1 else None
        return FlowReport(
            base_flow=base_flow,
            attack_type=attack_type,
            baseline=baseline,
            attempts=attempts,
        )

    def run_sync(self, base_flow, **kwargs) -> FlowReport:
        return asyncio.run(self.run(base_flow, **kwargs))
