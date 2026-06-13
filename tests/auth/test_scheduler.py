import asyncio

from penpine.auth.scheduler import RefreshScheduler
from penpine.auth.manager import SessionManager
from penpine.auth.provider import AuthProvider
from penpine.auth.scheme import BearerAuth
from penpine.auth.session import Session
from penpine.auth.exceptions import LoginError
from tests.auth._fakes import FakeEngine


class CountingProvider(AuthProvider):
    def __init__(self, fail_on=None):
        self.logins = 0
        self.fail_on = fail_on

    async def login(self, engine):
        self.logins += 1
        if self.fail_on is not None and self.logins == self.fail_on:
            raise LoginError("boom")
        return Session(token=f"t{self.logins}")


def manager(provider):
    return SessionManager(provider, BearerAuth(), auth_engine=FakeEngine([]))


async def test_scheduler_fires_periodically():
    provider = CountingProvider()
    mgr = manager(provider)
    sched = RefreshScheduler(mgr, every=0.02)
    await sched.start()
    await asyncio.sleep(0.09)
    await sched.stop()
    assert provider.logins >= 2


async def test_stop_halts_refreshes():
    provider = CountingProvider()
    mgr = manager(provider)
    sched = RefreshScheduler(mgr, every=0.02)
    await sched.start()
    await asyncio.sleep(0.05)
    await sched.stop()
    count = provider.logins
    await asyncio.sleep(0.05)
    assert provider.logins == count


async def test_scheduler_survives_login_error():
    provider = CountingProvider(fail_on=2)
    mgr = manager(provider)
    sched = RefreshScheduler(mgr, every=0.02)
    await sched.start()
    await asyncio.sleep(0.09)
    running = not sched._task.done()
    await sched.stop()
    assert running
    assert provider.logins >= 3


async def test_scheduler_survives_transport_error():
    from penpine.transport.exceptions import TransportError

    class BoomProvider(AuthProvider):
        def __init__(self):
            self.logins = 0

        async def login(self, engine):
            self.logins += 1
            if self.logins == 2:
                raise TransportError("net blip")
            return Session(token=f"t{self.logins}")

    provider = BoomProvider()
    sched = RefreshScheduler(manager(provider), every=0.02)
    await sched.start()
    await asyncio.sleep(0.09)
    running = not sched._task.done()
    await sched.stop()
    assert running                       # a TransportError tick did not kill the loop
    assert provider.logins >= 3


async def test_scheduler_idles_without_trigger():
    provider = CountingProvider()
    sched = RefreshScheduler(manager(provider))   # every=None, no session/expiry
    # deterministic: with nothing to schedule, a tick must NOT request a refresh
    _, should_refresh = sched._next_tick()
    assert should_refresh is False
    # and behaviorally it never proactively logs in
    await sched.start()
    await asyncio.sleep(0.1)
    await sched.stop()
    assert provider.logins == 0          # nothing to schedule -> no proactive login
