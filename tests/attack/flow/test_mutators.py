from penpine.attack.flow.mutators import drop_step, seed_context, swap_actor
from penpine.core.message import Request
from penpine.flow.flow import Flow
from penpine.flow.step import Step
from tests.flow._fakes import FakeActor


def _base():
    return Flow(
        actor=FakeActor(name="alice"),
        continue_on_error=True,
        steps=[
            Step("login", request=Request.from_url("http://t/login")),
            Step("act", request=Request.from_url("http://t/act")),
            Step("confirm", request=Request.from_url("http://t/confirm")),
        ],
    )


def test_drop_step_by_name_returns_new_flow_without_it():
    base = _base()
    variant = drop_step(base, "act")
    assert [s.name for s in variant.steps] == ["login", "confirm"]
    # base unchanged
    assert [s.name for s in base.steps] == ["login", "act", "confirm"]
    # config carried over
    assert variant.actor is base.actor
    assert variant.continue_on_error is True


def test_drop_step_by_index():
    variant = drop_step(_base(), 0)
    assert [s.name for s in variant.steps] == ["act", "confirm"]


def test_swap_actor_replaces_actor_on_named_steps_only():
    base = _base()
    bob = FakeActor(name="bob")
    variant = swap_actor(base, ["act", "confirm"], bob)
    names_to_actor = {s.name: s.actor for s in variant.steps}
    assert names_to_actor["login"] is None          # untouched (used flow default)
    assert names_to_actor["act"] is bob
    assert names_to_actor["confirm"] is bob
    # base steps unchanged
    assert all(s.actor is None for s in base.steps)


def test_seed_context_preseeds_the_flow_context():
    base = _base()
    variant = seed_context(base, {"doc_id": "42"})
    # the variant's context starts with the seeded value
    assert variant._ctx.get("doc_id") == "42"
    assert [s.name for s in variant.steps] == ["login", "act", "confirm"]
