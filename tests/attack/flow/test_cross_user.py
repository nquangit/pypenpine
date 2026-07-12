from penpine.attack.flow.modules.cross_user import CrossUserModule
from penpine.attack.flow.runner import FlowRunner
from penpine.attack.types import AttackType
from penpine.core.message import Request
from penpine.data.extract import Extract
from penpine.flow.flow import Flow
from penpine.flow.step import Step
from tests.flow._fakes import FakeActor, response


def _owned_doc_actor(*, enforce_owner):
    # 'create' (/docs) returns a doc id; 'access' (/docs/<id>) returns the doc.
    # When enforce_owner is True the actor returns 403 for a non-owner (name != 'alice').
    class DocActor(FakeActor):
        async def send(self, req):
            self.sent.append(req)
            if req.target.startswith("/docs/"):  # access step: /docs/<id>
                if enforce_owner and self.name != "alice":
                    return response(b"forbidden", status=b"403 Forbidden")
                return response(b"secret-doc-body")
            # create step: /docs
            return response(b'{"id":"42"}', headers=b"Content-Type: application/json\r\n")

    return DocActor


def _flow(actor):
    return Flow(
        actor=actor,
        steps=[
            Step(
                "create",
                request=Request.from_url("http://t/docs"),
                capture=[Extract("doc_id", json="$.id")],
            ),
            Step("access", request=Request.from_url("http://t/docs/{{doc_id}}")),
        ],
    )


async def test_finds_idor_when_attacker_reaches_owner_resource():
    DocActor = _owned_doc_actor(enforce_owner=False)  # no ownership check -> IDOR
    alice = DocActor(name="alice")
    bob = DocActor(name="bob")
    module = CrossUserModule(owner=alice, attacker=bob, access_steps=["access"])
    report = await FlowRunner().run(_flow(alice), module=module)
    assert report.summary()["found"] == 1
    assert report.findings[0].attack_type is AttackType.IDOR


async def test_silent_when_attacker_is_denied():
    DocActor = _owned_doc_actor(enforce_owner=True)  # ownership enforced -> no IDOR
    alice = DocActor(name="alice")
    bob = DocActor(name="bob")
    module = CrossUserModule(owner=alice, attacker=bob, access_steps=["access"])
    report = await FlowRunner().run(_flow(alice), module=module)
    assert report.summary()["found"] == 0


async def test_variant_uses_seeded_owner_id_not_a_recreated_one():
    # 'create' returns a NEW id each call; the attacker must hit the OWNER'S original
    # id (from the seeded baseline context), proving the capturing step didn't re-run.
    counter = {"n": 0}

    class CountingActor(FakeActor):
        async def send(self, req):
            self.sent.append(req)
            if req.target == "/docs":  # create
                counter["n"] += 1
                body = ('{"id":"%d"}' % counter["n"]).encode()  # noqa: UP031
                return response(body, headers=b"Content-Type: application/json\r\n")
            return response(b"doc")  # access /docs/<id>

    alice = CountingActor(name="alice")
    bob = CountingActor(name="bob")
    flow = Flow(
        actor=alice,
        steps=[
            Step(
                "create",
                request=Request.from_url("http://t/docs"),
                capture=[Extract("doc_id", json="$.id")],
            ),
            Step("access", request=Request.from_url("http://t/docs/{{doc_id}}")),
        ],
    )
    module = CrossUserModule(owner=alice, attacker=bob, access_steps=["access"])
    report = await FlowRunner().run(flow, module=module)
    # baseline created id "1"; the attacker must access /docs/1, NOT a re-created /docs/2
    assert any(req.target == "/docs/1" for req in bob.sent)
    assert all(req.target != "/docs" for req in bob.sent)  # bob never re-ran create
    assert report.summary()["found"] == 1
