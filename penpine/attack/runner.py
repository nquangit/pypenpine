"""Runner: analyze -> generate -> send -> validate -> Report."""

from __future__ import annotations

import asyncio
import dataclasses
import inspect
import threading
import time

from penpine._sync import run_on_loop
from penpine.attack.analyze.analyzer import analyze
from penpine.attack.exceptions import AttackConfigError
from penpine.attack.models import Payload, TestCase
from penpine.attack.registry import by_type as _registry_by_type
from penpine.attack.results import Attempt, Report
from penpine.attack.types import AttackType
from penpine.transport.engine import Engine


class Runner:
    def __init__(self, sender=None, *, max_concurrency=10, capture_baseline=True):
        self._sender = sender if sender is not None else Engine()
        self._max_concurrency = max_concurrency
        self._capture_baseline = capture_baseline
        self._loop = None
        self._loop_thread = None
        self._loop_lock = threading.Lock()

    def _instantiate(self, m):
        if not isinstance(m, type):
            return m
        try:
            inspect.signature(m).bind()
        except TypeError as exc:
            raise AttackConfigError(
                f"module class {m.__name__} needs constructor arguments; pass an instance instead"
            ) from exc
        return m()

    def _resolve_modules(self, attack, module):
        modules = []
        if module is not None:
            items = module if isinstance(module, (list, tuple)) else [module]
            modules += [self._instantiate(m) for m in items]
        if attack is not None:
            attacks = attack if isinstance(attack, (list, tuple)) else [attack]
            for a in attacks:
                modules += _registry_by_type(a, signature_only=True)
        return modules

    def _select_points(self, request, module, attack_type, points):
        if points is not None:
            return list(points)
        analysis = analyze(request)
        selected = analysis.for_attack(attack_type) if attack_type else analysis.all()
        return [p for p in selected if module is None or module.applies(p.kind)]

    async def run(
        self,
        request,
        *,
        attack: AttackType | list[AttackType] | None = None,
        module=None,
        test_cases=None,
        points=None,
        validator=None,
        sender=None,
    ):
        """Run an attack and return a Report.

        Provide one of: `attack` (an `AttackType` or list of `AttackType`s,
        resolved to registered signature modules via `registry.by_type`), `module`
        (an `AttackModule`/`DifferentialModule` instance/class or list of them --
        a class is instantiated no-arg), or `test_cases` (explicit `TestCase`s, no
        module involved). Points to attack default to `analyze(request).for_attack(mod.attack_type)`
        filtered by `module.applies(kind)` for each resolved module. Pass `points=`
        to override selection entirely (this BYPASSES the `applies` filter -- it
        runs the generator/prober on exactly the points you give). `sender`
        overrides the instance's sender for this call.

        A category (`attack=`) only resolves signature modules -- differential
        (active-prober) modules are opt-in via `module=`. Each resolved module
        that exposes `probe` takes the active-prober path (one probe per
        selected point); other modules go through generate -> send -> validate
        using that module's own validator. All resolved modules' attempts are
        aggregated into a single `Report`.
        """
        active_sender = sender if sender is not None else self._sender

        # Explicit test-cases path (no module).
        if test_cases is not None:
            cases = list(test_cases)
            baseline = await self._baseline(request, active_sender)
            attempts = await self._run_cases(request, cases, validator, baseline, active_sender)
            return Report(request=request, attack_type=None, baseline=baseline, attempts=attempts)

        modules = self._resolve_modules(attack, module)
        if not modules:
            raise AttackConfigError("run() requires one of attack=, module=, or test_cases=")

        baseline = await self._baseline(request, active_sender)
        attack_type = modules[0].attack_type if len(modules) == 1 else None

        attempts = []
        for mod in modules:
            selected = self._select_points(request, mod, mod.attack_type, points)
            if hasattr(mod, "probe"):
                attempts += await self._run_probes(request, selected, mod, baseline, active_sender)
            else:
                cases = []
                for point in selected:
                    cases.extend(mod.generate(point, request))
                attempts += await self._run_cases(
                    request, cases, mod.validator, baseline, active_sender
                )

        return Report(
            request=request, attack_type=attack_type, baseline=baseline, attempts=attempts
        )

    async def _baseline(self, request, sender):
        if not self._capture_baseline:
            return None
        try:
            return await sender.send(request)
        except Exception:
            return None

    async def _run_cases(self, request, cases, validator, baseline, sender):
        semaphore = asyncio.Semaphore(self._max_concurrency)

        async def _bounded(tc):
            async with semaphore:
                return await self._attempt(request, tc, validator, baseline, sender)

        return list(await asyncio.gather(*(_bounded(tc) for tc in cases)))

    async def _run_probes(self, request, points, module, baseline, sender):
        semaphore = asyncio.Semaphore(self._max_concurrency)

        async def _bounded(point):
            async with semaphore:
                return await self._probe_attempt(request, point, module, baseline, sender)

        return list(await asyncio.gather(*(_bounded(p) for p in points)))

    async def _attempt(self, base, test_case, validator, baseline, sender):
        start = time.perf_counter()
        try:
            req = (
                test_case.request
                if test_case.request is not None
                else base.replace_at(test_case.point.expr, test_case.payload.value)
            )
        except Exception as exc:
            return Attempt(test_case=test_case, error=exc)

        sent_tc = dataclasses.replace(test_case, request=req)
        try:
            response = await sender.send(req)
        except Exception as exc:
            return Attempt(
                test_case=sent_tc,
                request=req,
                error=exc,
                elapsed_ms=(time.perf_counter() - start) * 1000,
            )

        finding = None
        if validator is not None:
            try:
                finding = validator.evaluate(sent_tc, response, baseline)
            except Exception as exc:
                return Attempt(
                    test_case=sent_tc,
                    request=req,
                    response=response,
                    error=exc,
                    elapsed_ms=(time.perf_counter() - start) * 1000,
                )

        return Attempt(
            test_case=sent_tc,
            request=req,
            response=response,
            finding=finding,
            elapsed_ms=(time.perf_counter() - start) * 1000,
        )

    async def _probe_attempt(self, request, point, module, baseline, sender):
        placeholder = TestCase(
            point=point, payload=Payload("<differential>"), attack_type=module.attack_type
        )
        try:
            finding = await module.probe(point, request, sender, baseline=baseline)
        except Exception as exc:
            return Attempt(test_case=placeholder, error=exc)
        return Attempt(
            test_case=placeholder,
            request=getattr(finding, "request", None),
            response=getattr(finding, "response", None),
            finding=finding,
        )

    def _ensure_loop(self):
        with self._loop_lock:
            if self._loop is None:
                self._loop = asyncio.new_event_loop()
                self._loop_thread = threading.Thread(target=self._loop.run_forever, daemon=True)
                self._loop_thread.start()

    def run_sync(self, request, **kwargs):
        self._ensure_loop()
        return run_on_loop(self._loop, self.run(request, **kwargs))

    def close(self):
        if self._loop is not None:
            self._loop.call_soon_threadsafe(self._loop.stop)
            self._loop_thread.join(timeout=2)
            self._loop.close()
            self._loop = None
            self._loop_thread = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
