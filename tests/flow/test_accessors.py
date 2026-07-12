from penpine.core.message import Request
from penpine.flow.flow import Flow
from penpine.flow.step import Step
from tests.flow._fakes import FakeActor


def test_flow_exposes_actor_and_continue_on_error():
    actor = FakeActor()
    flow = Flow(
        actor=actor,
        continue_on_error=True,
        steps=[Step("a", request=Request.from_url("http://t/a"))],
    )
    assert flow.actor is actor
    assert flow.continue_on_error is True


def test_flow_defaults_actor_none_continue_false():
    flow = Flow(steps=[Step("a", request=Request.from_url("http://t/a"))], actor=FakeActor())
    assert flow.continue_on_error is False
