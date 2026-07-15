from penpine.attack.models import InjectionPoint, Payload, TestCase
from penpine.attack.modules import register_builtins
from penpine.attack.runner import Runner
from penpine.attack.types import AttackType
from penpine.core.message import Request
from penpine.core.parse.http_parser import parse_response
from penpine.transport.trace import current_injection


class _CapturingSender:
    def __init__(self):
        self.seen = []

    async def send(self, request):
        self.seen.append(current_injection.get())
        return parse_response(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nok")


class _OkSender:
    async def send(self, request):
        return parse_response(b"HTTP/1.1 200 OK\r\nContent-Length: 0\r\n\r\n")


class _BoomSender:
    async def send(self, request):
        raise ConnectionRefusedError("refused")


async def test_runner_publishes_injection_during_send():
    register_builtins()
    sender = _CapturingSender()
    req = Request.from_url("http://h/search?q=1")
    report = await Runner(sender=sender, max_concurrency=1).run(req, attack=AttackType.SQLI)
    # every send saw an InjectionInfo with a locator + value (not None)
    non_baseline = [s for s in sender.seen if s is not None]
    assert non_baseline, "sender never saw injection context"
    assert all(s.locator and s.value for s in non_baseline)
    assert any("q" in s.locator for s in non_baseline)  # param:q was targeted
    # context is reset after the run
    assert current_injection.get() is None
    assert report.summary()["sent"] >= 1


async def test_attempt_resets_injection_in_context_on_both_paths():
    # Directly exercise _attempt in the test's OWN context (not inside gather),
    # so a missing `finally: reset(token)` would leak the InjectionInfo here.
    # Guards the reset on BOTH the success and the caught-exception paths.
    r = Runner(sender=_OkSender())
    base = Request.from_url("http://h/search?q=1")
    tc = TestCase(
        point=InjectionPoint(expr="param:q", kind="param", name="q"),
        payload=Payload("' OR 1=1"),
        attack_type=AttackType.SQLI,
    )
    assert current_injection.get() is None

    await r._attempt(base, tc, None, None, _OkSender())
    assert current_injection.get() is None  # reset after a successful send

    attempt = await r._attempt(base, tc, None, None, _BoomSender())
    assert attempt.error is not None  # send raised, captured (never-raises)
    assert current_injection.get() is None  # reset after the caught exception
