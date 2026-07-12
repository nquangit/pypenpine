from penpine.core.message import Request
from penpine.flow.flow import Flow, FlowContext
from penpine.flow.step import Step
from tests.flow._fakes import FakeActor, response


async def test_sync_action_step_runs():
    calls = []

    def action(fc):
        assert isinstance(fc, FlowContext)
        fc.ctx.set("flag", "set-by-action")
        calls.append(fc)
        return None

    flow = Flow(steps=[Step("compute", action=action)])
    result = await flow.run()
    assert result.step("compute").status == "ok"
    assert result.context["flag"] == "set-by-action"
    assert len(calls) == 1


async def test_async_action_can_send_via_flow_context():
    actor = FakeActor(script=[response(b"pong")])

    async def action(fc):
        return await fc.send(Request.from_url("http://t/ping"), actor=actor)

    flow = Flow(steps=[Step("ping", action=action)])
    result = await flow.run()
    assert result.step("ping").status == "ok"
    assert len(actor.sent) == 1
    assert result.step("ping").response.body.text() == "pong"
