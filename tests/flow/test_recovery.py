import pytest

from penpine.core.message import Request
from penpine.flow.exceptions import StepError
from penpine.flow.flow import Flow
from penpine.flow.step import Recovery, Step
from tests.flow._fakes import FakeActor, response


async def test_recovery_runs_subflow_then_retry_succeeds():
    # login returns 409 (needs activation) first, then 200 after activation ran.
    login_actor = FakeActor(
        script=[response(b"needs activation", status=b"409 Conflict"), response(b"ok")]
    )
    activate_actor = FakeActor(script=[response(b"activated")])

    activation = Flow(
        actor=activate_actor,
        steps=[Step("activate", request=Request.from_url("http://t/activate"))],
    )

    flow = Flow(
        actor=login_actor,
        steps=[
            Step(
                "login",
                request=Request.from_url("http://t/login"),
                recovery=Recovery(
                    when=lambda o: o.response is not None and o.response.status_code == 409,
                    do=activation,
                    retry=True,
                ),
            ),
        ],
    )
    result = await flow.run()
    assert result.step("login").status == "recovered"
    assert result.step("login").recovery_ran is True
    assert len(login_actor.sent) == 2  # initial + retry
    assert len(activate_actor.sent) == 1  # recovery subflow ran once


async def test_recovery_exhausted_when_condition_persists():
    # login always returns 409; recovery runs, retry still 409 -> failed.
    login_actor = FakeActor(script=[response(b"needs activation", status=b"409 Conflict")])
    activate_actor = FakeActor(script=[response(b"activated")])
    activation = Flow(
        actor=activate_actor,
        steps=[Step("activate", request=Request.from_url("http://t/activate"))],
    )

    flow = Flow(
        actor=login_actor,
        steps=[
            Step(
                "login",
                request=Request.from_url("http://t/login"),
                recovery=Recovery(
                    when=lambda o: o.response is not None and o.response.status_code == 409,
                    do=activation,
                    retry=True,
                ),
            ),
        ],
    )
    with pytest.raises(StepError):
        await flow.run()
    # retry attempted exactly once beyond the original
    assert len(login_actor.sent) == 2


async def test_recovery_on_exception_then_retry_succeeds():
    def boom(request):
        raise RuntimeError("transient")

    actor = FakeActor(script=[boom, response(b"ok")])
    healer = Flow(
        actor=FakeActor(script=[response(b"healed")]),
        steps=[Step("heal", request=Request.from_url("http://t/heal"))],
    )
    flow = Flow(
        actor=actor,
        steps=[
            Step(
                "call",
                request=Request.from_url("http://t/call"),
                recovery=Recovery(when=lambda o: o.error is not None, do=healer, retry=True),
            )
        ],
    )
    result = await flow.run()
    assert result.step("call").status == "recovered"


async def test_recovery_without_retry_marks_recovered():
    actor = FakeActor(script=[response(b"needs activation", status=b"409 Conflict")])
    activation = Flow(
        actor=FakeActor(script=[response(b"activated")]),
        steps=[Step("activate", request=Request.from_url("http://t/activate"))],
    )
    flow = Flow(
        actor=actor,
        steps=[
            Step(
                "login",
                request=Request.from_url("http://t/login"),
                recovery=Recovery(
                    when=lambda o: o.response.status_code == 409, do=activation, retry=False
                ),
            )
        ],
    )
    result = await flow.run()
    assert result.step("login").status == "recovered"
    assert len(actor.sent) == 1  # no retry


async def test_recovery_subflow_failure_marks_step_failed():
    # When the recovery sub-flow itself fails, the step stays failed (recovery_ran True).
    def boom(request):
        raise RuntimeError("activation service down")

    login_actor = FakeActor(script=[response(b"needs activation", status=b"409 Conflict")])
    broken_activation = Flow(
        actor=FakeActor(script=[boom]),
        steps=[Step("activate", request=Request.from_url("http://t/activate"))],
    )
    flow = Flow(
        actor=login_actor,
        steps=[
            Step(
                "login",
                request=Request.from_url("http://t/login"),
                recovery=Recovery(
                    when=lambda o: o.response is not None and o.response.status_code == 409,
                    do=broken_activation,
                    retry=True,
                ),
            )
        ],
    )
    with pytest.raises(StepError) as ei:
        await flow.run()
    login_result = ei.value.result.step("login")
    assert login_result.status == "failed"
    assert login_result.recovery_ran is True
    assert len(login_actor.sent) == 1  # sub-flow failed before any retry


async def test_raising_recovery_predicate_on_send_failure_surfaces_send_error():
    # A response-shaped predicate crashing on a send failure must fail the step, not leak.
    def bad_when(outcome):
        return outcome.response.status_code == 409  # AttributeError when response is None

    def boom(request):
        raise RuntimeError("connection refused")

    actor = FakeActor(script=[boom])
    activation = Flow(
        actor=FakeActor(script=[response(b"activated")]),
        steps=[Step("activate", request=Request.from_url("http://t/activate"))],
    )
    flow = Flow(
        actor=actor,
        steps=[
            Step(
                "login",
                request=Request.from_url("http://t/login"),
                recovery=Recovery(when=bad_when, do=activation, retry=True),
            ),
        ],
    )
    with pytest.raises(StepError) as ei:
        await flow.run()
    login = ei.value.result.step("login")
    assert login.status == "failed"
    assert isinstance(login.error, RuntimeError)  # original send error preserved
    assert login.recovery_ran is False


async def test_recovery_predicate_bug_on_success_is_recorded():
    def bad_when(outcome):
        raise ValueError("predicate bug")

    actor = FakeActor(script=[response(b"ok")])
    activation = Flow(
        actor=FakeActor(script=[response(b"x")]),
        steps=[Step("a", request=Request.from_url("http://t/a"))],
    )
    flow = Flow(
        actor=actor,
        steps=[
            Step(
                "s",
                request=Request.from_url("http://t/s"),
                recovery=Recovery(when=bad_when, do=activation),
            )
        ],
    )
    with pytest.raises(StepError) as ei:
        await flow.run()
    assert isinstance(ei.value.result.step("s").error, ValueError)


async def test_recovery_subflow_inherits_parent_actor_when_it_has_none():
    # Recovery sub-flow with no actor of its own falls back to the parent's default actor.
    actor = FakeActor(
        script=[
            response(b"needs activation", status=b"409 Conflict"),  # login attempt 1
            response(b"activated"),  # recovery activate (fallback actor)
            response(b"ok"),  # login retry
        ]
    )
    activation = Flow(steps=[Step("activate", request=Request.from_url("http://t/activate"))])
    flow = Flow(
        actor=actor,
        steps=[
            Step(
                "login",
                request=Request.from_url("http://t/login"),
                recovery=Recovery(
                    when=lambda o: o.response is not None and o.response.status_code == 409,
                    do=activation,
                    retry=True,
                ),
            ),
        ],
    )
    result = await flow.run()
    assert result.step("login").status == "recovered"
    assert len(actor.sent) == 3  # login, activate (via fallback actor), login retry
