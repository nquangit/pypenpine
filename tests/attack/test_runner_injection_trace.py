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
