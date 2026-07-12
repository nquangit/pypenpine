import pytest

from penpine.core.message import Request
from penpine.flow.exceptions import FlowError
from penpine.flow.step import Recovery, Step, StepOutcome


def test_step_stores_fields():
    req = Request.from_url("http://h/")
    s = Step("login", request=req, capture=["x"], actor="alice")
    assert s.name == "login"
    assert s.request is req
    assert s.action is None
    assert s.capture == ["x"]
    assert s.actor == "alice"
    assert s.guard is None
    assert s.recovery is None


def test_step_action_variant():
    fn = lambda fc: None
    s = Step("probe", action=fn)
    assert s.action is fn
    assert s.request is None


def test_step_requires_exactly_one_of_request_or_action():
    with pytest.raises(FlowError):
        Step("bad")  # neither
    with pytest.raises(FlowError):
        Step("bad", request=Request.from_url("http://h/"), action=lambda fc: None)  # both


def test_step_outcome_defaults():
    o = StepOutcome(ctx="c", actor="a")
    assert o.response is None
    assert o.error is None


def test_recovery_defaults_retry_true():
    r = Recovery(when=lambda o: True, do="subflow")
    assert r.retry is True
    assert r.do == "subflow"
