import pytest

from penpine.core.message import Request
from penpine.data.extract import Extract
from penpine.flow.exceptions import StepError
from penpine.flow.flow import Flow
from penpine.flow.results import FlowResult
from penpine.flow.step import Step
from tests.flow._fakes import FakeActor, response


async def test_linear_happy_path_threads_captured_data():
    actor = FakeActor(
        script=[
            response(b'{"token":"abc"}', headers=b"Content-Type: application/json\r\n"),
            response(b"done"),
        ]
    )
    flow = Flow(
        actor=actor,
        steps=[
            Step(
                "login",
                request=Request.from_url("http://t/login"),
                capture=[Extract("token", json="$.token")],
            ),
            Step("act", request=Request.from_url("http://t/do?tok={{token}}")),
        ],
    )
    result = await flow.run()
    assert isinstance(result, FlowResult)
    assert [s.status for s in result] == ["ok", "ok"]
    assert result.context["token"] == "abc"
    # second request was rendered with the captured token
    assert b"tok=abc" in actor.sent[1].serialize()


async def test_guard_skips_step():
    actor = FakeActor(script=[response(b"x")])
    flow = Flow(
        actor=actor,
        steps=[
            Step(
                "activate",
                request=Request.from_url("http://t/activate"),
                guard=lambda ctx: ctx.has("needs_activation"),
            ),
            Step("login", request=Request.from_url("http://t/login")),
        ],
    )
    result = await flow.run()
    assert [s.status for s in result] == ["skipped", "ok"]
    assert len(actor.sent) == 1  # only login sent


async def test_fail_fast_raises_step_error_with_partial_result():
    def boom(request):
        raise RuntimeError("network down")

    actor = FakeActor(script=[response(b"ok"), boom])
    flow = Flow(
        actor=actor,
        steps=[
            Step("first", request=Request.from_url("http://t/a")),
            Step("second", request=Request.from_url("http://t/b")),
            Step("third", request=Request.from_url("http://t/c")),
        ],
    )
    with pytest.raises(StepError) as ei:
        await flow.run()
    err = ei.value
    assert err.name == "second"
    assert err.index == 1
    assert [s.status for s in err.result] == ["ok", "failed"]  # third never ran


async def test_raising_guard_becomes_failed_step_with_partial_result():
    def boom_guard(ctx):
        raise ValueError("guard blew up")

    actor = FakeActor(script=[response(b"ok")])
    flow = Flow(
        actor=actor,
        steps=[
            Step("a", request=Request.from_url("http://t/a")),
            Step("b", request=Request.from_url("http://t/b"), guard=boom_guard),
            Step("c", request=Request.from_url("http://t/c")),
        ],
    )
    with pytest.raises(StepError) as ei:
        await flow.run()
    assert ei.value.name == "b"
    assert isinstance(ei.value.result.step("b").error, ValueError)
    assert [s.status for s in ei.value.result] == ["ok", "failed"]  # c never ran
    assert len(actor.sent) == 1  # only step a sent; guard failed before b's send


async def test_continue_on_error_records_and_proceeds():
    def boom(request):
        raise RuntimeError("nope")

    actor = FakeActor(script=[response(b"ok"), boom, response(b"ok")])
    flow = Flow(
        actor=actor,
        continue_on_error=True,
        steps=[
            Step("a", request=Request.from_url("http://t/a")),
            Step("b", request=Request.from_url("http://t/b")),
            Step("c", request=Request.from_url("http://t/c")),
        ],
    )
    result = await flow.run()
    assert [s.status for s in result] == ["ok", "failed", "ok"]
    assert isinstance(result.step("b").error, RuntimeError)


async def test_callable_request_built_from_context():
    actor = FakeActor(
        script=[
            response(b'{"id":"9"}', headers=b"Content-Type: application/json\r\n"),
            response(b"ok"),
        ]
    )
    flow = Flow(
        actor=actor,
        steps=[
            Step(
                "create",
                request=Request.from_url("http://t/new"),
                capture=[Extract("rid", json="$.id")],
            ),
            Step(
                "use", request=lambda ctx: Request.from_url(f"http://t/item/{ctx.require('rid')}")
            ),
        ],
    )
    result = await flow.run()
    assert result.step("use").status == "ok"
    assert b"/item/9" in actor.sent[1].serialize()
