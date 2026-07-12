from penpine.attack.flow.results import FlowAttempt, FlowFinding, FlowReport
from penpine.attack.models import Confidence
from penpine.attack.types import AttackType


def _finding():
    return FlowFinding(
        attack_type=AttackType.BROKEN_ACCESS,
        target="drop:authz",
        confidence=Confidence.HIGH,
        evidence="goal still succeeded",
        baseline_result="B",
        variant_result="V",
    )


def test_attempt_flags():
    ok = FlowAttempt(variant="v", variant_result="r", finding=_finding())
    assert ok.found is True
    assert ok.ok is True
    err = FlowAttempt(variant="v", error=RuntimeError("x"))
    assert err.found is False
    assert err.ok is False


def test_report_aggregates():
    f = _finding()
    report = FlowReport(
        base_flow="F",
        attack_type=AttackType.BROKEN_ACCESS,
        baseline="B",
        attempts=[
            FlowAttempt(variant="a", variant_result="r", finding=f),
            FlowAttempt(variant="b", variant_result="r", finding=None),
            FlowAttempt(variant="c", error=RuntimeError("x")),
        ],
    )
    assert report.findings == [f]
    assert len(report.errors) == 1
    assert report.summary() == {"variants": 3, "failed": 1, "found": 1}
    assert len(list(report)) == 3
