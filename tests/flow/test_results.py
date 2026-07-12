import pytest

from penpine.flow.results import FlowResult, StepResult


def make(status, name="s"):
    return StepResult(step=name, actor=None, status=status)


def test_step_result_defaults():
    r = StepResult(step="login", actor=None, status="ok")
    assert r.captured == []
    assert r.recovery_ran is False
    assert r.error is None
    assert r.elapsed_ms is None


def test_flow_result_ok_true_when_no_failure():
    fr = FlowResult(steps=[make("ok"), make("skipped"), make("recovered")], context={})
    assert fr.ok is True
    assert fr.failed_step is None


def test_flow_result_ok_false_with_failure():
    failed = make("failed", "boom")
    fr = FlowResult(steps=[make("ok"), failed], context={})
    assert fr.ok is False
    assert fr.failed_step is failed


def test_flow_result_step_lookup_and_iter():
    a, b = make("ok", "a"), make("ok", "b")
    fr = FlowResult(steps=[a, b], context={"k": "v"})
    assert fr.step("b") is b
    assert list(fr) == [a, b]
    with pytest.raises(KeyError):
        fr.step("missing")


def test_flow_result_summary_counts():
    fr = FlowResult(
        steps=[make("ok"), make("ok"), make("skipped"), make("recovered"), make("failed")],
        context={},
    )
    assert fr.summary() == {"ran": 3, "skipped": 1, "recovered": 1, "failed": 1}
