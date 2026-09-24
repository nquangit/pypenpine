from penpine.exceptions import PenpineError
from penpine.flow.exceptions import FlowError, StepError


def test_flow_error_is_penpine_error():
    assert issubclass(FlowError, PenpineError)


def test_step_error_carries_name_index_and_result():
    err = StepError("login", index=2, result="sentinel")
    assert isinstance(err, FlowError)
    assert err.name == "login"
    assert err.index == 2
    assert err.result == "sentinel"
    assert "login" in str(err)


def test_step_error_defaults():
    err = StepError("activate")
    assert err.index is None
    assert err.result is None
    assert err.cause is None
    assert err.status is None


def test_step_error_message_spells_out_cause_and_status():
    cause = ValueError("boom")
    err = StepError("pay", index=1, cause=cause, status=401)
    assert err.cause is cause
    assert err.status == 401
    text = str(err)
    assert "pay" in text
    assert "index 1" in text
    assert "HTTP 401" in text
    assert "ValueError: boom" in text
