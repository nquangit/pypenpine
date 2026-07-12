from penpine.attack.flow.module import FlowAttackModule, FlowVariant
from penpine.attack.flow.results import FlowFinding, FlowReport
from penpine.attack.flow.runner import FlowRunner
from penpine.attack.models import Confidence
from penpine.attack.types import AttackType
from penpine.core.message import Request
from penpine.flow.flow import Flow
from penpine.flow.step import Step
from tests.flow._fakes import FakeActor, response


def _flow():
    return Flow(
        actor=FakeActor(script=[response(b"ok")]),
        steps=[Step("a", request=Request.from_url("http://t/a"))],
    )


class _StubModule(FlowAttackModule):
    attack_type = AttackType.BROKEN_ACCESS
    name = "stub"

    def __init__(self, *, n_variants=2, find_on=(), raise_on=()):
        self._n = n_variants
        self._find_on = set(find_on)
        self._raise_on = set(raise_on)

    def mutate(self, base_flow, baseline_result, targets):
        for i in range(self._n):
            yield FlowVariant(flow=_flow(), target=f"v{i}", meta={})

    def validate(self, variant, variant_result, baseline_result):
        if variant.target in self._raise_on:
            raise ValueError("validator boom")
        if variant.target in self._find_on:
            return FlowFinding(
                attack_type=self.attack_type,
                target=variant.target,
                confidence=Confidence.MEDIUM,
                evidence="stub",
                baseline_result=baseline_result,
                variant_result=variant_result,
            )
        return None


async def test_runner_runs_baseline_mutates_and_validates():
    report = await FlowRunner().run(_flow(), module=_StubModule(n_variants=3, find_on=["v1"]))
    assert isinstance(report, FlowReport)
    assert report.summary() == {"variants": 3, "failed": 0, "found": 1}
    assert report.findings[0].target == "v1"


async def test_runner_never_raises_on_validator_error():
    report = await FlowRunner().run(_flow(), module=_StubModule(n_variants=2, raise_on=["v0"]))
    assert report.summary()["failed"] == 1
    assert isinstance(report.errors[0].error, ValueError)


def test_run_sync_parity():
    report = FlowRunner().run_sync(_flow(), module=_StubModule(n_variants=1, find_on=["v0"]))
    assert report.summary() == {"variants": 1, "failed": 0, "found": 1}


async def test_runner_never_raises_on_variant_run_error():
    class _RaisingFlow:
        async def run(self):
            raise RuntimeError("variant boom")

    class _Mod(FlowAttackModule):
        attack_type = AttackType.BROKEN_ACCESS
        name = "raiser"

        def mutate(self, base_flow, baseline_result, targets):
            yield FlowVariant(flow=_RaisingFlow(), target="v0")

        def validate(self, variant, variant_result, baseline_result):
            return None

    report = await FlowRunner().run(_flow(), module=_Mod())
    assert report.summary()["failed"] == 1
    assert isinstance(report.errors[0].error, RuntimeError)
