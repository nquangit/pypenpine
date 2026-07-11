"""Runner: analyze -> generate -> send -> validate -> Report."""

from __future__ import annotations

import asyncio
import dataclasses
import threading
import time

from penpine.attack.analyze.analyzer import analyze
from penpine.attack.exceptions import AttackConfigError
from penpine.attack.models import Payload, TestCase
from penpine.attack.registry import get as _registry_get
from penpine.attack.results import Attempt, Report
from penpine.transport.engine import Engine


class Runner:
    def __init__(self, sender=None, *, max_concurrency=10, capture_baseline=True):
        self._sender = sender if sender is not None else Engine()
        self._max_concurrency = max_concurrency
        self._capture_baseline = capture_baseline
        self._loop = None
        self._loop_thread = None
        self._loop_lock = threading.Lock()

    def _resolve_module(self, attack, module):
        if module is not None:
            return module
        if attack is not None:
            return _registry_get(attack)
        return None

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
        attack=None,
        module=None,
        test_cases=None,
        points=None,
        validator=None,
        sender=None,
    ):
        """Run an attack and return a Report.

        Provide one of: `attack` (module name resolved from the registry),
        `module` (an AttackModule instance), or `test_cases` (explicit TestCases).
        Points to attack default to `analyze(request).for_attack(attack_type)`
        filtered by `module.applies(kind)`; note a module's name should match an
        analyzer attack-type tag or selection will be empty. Pass `points=` to
        override selection entirely (this BYPASSES the `applies` filter — it runs
        the generator on exactly the points you give). `sender` overrides the
        instance's sender for this call.
        """
        active_sender = sender if sender is not None else self._sender
        module = self._resolve_module(attack, module)
        attack_type = attack if attack is not None else (module.name if module else None)
        if module is not None and hasattr(module, "probe"):
            selection_tag = attack or getattr(module, "select_attack_type", None) or module.name
            selected = self._select_points(request, module, selection_tag, points)
            baseline = None
            if self._capture_baseline:
                try:
                    baseline = await active_sender.send(request)
                except Exception:
                    baseline = None
            semaphore = asyncio.Semaphore(self._max_concurrency)

            async def _bounded_probe(point):
                async with semaphore:
                    return await self._probe_attempt(
                        request, point, module, baseline, active_sender
                    )

            attempts = list(await asyncio.gather(*(_bounded_probe(p) for p in selected)))
            return Report(
                request=request, attack_type=attack_type, baseline=baseline, attempts=attempts
            )

        if validator is None and module is not None:
            validator = module.validator

        if test_cases is None:
            if module is None:
                raise AttackConfigError("run() requires one of attack=, module=, or test_cases=")
            cases = []
            for point in self._select_points(request, module, attack_type, points):
                cases.extend(module.generate(point, request))
            test_cases = cases
        else:
            test_cases = list(test_cases)

        baseline = None
        if self._capture_baseline:
            try:
                baseline = await active_sender.send(request)
            except Exception:
                baseline = None

        semaphore = asyncio.Semaphore(self._max_concurrency)

        async def _bounded(tc):
            async with semaphore:
                return await self._attempt(request, tc, validator, baseline, active_sender)

        attempts = list(await asyncio.gather(*(_bounded(tc) for tc in test_cases)))
        return Report(
            request=request, attack_type=attack_type, baseline=baseline, attempts=attempts
        )

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
            point=point, payload=Payload("<differential>"), attack_type=module.name
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
        future = asyncio.run_coroutine_threadsafe(self.run(request, **kwargs), self._loop)
        return future.result()

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
