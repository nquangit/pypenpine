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
