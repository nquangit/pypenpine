from penpine.attack.flow.modules.skip_step import SkipStepModule
from penpine.attack.flow.runner import FlowRunner
from penpine.attack.types import AttackType
from penpine.core.message import Request
from penpine.flow.flow import Flow
from penpine.flow.step import Step
from tests.flow._fakes import FakeActor, response


def _flow(confirm_needs_authz):
    # 'authz' gates 'confirm'. When confirm_needs_authz is True, the fake actor
    # returns 200 for confirm ONLY if the authz step ran first (secure);
    # when False, confirm returns 200 regardless (broken access control).
    state = {"authz_ran": False}

    def authz(request):
        state["authz_ran"] = True
        return response(b"authorized")

    def confirm(request):
        ok = (not confirm_needs_authz) or state["authz_ran"]
        return response(b"done") if ok else response(b"denied", status=b"403 Forbidden")

    class ScriptedActor(FakeActor):
        async def send(self, req):
            self.sent.append(req)
            if req.target.startswith("/login"):
                # Each flow run starts a fresh session: dropping 'authz' in a
                # later step must not benefit from state a *previous* run
                # (e.g. the baseline) left behind on this shared actor.
                state["authz_ran"] = False
                return response(b"ok")
            if req.target.startswith("/authz"):
                return authz(req)
            if req.target.startswith("/confirm"):
                return confirm(req)
            return response(b"ok")

    return Flow(
        actor=ScriptedActor(),
        steps=[
            Step("login", request=Request.from_url("http://t/login")),
            Step("authz", request=Request.from_url("http://t/authz")),
            Step("confirm", request=Request.from_url("http://t/confirm")),
        ],
    )


async def test_finds_broken_access_when_goal_survives_dropped_gate():
    # confirm does NOT actually require authz -> dropping authz still yields 200 -> finding
    report = await FlowRunner().run(_flow(confirm_needs_authz=False), module=SkipStepModule())
    targets = {f.target for f in report.findings}
    assert "authz" in targets  # dropping the authz gate still reached a 200 confirm
    assert all(f.attack_type is AttackType.BROKEN_ACCESS for f in report.findings)


async def test_silent_when_dropping_gate_breaks_goal():
    # confirm truly requires authz -> dropping authz makes confirm 403 -> no finding for authz
    report = await FlowRunner().run(_flow(confirm_needs_authz=True), module=SkipStepModule())
    targets = {f.target for f in report.findings}
    assert "authz" not in targets
