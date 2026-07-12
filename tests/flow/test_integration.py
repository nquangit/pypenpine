from penpine.core.message import Request
from penpine.data.extract import Extract
from penpine.flow.flow import Flow
from penpine.flow.step import Step
from tests.flow._fakes import FakeActor, response


async def test_multi_actor_shared_context_threads_data():
    # alice creates a doc, bob accesses it using alice's captured id (IDOR shape).
    alice = FakeActor(
        name="alice",
        script=[response(b'{"id":"42"}', headers=b"Content-Type: application/json\r\n")],
    )
    bob = FakeActor(name="bob", script=[response(b"seen")])

    flow = Flow(
        actor=alice,
        steps=[
            Step(
                "create",
                request=Request.from_url("http://t/docs"),
                capture=[Extract("doc_id", json="$.id")],
            ),
            Step("access", actor=bob, request=Request.from_url("http://t/docs/{{doc_id}}")),
        ],
    )
    result = await flow.run()
    assert result.context["doc_id"] == "42"
    assert b"/docs/42" in bob.sent[0].serialize()
    assert alice.sent and bob.sent  # both actors used, one shared context


def test_run_sync_matches_run():
    actor = FakeActor(script=[response(b"ok")])
    flow = Flow(actor=actor, steps=[Step("a", request=Request.from_url("http://t/a"))])
    result = flow.run_sync()  # plain sync call, no await
    assert result.step("a").status == "ok"
    assert result.summary() == {"ran": 1, "skipped": 0, "recovered": 0, "failed": 0}
